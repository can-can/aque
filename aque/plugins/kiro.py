"""Kiro CLI hook plugin for aque.

Installs a stop hook in ~/.kiro/agents/aque.json that writes a signal file
when Kiro finishes a turn.
"""

import json
from pathlib import Path

DEFAULT_CONFIG_PATH = Path.home() / ".kiro" / "agents" / "aque.json"

AQUE_HOOK_COMMAND = (
    "echo '{\"event\":\"stop\"}' > ~/.aque/signals/$AQUE_AGENT_ID.json"
)


def is_installed(config_path: Path = DEFAULT_CONFIG_PATH) -> bool:
    if not config_path.exists():
        return False
    try:
        data = json.loads(config_path.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    for hook in data.get("hooks", {}).get("stop", []):
        if "aque/signals" in hook.get("command", ""):
            return True
    return False


def install_hook(config_path: Path = DEFAULT_CONFIG_PATH) -> None:
    if is_installed(config_path=config_path):
        return
    config_path.parent.mkdir(parents=True, exist_ok=True)
    data = {"name": "aque", "hooks": {"stop": [{"command": AQUE_HOOK_COMMAND}]}}
    config_path.write_text(json.dumps(data, indent=2) + "\n")
