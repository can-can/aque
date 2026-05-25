"""Claude Code plugin for aque.

Two capability bundles live here:

* **Hooks** — ``is_installed`` / ``install_hook`` configure Stop,
  Notification, and UserPromptSubmit hooks in ~/.claude/settings.json so:
    - Stop / Notification → writes {"event":"stop", "source": <hook>}  (waiting)
    - UserPromptSubmit   → writes {"event":"start", "source": <hook>} (working)
  The signal payload's ``source`` field carries Claude's ``hook_event_name``
  so the monitor can log which hook fired a transition — essential when a
  misfired hook flips a running agent to WAITING.

* **Session capture** — ``preassign`` / ``summarize`` / ``existing_uuids`` /
  ``resume_command`` let the launch coordinator preassign a session UUID at
  launch time, list prior sessions for the resume picker, and rewrite a
  command to resume a chosen session.
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

DEFAULT_CONFIG_PATH = Path.home() / ".claude" / "settings.json"


# Each hook reads its stdin (Claude passes JSON with `hook_event_name`),
# extracts the event name with sed, and writes a signal payload that carries
# it forward to the monitor as ``source``. Commands must always exit 0:
# a non-zero hook makes Claude Code report a hook error even when there's no
# aque agent. The ``if [ -n … ]`` form exits 0 when AQUE_AGENT_ID is unset.
def _cmd(event: str) -> str:
    # ``[ ! -t 0 ]`` guards the cat: when Claude invokes the hook, stdin is a
    # closed pipe carrying the JSON payload, so cat reads it then sees EOF.
    # In tests / interactive shells stdin is a tty, where cat would block
    # forever; we skip reading and the source falls through to ``unknown``.
    return (
        "if [ -n \"$AQUE_AGENT_ID\" ]; then "
        "INPUT=''; "
        "if [ ! -t 0 ]; then INPUT=$(cat 2>/dev/null || true); fi; "
        "SRC=$(printf '%s' \"$INPUT\" | sed -n 's/.*\"hook_event_name\":\"\\([^\"]*\\)\".*/\\1/p' | head -1); "
        ": \"${SRC:=unknown}\"; "
        f"printf '{{\"event\":\"{event}\",\"source\":\"%s\"}}\\n' \"$SRC\" "
        "> ~/.aque/signals/$AQUE_AGENT_ID.json; "
        "fi"
    )


# Claude hook event -> aque signal event.
_HOOKS = {
    "Stop": _cmd("stop"),
    "Notification": _cmd("stop"),
    "UserPromptSubmit": _cmd("start"),
}

# Backwards-compatible alias — existing tests import this name directly.
AQUE_HOOK_COMMAND = _HOOKS["Stop"]


def _aque_hook_in(entries: list) -> dict | None:
    """Return the aque hook dict within a list of hook entries, or None."""
    for entry in entries:
        for hook in entry.get("hooks", []):
            if "aque/signals" in hook.get("command", ""):
                return hook
    return None


def _load(config_path: Path) -> dict:
    if not config_path.exists():
        return {}
    try:
        return json.loads(config_path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def is_installed(config_path: Path = DEFAULT_CONFIG_PATH) -> bool:
    """True only if an aque hook with the current command is configured for
    every required event. A stale command (from an older aque version) counts
    as not-installed so the next launch upgrades it in place."""
    hooks = _load(config_path).get("hooks", {})
    for event, expected in _HOOKS.items():
        existing = _aque_hook_in(hooks.get(event, []))
        if existing is None or existing.get("command") != expected:
            return False
    return True


def install_hook(config_path: Path = DEFAULT_CONFIG_PATH) -> None:
    """Add or upgrade the aque Stop/Notification/UserPromptSubmit hooks."""
    data = _load(config_path)
    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
    hooks = data.setdefault("hooks", {})
    for event, command in _HOOKS.items():
        entries = hooks.setdefault(event, [])
        existing = _aque_hook_in(entries)
        if existing is not None:
            existing["command"] = command  # upgrade in place
        else:
            entries.append({"hooks": [{"type": "command", "command": command}]})
    config_path.write_text(json.dumps(data, indent=2) + "\n")


# ── Session capture ─────────────────────────────────────────────────


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

    Idempotent: if ``command`` already carries ``--session-id`` (preassigned
    at launch time) the command is already resumable in-place and is returned
    unchanged. Owning idempotency here keeps the launch coordinator free of
    claude-specific flag knowledge.
    """
    if "--session-id" in command:
        return command
    return [*command, "--resume", session_id]


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
