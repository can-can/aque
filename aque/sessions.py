"""Per-type session-ID capture and resume-command logic for aque.

Each capturer knows where its agent type stores session files for a given
working directory and how to rewrite a launch command to resume an existing
session. Aque uses these to enable the Resume action in the orphan modal
without installing any hooks.
"""

from pathlib import Path
from typing import Protocol


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


CAPTURERS: dict[str, SessionCapturer] = {
    "claude": ClaudeCapturer(),
}
