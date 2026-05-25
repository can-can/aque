"""Claude Code hook plugin for aque.

Installs Stop, Notification, and UserPromptSubmit hooks in
~/.claude/settings.json so that:
  - Stop / Notification → writes {"event":"stop", "source": <hook>}  (waiting)
  - UserPromptSubmit   → writes {"event":"start", "source": <hook>} (working)

The signal payload's ``source`` field carries Claude's ``hook_event_name`` from
the hook input on stdin. It lets the monitor log which event triggered a
transition — essential when a misfired hook flips an actively-running agent
to WAITING and we need to pin down *which* Claude hook fired.
"""

import json
from pathlib import Path

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
