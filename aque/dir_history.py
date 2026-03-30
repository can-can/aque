# aque/dir_history.py
"""Persistence layer for directory usage history and pinning."""

import fcntl
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


class DirHistoryManager:
    def __init__(self, aque_dir: Path):
        self.aque_dir = Path(aque_dir)
        self.history_file = self.aque_dir / "dir_history.json"
        self.aque_dir.mkdir(parents=True, exist_ok=True)

    def _load_raw(self) -> dict:
        """Load JSON data, returning defaults if file doesn't exist.

        Cleans entries where the directory no longer exists on disk.
        """
        if not self.history_file.exists():
            return {"pinned": [], "history": []}

        with open(self.history_file, "r") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                return {"pinned": [], "history": []}
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

        # Clean pinned entries where directory no longer exists
        data["pinned"] = [p for p in data.get("pinned", []) if Path(p).is_dir()]

        # Clean history entries where directory no longer exists
        data["history"] = [
            h for h in data.get("history", []) if Path(h["path"]).is_dir()
        ]

        return data

    def _save(self, data: dict) -> None:
        """Atomic write using tempfile + os.replace."""
        fd, tmp_path = tempfile.mkstemp(dir=self.aque_dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, self.history_file)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def get_pinned(self) -> list[str]:
        """Return the pinned directory list."""
        return self._load_raw()["pinned"]

    def get_history(self) -> list[dict]:
        """Return history sorted by count descending."""
        data = self._load_raw()
        return sorted(data["history"], key=lambda h: h["count"], reverse=True)

    def record_use(self, path: str) -> None:
        """Increment count for path (or create with count=1). Updates last_used."""
        resolved = str(Path(path).expanduser().resolve())
        data = self._load_raw()

        now = datetime.now(timezone.utc).isoformat()
        for entry in data["history"]:
            if entry["path"] == resolved:
                entry["count"] += 1
                entry["last_used"] = now
                break
        else:
            data["history"].append(
                {"path": resolved, "count": 1, "last_used": now}
            )

        self._save(data)

    def pin(self, path: str) -> None:
        """Add path to pinned list (idempotent). Expands/resolves path."""
        resolved = str(Path(path).expanduser().resolve())
        data = self._load_raw()

        if resolved not in data["pinned"]:
            data["pinned"].append(resolved)

        self._save(data)

    def unpin(self, path: str) -> None:
        """Remove path from pinned list. Does NOT remove from history."""
        resolved = str(Path(path).expanduser().resolve())
        data = self._load_raw()

        data["pinned"] = [p for p in data["pinned"] if p != resolved]

        self._save(data)

    def get_ranked_dirs(self) -> list[dict]:
        """Return pinned first, then non-pinned history sorted by frequency.

        Pinned entries include their count from history (0 if not in history).
        Max 20 non-pinned entries.
        """
        data = self._load_raw()
        pinned_set = set(data["pinned"])

        # Build a count lookup from history
        count_by_path: dict[str, int] = {}
        for h in data["history"]:
            count_by_path[h["path"]] = h["count"]

        result: list[dict] = []

        # Pinned first, in their stored order
        for p in data["pinned"]:
            result.append({"path": p, "pinned": True, "count": count_by_path.get(p, 0)})

        # Non-pinned history, sorted by count descending, max 20
        non_pinned = sorted(
            [h for h in data["history"] if h["path"] not in pinned_set],
            key=lambda h: h["count"],
            reverse=True,
        )
        for h in non_pinned[:20]:
            result.append({"path": h["path"], "pinned": False, "count": h["count"]})

        return result

    def search(self, query: str, default_dir: str) -> list[dict]:
        """Search for directories matching query.

        If empty query, returns get_ranked_dirs().
        Otherwise: substring match on path against ranked dirs.
        If fewer than 5 matches, scans default_dir 1-2 levels deep for non-hidden dirs.
        If still not enough, scans Path.home() 1 level.
        Returns list of {"path": ..., "pinned": bool, "count": int}.
        """
        if not query:
            return self.get_ranked_dirs()

        ranked = self.get_ranked_dirs()
        matches = [r for r in ranked if query.lower() in r["path"].lower()]

        if len(matches) < 5:
            # Scan default_dir 1-2 levels deep
            seen = {m["path"] for m in matches}
            fs_dirs = self._scan_dirs(Path(default_dir), max_depth=2)
            for d in fs_dirs:
                ds = str(d)
                if ds not in seen and query.lower() in ds.lower():
                    matches.append({"path": ds, "pinned": False, "count": 0})
                    seen.add(ds)

        if len(matches) < 5:
            # Scan home 1 level
            seen = {m["path"] for m in matches}
            home_dirs = self._scan_dirs(Path.home(), max_depth=1)
            for d in home_dirs:
                ds = str(d)
                if ds not in seen and query.lower() in ds.lower():
                    matches.append({"path": ds, "pinned": False, "count": 0})
                    seen.add(ds)

        return matches

    @staticmethod
    def _scan_dirs(root: Path, max_depth: int) -> list[Path]:
        """Scan for non-hidden directories up to max_depth levels below root."""
        results: list[Path] = []
        if not root.is_dir():
            return results

        def _walk(current: Path, depth: int) -> None:
            if depth > max_depth:
                return
            try:
                for entry in sorted(current.iterdir()):
                    if entry.name.startswith("."):
                        continue
                    if entry.is_dir():
                        results.append(entry)
                        if depth < max_depth:
                            _walk(entry, depth + 1)
            except PermissionError:
                pass

        _walk(root, 1)
        return results
