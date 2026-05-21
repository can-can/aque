"""Claude Code hook plugin for aque.

Installs Stop, Notification, and UserPromptSubmit hooks in
~/.claude/settings.json so that:
  - Stop / Notification → writes {"event":"stop"}  (agent waiting / turn done)
  - UserPromptSubmit   → writes {"event":"start"} (user sent a prompt = working)
"""

import json
from pathlib import Path

DEFAULT_CONFIG_PATH = Path.home() / ".claude" / "settings.json"

# Commands must always exit 0: a non-zero hook makes Claude Code report a hook
# error even when there's no aque agent. The `if [ -n … ]` form exits 0 when
# AQUE_AGENT_ID is unset.
def _cmd(event: str) -> str:
    return (
        "if [ -n \"$AQUE_AGENT_ID\" ]; then "
        f"echo '{{\"event\":\"{event}\"}}' > ~/.aque/signals/$AQUE_AGENT_ID.json; "
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
    """True only if an aque hook is configured for every required event."""
    hooks = _load(config_path).get("hooks", {})
    return all(_aque_hook_in(hooks.get(event, [])) is not None for event in _HOOKS)


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
