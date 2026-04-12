"""Gemini CLI hook plugin for aque.

Installs an AfterAgent hook in ~/.gemini/settings.json that writes a signal
file when Gemini finishes a turn.
"""

import json
from pathlib import Path

DEFAULT_CONFIG_PATH = Path.home() / ".gemini" / "settings.json"

AQUE_HOOK_COMMAND = (
    "echo '{\"event\":\"stop\"}' > ~/.aque/signals/$AQUE_AGENT_ID.json && echo '{}'"
)

AQUE_HOOK_ENTRY = {
    "hooks": [{"type": "command", "command": AQUE_HOOK_COMMAND}]
}


def _has_aque_hook(entries: list) -> bool:
    for entry in entries:
        for hook in entry.get("hooks", []):
            if "aque/signals" in hook.get("command", ""):
                return True
    return False


def is_installed(config_path: Path = DEFAULT_CONFIG_PATH) -> bool:
    if not config_path.exists():
        return False
    try:
        data = json.loads(config_path.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    return _has_aque_hook(data.get("hooks", {}).get("AfterAgent", []))


def install_hook(config_path: Path = DEFAULT_CONFIG_PATH) -> None:
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
    hooks.setdefault("AfterAgent", []).append(AQUE_HOOK_ENTRY)
    config_path.write_text(json.dumps(data, indent=2) + "\n")
