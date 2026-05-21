"""A pyte-backed terminal session driven by a PTY running `tmux attach`.

`PtySession` wraps a `pyte.Screen` + `pyte.ByteStream` (the emulator) and,
when `spawn()` is called, a real PTY whose master fd is read into the screen.
Tests construct it without spawning and `feed()` bytes directly.
"""

from __future__ import annotations

import asyncio
import fcntl
import os
import pty
import signal
import struct
import subprocess
import termios
import threading
from typing import Callable

import pyte


def _make_controlling_tty() -> None:
    """preexec_fn (runs in the child, post-fork/pre-exec): become a session
    leader and adopt the slave PTY (fd 0) as the controlling terminal, so the
    child program behaves as a real TTY and receives SIGWINCH on resize.

    Only raw syscalls here — no Python-level locks — so it is safe after a
    subprocess fork even in a multithreaded parent."""
    os.setsid()
    fcntl.ioctl(0, termios.TIOCSCTTY, 0)


# (No os.fork-based reaping helper: subprocess.Popen.wait() reaps the child.)


class _EmbeddedScreen(pyte.Screen):
    """pyte screen hardened against sequences real terminals (tmux) emit that
    pyte 0.8.2 mishandles.

    tmux sends a *private* Device Status Report (``CSI ? Ps n``); pyte dispatches
    it as ``report_device_status(Ps, private=True)`` but the base method has no
    ``private`` parameter and raises ``TypeError``, which would otherwise crash
    the embed. We accept and ignore private DSR queries and delegate the rest.
    """

    def report_device_status(self, mode, **kwargs):
        if kwargs.get("private"):
            return
        return super().report_device_status(mode)


class PtySession:
    def __init__(self, columns: int = 80, lines: int = 24):
        self.columns = columns
        self.lines = lines
        self.screen = _EmbeddedScreen(columns, lines)
        self.stream = pyte.ByteStream(self.screen)
        self._master_fd: int | None = None
        self._pid: int | None = None
        self._proc: subprocess.Popen | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        # Called (in the event-loop thread) after output is read+fed, so the
        # widget can repaint the rows pyte marked dirty.
        self.on_output: Callable[[], None] | None = None

    # emulator
    def feed(self, data: bytes) -> None:
        # Never let a single malformed/unsupported escape sequence crash the
        # embed — pyte is a partial emulator and real apps emit sequences it
        # doesn't model. Drop the offending chunk and keep the terminal alive.
        try:
            self.stream.feed(data)
        except Exception:
            pass

    def display(self) -> list[str]:
        return self.screen.display

    def cursor(self) -> tuple[int, int]:
        return (self.screen.cursor.x, self.screen.cursor.y)

    def buffer_line(self, y: int) -> dict:
        """Return the pyte buffer row (dict col->Char) for line y."""
        return self.screen.buffer[y]

    def dirty_lines(self) -> set[int]:
        return set(self.screen.dirty)

    def clear_dirty(self) -> None:
        self.screen.dirty.clear()

    def resize(self, lines: int, columns: int) -> None:
        self.lines = lines
        self.columns = columns
        self.screen.resize(lines, columns)
        if self._master_fd is not None:
            self._set_winsize(lines, columns)

    # real PTY
    def spawn(self, argv: list[str]) -> None:
        """Run argv on a new PTY.

        Uses ``subprocess`` (whose C-level fork+exec bypasses CPython's at-fork
        handlers) rather than ``os.forkpty()``. ``os.fork``/``forkpty`` acquire
        the import/IO locks via at-fork handlers; in a multithreaded runtime
        (Textual's input thread, libtmux subprocesses) that can deadlock the
        event-loop thread if another thread holds one — freezing the whole UI.
        """
        master, slave = pty.openpty()
        # Size the slave before launch so the child sees the right dimensions.
        winsize = struct.pack("HHHH", self.lines, self.columns, 0, 0)
        try:
            fcntl.ioctl(slave, termios.TIOCSWINSZ, winsize)
        except OSError:
            pass
        try:
            self._proc = subprocess.Popen(
                argv,
                stdin=slave, stdout=slave, stderr=slave,
                preexec_fn=_make_controlling_tty,
                close_fds=True,
            )
        finally:
            os.close(slave)  # parent keeps only the master end
        self._pid = self._proc.pid
        self._master_fd = master
        flags = fcntl.fcntl(master, fcntl.F_GETFL)
        fcntl.fcntl(master, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        # Drive reads from the asyncio loop: the fd is watched and `_on_readable`
        # fires only when output is available — no polling. Outside a running
        # loop (e.g. unit tests) we skip registration; callers can use `read()`.
        try:
            self._loop = asyncio.get_running_loop()
            self._loop.add_reader(master, self._on_readable)
        except RuntimeError:
            self._loop = None

    def _on_readable(self) -> None:
        if self._master_fd is None:
            return
        try:
            data = os.read(self._master_fd, 4096)
        except BlockingIOError:
            return
        except OSError:
            data = b""
        if not data:
            # EOF — the child (tmux client) exited. Stop watching so a readable
            # EOF doesn't spin the loop; notify once so the final frame paints.
            self._stop_reader()
            if self.on_output is not None:
                self.on_output()
            return
        self.feed(data)
        if self.on_output is not None:
            self.on_output()

    def _stop_reader(self) -> None:
        if self._loop is not None and self._master_fd is not None:
            try:
                self._loop.remove_reader(self._master_fd)
            except Exception:
                pass

    def _set_winsize(self, lines: int, columns: int) -> None:
        if self._master_fd is None:
            return
        winsize = struct.pack("HHHH", lines, columns, 0, 0)
        fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, winsize)

    @property
    def fileno(self) -> int | None:
        return self._master_fd

    def read(self, max_bytes: int = 65536) -> bytes:
        if self._master_fd is None:
            return b""
        try:
            return os.read(self._master_fd, max_bytes)
        except (BlockingIOError, OSError):
            return b""

    def write(self, data: bytes) -> None:
        if self._master_fd is None or not data:
            return
        try:
            os.write(self._master_fd, data)
        except OSError:
            pass

    def close(self) -> None:
        self._stop_reader()
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None
        proc = self._proc
        self._proc = None
        self._pid = None
        self._loop = None
        if proc is not None and proc.poll() is None:
            try:
                proc.send_signal(signal.SIGHUP)  # detach + exit the tmux client
            except (ProcessLookupError, OSError):
                return
            # Reap off the event loop so a click/agent-switch never freezes the UI
            # while waiting for the child to exit (and no zombie lingers).
            threading.Thread(target=proc.wait, daemon=True).start()
