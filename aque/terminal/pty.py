"""A pyte-backed terminal session driven by a PTY running `tmux attach`.

`PtySession` wraps a `pyte.Screen` + `pyte.ByteStream` (the emulator) and,
when `spawn()` is called, a real PTY whose master fd is read into the screen.
Tests construct it without spawning and `feed()` bytes directly.
"""

from __future__ import annotations

import asyncio
import fcntl
import os
import signal
import struct
import termios
import threading
from typing import Callable

import pyte


def _reap_in_background(pid: int) -> None:
    """Wait on a terminated child in a throwaway daemon thread, so the UI event
    loop never blocks on a child that is slow to exit — and no zombie lingers."""
    def _wait() -> None:
        try:
            os.waitpid(pid, 0)
        except (ChildProcessError, OSError):
            pass
    threading.Thread(target=_wait, daemon=True).start()


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
        """Fork a child running argv attached to a new PTY."""
        pid, master_fd = os.forkpty()
        if pid == 0:  # child
            os.execvp(argv[0], argv)
            os._exit(127)
        self._pid = pid
        self._master_fd = master_fd
        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        self._set_winsize(self.lines, self.columns)
        # Drive reads from the asyncio loop: the fd is watched and `_on_readable`
        # fires only when output is available — no polling. Outside a running
        # loop (e.g. unit tests) we skip registration; callers can use `read()`.
        try:
            self._loop = asyncio.get_running_loop()
            self._loop.add_reader(master_fd, self._on_readable)
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
        pid = self._pid
        self._pid = None
        self._loop = None
        if pid is not None:
            try:
                os.kill(pid, signal.SIGHUP)
            except ProcessLookupError:
                return
            # Reap off the event loop so a click/agent-switch never freezes the UI
            # while waiting for the child (tmux client) to exit.
            _reap_in_background(pid)
