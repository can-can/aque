# aque/history.py
import fcntl
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


_UNSET = object()  # sentinel: caller did not pass agent_type


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

    def add_entry(self, agent_id: int, label: str, dir: str, command: list[str], created_at: str, agent_type: object = _UNSET) -> None:
        entries = self.load()
        entry: dict = {
            "id": agent_id, "label": label, "dir": dir, "command": command,
            "created_at": created_at,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
        if agent_type is not _UNSET:
            entry["agent_type"] = agent_type  # type: ignore[assignment]
        entries.append(entry)
        self._save(entries)

    def recent_tasks(self, limit: int = 10) -> list[dict]:
        """Return de-duplicated recent tasks, newest first.

        Tasks are unique by ``(dir, command)``. ``agent_type`` is backfilled
        for entries missing the field by looking at other entries that ran the
        same command with a known type. ``type_known`` is False only when the
        entry had no ``agent_type`` field *and* no type could be inferred — the
        UI uses this to prompt for a type before launching.
        """
        entries = self.load()

        # command -> agent_type, from entries that carry a real (truthy) type.
        type_by_command: dict[tuple, str] = {}
        for e in entries:
            at = e.get("agent_type")
            if at:
                type_by_command.setdefault(tuple(e.get("command", [])), at)

        tasks: list[dict] = []
        seen: set[tuple] = set()
        for e in reversed(entries):  # entries are appended oldest-first
            command = list(e.get("command", []))
            cmd_key = tuple(command)
            key = (e.get("dir"), cmd_key)
            if key in seen:
                continue
            seen.add(key)

            has_field = "agent_type" in e
            agent_type = e.get("agent_type")
            type_known = has_field
            if not has_field:
                inferred = type_by_command.get(cmd_key)
                if inferred is not None:
                    agent_type = inferred
                    type_known = True

            tasks.append({
                "label": e.get("label", ""),
                "dir": e.get("dir", ""),
                "command": command,
                "agent_type": agent_type,
                "type_known": type_known,
            })
            if len(tasks) >= limit:
                break
        return tasks

    def count(self) -> int:
        return len(self.load())

    def remove_entry(self, agent_id: int) -> None:
        """Drop the most recent history entry for ``agent_id``. Used by undo."""
        entries = self.load()
        for i in range(len(entries) - 1, -1, -1):
            if entries[i].get("id") == agent_id:
                entries.pop(i)
                self._save(entries)
                return
