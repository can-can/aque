"""Codex CLI hook plugin for aque.

Installs a Stop hook in ~/.codex/hooks.json and enables codex_hooks in
~/.codex/config.toml. Writes a helper shell script to ~/.aque/hooks/.
"""

import json
from pathlib import Path

DEFAULT_HOOKS_PATH = Path.home() / ".codex" / "hooks.json"
DEFAULT_CONFIG_PATH = Path.home() / ".codex" / "config.toml"
STOP_SCRIPT_PATH = Path.home() / ".aque" / "hooks" / "codex-stop.sh"

STOP_SCRIPT = """\
#!/bin/sh
read -r _input
mkdir -p ~/.aque/signals
echo '{"event":"stop"}' > ~/.aque/signals/${AQUE_AGENT_ID}.json
echo '{}'
"""

AQUE_HOOK_ENTRY = {
    "hooks": [{"type": "command", "command": str(STOP_SCRIPT_PATH), "timeout": 10}]
}


def is_installed(hooks_path: Path = DEFAULT_HOOKS_PATH) -> bool:
    if not hooks_path.exists():
        return False
    try:
        data = json.loads(hooks_path.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    for entry in data.get("hooks", {}).get("Stop", []):
        for hook in entry.get("hooks", []):
            if "aque" in hook.get("command", ""):
                return True
    return False


def install_hook(
    hooks_path: Path = DEFAULT_HOOKS_PATH,
    config_path: Path = DEFAULT_CONFIG_PATH,
) -> None:
    if is_installed(hooks_path=hooks_path):
        return

    # Write stop script
    STOP_SCRIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    STOP_SCRIPT_PATH.write_text(STOP_SCRIPT)
    STOP_SCRIPT_PATH.chmod(0o755)

    # Merge Stop hook into hooks.json
    hooks_path.parent.mkdir(parents=True, exist_ok=True)
    if hooks_path.exists():
        try:
            data = json.loads(hooks_path.read_text())
        except (json.JSONDecodeError, OSError):
            data = {}
    else:
        data = {}
    data.setdefault("hooks", {}).setdefault("Stop", []).append(AQUE_HOOK_ENTRY)
    hooks_path.write_text(json.dumps(data, indent=2) + "\n")

    # Ensure [features] codex_hooks = true in config.toml
    config_path.parent.mkdir(parents=True, exist_ok=True)
    text = config_path.read_text() if config_path.exists() else ""
    if "codex_hooks" not in text:
        addition = "\n[features]\ncodex_hooks = true\n"
        config_path.write_text(text + addition)
