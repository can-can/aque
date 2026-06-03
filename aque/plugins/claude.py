"""Claude Code plugin for aque — session capture only.

The Claude plugin used to also install Stop/Notification/UserPromptSubmit
hooks in ``~/.claude/settings.json`` so the monitor could flip state via
signal files. Those hooks proved too eager (the Stop hook fires on every
Claude turn, repeatedly demoting RUNNING agents to WAITING), so detection
was unified on content polling and the hook installer was removed.

What remains is the **session capture** bundle the launch coordinator
uses to preassign a session UUID at launch time, list prior sessions for
the resume picker, and rewrite a command to resume a chosen session.
"""

import json
import uuid as _uuid
from datetime import datetime, timezone
from pathlib import Path

from aque.sessions import (
    SessionSummary,
    _extract_text,
    _read_last_user_or_assistant,
    _truncate,
)


def _session_dir(cwd: str) -> Path:
    """Claude stores each session as ``~/.claude/projects/<slug>/<uuid>.jsonl``
    where slug is ``cwd`` with ``/`` replaced by ``-``."""
    slug = cwd.replace("/", "-")
    return Path.home() / ".claude" / "projects" / slug


def existing_uuids(cwd: str) -> set[str]:
    d = _session_dir(cwd)
    if not d.is_dir():
        return set()
    return {p.stem for p in d.glob("*.jsonl")}


def preassign(command: list[str]) -> tuple[list[str], str]:
    """Append ``--session-id <fresh-uuid>`` so the launching process never
    races the monitor to discover the session file. Returns the rewritten
    command and the generated UUID."""
    sid = str(_uuid.uuid4())
    return ([*command, "--session-id", sid], sid)


def resume_command(command: list[str], session_id: str) -> list[str]:
    """Return a command that resumes claude session ``session_id``.

    A captured agent's stored command carries the ``--session-id <uuid>`` that
    ``preassign`` wrote at launch. That flag *creates* a session with the given
    id — re-running it makes claude refuse ("session id already in use"). To
    reopen the conversation claude needs ``--resume <uuid>`` instead, so we drop
    any preassigned ``--session-id`` here and append ``--resume``.

    Idempotent across repeated resumes: a stale ``--resume <uuid>`` (left by a
    prior resume) is stripped too, so the result never accumulates duplicate
    flags. Owning this rewrite keeps the launch coordinator free of
    claude-specific flag knowledge.
    """
    out: list[str] = []
    skip_next = False
    for arg in command:
        if skip_next:
            skip_next = False
            continue
        if arg in ("--session-id", "--resume"):
            skip_next = True  # drop the flag and its value
            continue
        out.append(arg)
    return [*out, "--resume", session_id]


def summarize(cwd: str) -> list[SessionSummary]:
    """Return one ``SessionSummary`` per ``*.jsonl`` under the Claude project
    dir for ``cwd``, newest first by file mtime. Used by the resume picker."""
    d = _session_dir(cwd)
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
