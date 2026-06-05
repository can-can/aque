import asyncio
from pathlib import Path


class StateWatcher:
    """Yield once whenever the watched file's (mtime, size) changes."""

    def __init__(self, state_file: Path, interval: float = 1.0):
        self.state_file = Path(state_file)
        self.interval = interval

    def _stamp(self) -> tuple[int, int]:
        try:
            st = self.state_file.stat()
            return (st.st_mtime_ns, st.st_size)
        except FileNotFoundError:
            return (0, 0)

    async def watch(self):
        last = self._stamp()
        while True:
            await asyncio.sleep(self.interval)
            cur = self._stamp()
            if cur != last:
                last = cur
                yield
