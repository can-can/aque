"""A pyte-backed terminal session driven by a PTY running `tmux attach`.

`PtySession` wraps a `pyte.Screen` + `pyte.ByteStream` (the emulator) and,
when `spawn()` is called, a real PTY whose master fd is read into the screen.
Tests construct it without spawning and `feed()` bytes directly.
"""

from __future__ import annotations

import fcntl
import os
import signal
import struct
import termios

import pyte


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
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None
        if self._pid is not None:
            try:
                os.kill(self._pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            # Reap so the terminated tmux client doesn't linger as a zombie.
            try:
                os.waitpid(self._pid, 0)
            except (ChildProcessError, OSError):
                pass
            self._pid = None
