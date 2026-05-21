import copy
from pathlib import Path

import yaml


_projects_dir = Path.home() / "Projects"
DEFAULT_CONFIG = {
    "idle_timeout": 15,
    "stall_timeout": 600,
    "snapshot_interval": 2,
    "action_keys": {
        "dismiss": "d",
        "done": "k",
        "skip": "s",
        "hold": "h",
    },
    "queue_order": "fifo",
    "session_prefix": "aque",
    "default_dir": str(_projects_dir) if _projects_dir.exists() else str(Path.home()),
    "responder_enabled": True,
    "responder_command": ["claude"],
    "responder_idle_gap": 30,
    "responder_dir": None,
    "shortcuts": {
        # Reserved Ctrl+Shift command layer — terminals don't distinguish
        # Ctrl+Shift+<letter> from Ctrl+<letter>, so these never collide with
        # the agent's own keys. Rebind freely.
        "quit": "ctrl+shift+q",
        "attach_fullscreen": "f2",
        "next_agent": "ctrl+shift+j",
        "prev_agent": "ctrl+shift+k",
        "new_agent": "ctrl+shift+n",
        "kill_agent": "ctrl+shift+x",
        "hold_agent": "ctrl+shift+h",
        "toggle_auto": "ctrl+shift+a",
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(aque_dir: Path) -> dict:
    config_path = Path(aque_dir) / "config.yaml"
    if not config_path.exists():
        return copy.deepcopy(DEFAULT_CONFIG)
    with open(config_path) as f:
        user_config = yaml.safe_load(f) or {}
    return _deep_merge(DEFAULT_CONFIG, user_config)
