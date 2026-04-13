"""Append-only debug logging for investigating auto-attach issues.

Writes to ~/.aque/debug.log with ISO timestamps. Safe to call from both
the monitor daemon and the desk TUI — open/append/close per call so we
don't hold a file descriptor across forks.
"""
import os
from datetime import datetime
from pathlib import Path


def dbg(tag: str, aque_dir: Path | None = None, **fields) -> None:
    aque_dir = Path(aque_dir or Path.home() / ".aque")
    try:
        aque_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().isoformat(timespec="milliseconds")
        parts = [f"{ts} pid={os.getpid()} [{tag}]"]
        for k, v in fields.items():
            parts.append(f"{k}={v}")
        line = " ".join(parts) + "\n"
        with open(aque_dir / "debug.log", "a") as f:
            f.write(line)
    except Exception:
        pass
