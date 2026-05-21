"""Claude Code hook plugin for aque.

Installs a Stop hook in ~/.claude/settings.json that writes a signal file
when Claude Code completes a turn.
"""

import json
from pathlib import Path

DEFAULT_CONFIG_PATH = Path.home() / ".claude" / "settings.json"

# Must always exit 0: a non-zero Stop hook makes Claude Code report a
# "Stop hook error" even when there's simply no aque agent to signal. The
# `[ -n … ] && …` form exits 1 when AQUE_AGENT_ID is unset, so use if/fi.
AQUE_HOOK_COMMAND = (
    "if [ -n \"$AQUE_AGENT_ID\" ]; then "
    "echo '{\"event\":\"stop\"}' > ~/.aque/signals/$AQUE_AGENT_ID.json; "
    "fi"
)

AQUE_HOOK_ENTRY = {
    "hooks": [
        {
            "type": "command",
            "command": AQUE_HOOK_COMMAND,
        }
    ]
}


def _is_aque_hook(entry: dict) -> bool:
    """Check if a hook entry is an aque signal hook."""
    for hook in entry.get("hooks", []):
        if "aque/signals" in hook.get("command", ""):
            return True
    return False


def is_installed(config_path: Path = DEFAULT_CONFIG_PATH) -> bool:
    """Check if the aque Stop hook is already configured."""
    if not config_path.exists():
        return False
    try:
        data = json.loads(config_path.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    stop_hooks = data.get("hooks", {}).get("Stop", [])
    return any(_is_aque_hook(entry) for entry in stop_hooks)


def install_hook(config_path: Path = DEFAULT_CONFIG_PATH) -> None:
    """Add (or upgrade) the aque Stop hook in Claude Code settings."""
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text())
        except (json.JSONDecodeError, OSError):
            data = {}
    else:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        data = {}

    hooks = data.setdefault("hooks", {})
    stop_hooks = hooks.setdefault("Stop", [])

    # Self-heal: if an aque hook is already present, refresh its command.
    # Older installs shipped a command that exited non-zero when AQUE_AGENT_ID
    # was unset, which Claude Code surfaced as a "Stop hook error".
    found = False
    for entry in stop_hooks:
        for hook in entry.get("hooks", []):
            if "aque/signals" in hook.get("command", ""):
                hook["command"] = AQUE_HOOK_COMMAND
                found = True
    if not found:
        stop_hooks.append(AQUE_HOOK_ENTRY)

    config_path.write_text(json.dumps(data, indent=2) + "\n")
