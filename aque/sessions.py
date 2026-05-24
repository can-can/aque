"""Per-type session-ID capture and resume-command logic for aque.

Each capturer knows where its agent type stores session files for a given
working directory and how to rewrite a launch command to resume an existing
session. Aque uses these to enable the Resume action in the orphan modal
without installing any hooks.
"""

from pathlib import Path
from typing import Protocol


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


class SessionCapturer(Protocol):
    def session_dir(self, cwd: str) -> Path: ...
    def existing_uuids(self, cwd: str) -> set[str]: ...
    def resume_command(self, original_cmd: list[str], session_id: str) -> list[str]: ...


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


_CODEX_UUID_TOKEN_COUNT = 5  # last 5 hyphen-separated tokens of the stem form the UUID


def _extract_codex_uuid(stem: str) -> str | None:
    """Pull the UUID out of a codex session filename stem.

    Codex filenames look like:
        rollout-<YYYY>-<MM>-<DD>T<HH>-<MM>-<SS>-<8>-<4>-<4>-<4>-<12>
    The last 5 hyphen-separated tokens form the UUID.
    """
    parts = stem.split("-")
    if len(parts) < _CODEX_UUID_TOKEN_COUNT + 1:
        return None
    return "-".join(parts[-_CODEX_UUID_TOKEN_COUNT:])


class CodexCapturer:
    """Capture Codex session UUIDs.

    Codex stores sessions under `~/.codex/sessions/<YYYY>/<MM>/<DD>/` with
    filenames of the form `rollout-<timestamp>-<uuid>.jsonl`. The dir is one
    tree across all cwds, so the cwd argument is ignored when listing.
    The resume command is `codex resume <uuid>`, inserted as the first
    positional after the program name so any user-supplied flags are preserved.
    """

    def session_dir(self, cwd: str) -> Path:
        return Path.home() / ".codex" / "sessions"

    def existing_uuids(self, cwd: str) -> set[str]:
        d = self.session_dir(cwd)
        if not d.is_dir():
            return set()
        uuids: set[str] = set()
        for p in d.rglob("*.jsonl"):
            uuid = _extract_codex_uuid(p.stem)
            if uuid is not None:
                uuids.add(uuid)
        return uuids

    def resume_command(self, original_cmd: list[str], session_id: str) -> list[str]:
        return [original_cmd[0], "resume", session_id, *original_cmd[1:]]


CAPTURERS: dict[str, SessionCapturer] = {
    "claude": ClaudeCapturer(),
    "codex": CodexCapturer(),
}
