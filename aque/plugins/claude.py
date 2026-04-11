"""Claude Code hook plugin for aque.

Installs a Stop hook in ~/.claude/settings.json that writes a signal file
when Claude Code completes a turn.
"""

import json
from pathlib import Path

DEFAULT_CONFIG_PATH = Path.home() / ".claude" / "settings.json"

AQUE_HOOK_COMMAND = (
    "echo '{\"event\":\"stop\"}' > ~/.aque/signals/$AQUE_AGENT_ID.json"
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
    """Add the aque Stop hook to Claude Code settings."""
    if is_installed(config_path=config_path):
        return

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
    stop_hooks.append(AQUE_HOOK_ENTRY)

    config_path.write_text(json.dumps(data, indent=2) + "\n")
