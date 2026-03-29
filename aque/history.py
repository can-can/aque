# aque/history.py
import fcntl
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


class HistoryManager:
    def __init__(self, aque_dir: Path):
        self.aque_dir = Path(aque_dir)
        self.history_file = self.aque_dir / "history.json"
        self.aque_dir.mkdir(parents=True, exist_ok=True)

    def load(self) -> list[dict]:
        if not self.history_file.exists():
            return []
        with open(self.history_file, "r") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            try:
                data = json.load(f)
                return data.get("agents", [])
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def _save(self, entries: list[dict]) -> None:
        fd, tmp_path = tempfile.mkstemp(dir=self.aque_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump({"agents": entries}, f, indent=2)
            os.replace(tmp_path, self.history_file)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def add_entry(self, agent_id: int, label: str, dir: str, command: list[str], created_at: str) -> None:
        entries = self.load()
        entries.append({
            "id": agent_id, "label": label, "dir": dir, "command": command,
            "created_at": created_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        self._save(entries)

    def count(self) -> int:
        return len(self.load())
