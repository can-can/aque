"""Per-type session-ID capture and resume-command logic for aque.

Each capturer knows where its agent type stores session files for a given
working directory and how to rewrite a launch command to resume an existing
session. Aque uses these to enable the Resume action in the orphan modal
without installing any hooks.
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple, Protocol


class SessionSummary(NamedTuple):
    """Lightweight metadata for one prior agent session, used by the
    create-time resume picker.

    Construct via the capturer's `summarize()` method, not directly.
    `mtime` is a real `datetime` (caller is responsible for wrapping
    `path.stat().st_mtime` with `datetime.fromtimestamp(..., tz=timezone.utc)`
    before passing it in).
    """
    uuid: str
    first_prompt: str | None    # first non-meta user message, ~80 chars
    last_activity: str | None   # last user or assistant message, ~80 chars
    mtime: datetime             # file mtime (proxy for "last active")
    size_bytes: int             # file size


def _read_last_line(path: Path, window: int = 8192) -> str | None:
    """Read the last non-empty line of a file without loading the whole thing.

    Seeks `window` bytes from EOF and walks forward. Doubles the window if the
    last line is bigger than it. Returns None for missing or empty files.
    """
    try:
        size = path.stat().st_size
    except (FileNotFoundError, OSError):
        return None
    if size == 0:
        return None
    with path.open("rb") as f:
        read = min(window, size)
        while True:
            f.seek(size - read)
            chunk = f.read(read)
            # Drop trailing newlines so we don't return "".
            chunk = chunk.rstrip(b"\r\n")
            nl = chunk.rfind(b"\n")
            if nl != -1:
                return chunk[nl + 1:].rstrip(b"\r").decode("utf-8", errors="replace")
            if read >= size:
                # Whole file is one line.
                return chunk.rstrip(b"\r").decode("utf-8", errors="replace")
            read = min(read * 2, size)


def _read_last_user_or_assistant(path: Path, window: int = 65536) -> tuple[str | None, str | None]:
    """Walk backwards through the last `window` bytes of a jsonl file to find
    the most-recent entry whose type is "user" or "assistant" (and is not a
    meta entry).

    Returns (content_text, role) for the first such match found from the end,
    or (None, None) if none is found within the window (or if the file is
    missing/empty).
    """
    try:
        size = path.stat().st_size
    except (FileNotFoundError, OSError):
        return (None, None)
    if size == 0:
        return (None, None)
    with path.open("rb") as f:
        read = min(window, size)
        f.seek(size - read)
        chunk = f.read(read)
    # Split into lines and walk backwards.
    lines = chunk.split(b"\n")
    for raw in reversed(lines):
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw.decode("utf-8", errors="replace"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if obj.get("type") not in ("user", "assistant"):
            continue
        if obj.get("isMeta"):
            continue
        msg = obj.get("message") or {}
        text = _extract_text(msg.get("content"))
        if text is None or text.startswith("<local-command-caveat>"):
            continue
        role = obj.get("type")
        return (text, role)
    return (None, None)


def _extract_text(content) -> str | None:
    """Extract a text string from a message.content value.

    content may be a plain string or a list of {type:"text", text:...} blocks.
    Returns None for non-text shapes.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str):
                    return text
    return None


def _truncate(text: str | None, limit: int = 80) -> str | None:
    if text is None:
        return None
    # Collapse newlines to spaces for single-line display.
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    return flat[:limit] + "…"


class SessionCapturer(Protocol):
    def session_dir(self, cwd: str) -> Path: ...
    def existing_uuids(self, cwd: str) -> set[str]: ...
    def resume_command(self, original_cmd: list[str], session_id: str) -> list[str]: ...
    def preassign(self, original_cmd: list[str]) -> tuple[list[str], str] | None: ...
    def summarize(self, cwd: str) -> list[SessionSummary]: ...


class ClaudeCapturer:
    """Capture Claude Code session UUIDs.

    Claude stores each session as `~/.claude/projects/<slug>/<uuid>.jsonl`
    where slug is the cwd with `/` replaced by `-`.
    """

    def session_dir(self, cwd: str) -> Path:
        slug = cwd.replace("/", "-")
        return Path.home() / ".claude" / "projects" / slug

    def existing_uuids(self, cwd: str) -> set[str]:
        d = self.session_dir(cwd)
        if not d.is_dir():
            return set()
        return {p.stem for p in d.glob("*.jsonl")}

    def resume_command(self, original_cmd: list[str], session_id: str) -> list[str]:
        return [*original_cmd, "--resume", session_id]

    def preassign(self, original_cmd: list[str]) -> tuple[list[str], str]:
        sid = str(uuid.uuid4())
        return ([*original_cmd, "--session-id", sid], sid)

    def summarize(self, cwd: str) -> list[SessionSummary]:
        d = self.session_dir(cwd)
        if not d.is_dir():
            return []

        summaries: list[SessionSummary] = []
        for path in d.glob("*.jsonl"):
            uuid_str = path.stem
            first_prompt: str | None = None
            last_activity: str | None = None
            try:
                stat = path.stat()
                with path.open("r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if obj.get("type") != "user":
                            continue
                        if obj.get("isMeta"):
                            continue
                        msg = obj.get("message") or {}
                        text = _extract_text(msg.get("content"))
                        if text is None or text.startswith("<local-command-caveat>"):
                            continue
                        first_prompt = text
                        break

                last_text, _last_role = _read_last_user_or_assistant(path)
                last_activity = last_text  # may be None

                summaries.append(SessionSummary(
                    uuid=uuid_str,
                    first_prompt=_truncate(first_prompt),
                    last_activity=_truncate(last_activity),
                    mtime=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                    size_bytes=stat.st_size,
                ))
            except OSError:
                continue

        summaries.sort(key=lambda s: s.mtime, reverse=True)
        return summaries


CAPTURERS: dict[str, SessionCapturer] = {
    "claude": ClaudeCapturer(),
}
