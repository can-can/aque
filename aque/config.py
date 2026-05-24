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
        # Priority chords — these work even while the embedded terminal is
        # focused (plain letters go to the agent and are gated by check_action).
        # We avoid F-keys, which terminal apps consume. Rebind freely.
        "quit": "ctrl+shift+q",
        "attach_fullscreen": "ctrl+shift+f",
        "next_agent": "ctrl+shift+j",
        "prev_agent": "ctrl+shift+k",
        "back_to_list": "tab",
        "cycle_layout": "ctrl+shift+o",
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
