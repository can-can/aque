import asyncio
import fcntl
import os
import pty
import signal
import struct
import termios
import time


class PtyProcess:
    """Run a command in a PTY; pump bytes in/out asynchronously."""

    def __init__(self, argv: list[str]):
        self.argv = argv
        self.pid: int | None = None
        self.master_fd: int | None = None

    def start(self, cols: int = 80, rows: int = 24) -> None:
        pid, master_fd = pty.fork()
        if pid == 0:  # child: becomes the PTY session leader
            try:
                winsize = struct.pack("HHHH", rows, cols, 0, 0)
                fcntl.ioctl(0, termios.TIOCSWINSZ, winsize)  # fd 0 = controlling tty
            except OSError:
                pass
            os.execvp(self.argv[0], self.argv)
            os._exit(127)  # only reached if execvp fails
        self.pid = pid
        self.master_fd = master_fd
        os.set_blocking(master_fd, False)
        try:
            self.resize(cols, rows)  # keep the master side in sync
        except OSError:
            pass

    def write(self, data: bytes) -> None:
        if self.master_fd is not None:
            os.write(self.master_fd, data)

    def resize(self, cols: int, rows: int) -> None:
        if self.master_fd is None:
            return
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)

    async def output(self):
        """Yield output chunks until the child exits (then stop)."""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[bytes] = asyncio.Queue()
        fd = self.master_fd

        def _readable() -> None:
            if fd != self.master_fd:  # fd was closed (and may be recycled)
                return
            try:
                data = os.read(fd, 65536)
            except (BlockingIOError, InterruptedError):
                return
            except OSError:
                data = b""  # PTY closed -> EOF
            queue.put_nowait(data)

        loop.add_reader(fd, _readable)
        try:
            while True:
                chunk = await queue.get()
                if chunk == b"":
                    return
                yield chunk
        finally:
            loop.remove_reader(fd)

    def close(self) -> None:
        if self.pid is not None:
            try:
                os.kill(self.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        if self.master_fd is not None:
            try:
                os.close(self.master_fd)  # closing the master also SIGHUPs the child
            except OSError:
                pass
            self.master_fd = None
        if self.pid is not None:
            self._reap(self.pid)
            self.pid = None

    def _reap(self, pid: int) -> None:
        """Reap the child so it doesn't linger as a zombie (bounded ~100ms)."""
        for _ in range(20):
            try:
                reaped, _ = os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                return  # already reaped
            if reaped == pid:
                return
            time.sleep(0.005)
