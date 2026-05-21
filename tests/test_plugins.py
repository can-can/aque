import importlib
import json
from pathlib import Path
from unittest.mock import patch

from aque.plugins import discover_plugins, get_plugin
from aque.plugins.claude import is_installed, install_hook


class TestDiscoverPlugins:
    def test_discovers_builtin_claude_plugin(self):
        plugins = discover_plugins()
        assert "claude" in plugins

    def test_plugin_has_required_interface(self):
        plugins = discover_plugins()
        claude = plugins["claude"]
        assert hasattr(claude, "is_installed")
        assert hasattr(claude, "install_hook")
        assert callable(claude.is_installed)
        assert callable(claude.install_hook)

    def test_get_plugin_returns_module(self):
        plugin = get_plugin("claude")
        assert plugin is not None
        assert hasattr(plugin, "is_installed")

    def test_get_plugin_returns_none_for_unknown(self):
        plugin = get_plugin("nonexistent_agent_xyz")
        assert plugin is None

    def test_discovers_user_plugins(self, tmp_path):
        user_plugins_dir = tmp_path / "plugins"
        user_plugins_dir.mkdir()
        (user_plugins_dir / "custom_agent.py").write_text(
            "def is_installed():\n    return False\n"
            "def install_hook():\n    pass\n"
        )
        plugins = discover_plugins(user_plugin_dir=user_plugins_dir)
        assert "custom_agent" in plugins

    def test_user_plugin_overrides_builtin(self, tmp_path):
        user_plugins_dir = tmp_path / "plugins"
        user_plugins_dir.mkdir()
        (user_plugins_dir / "claude.py").write_text(
            "def is_installed():\n    return True\n"
            "def install_hook():\n    pass\n"
        )
        plugins = discover_plugins(user_plugin_dir=user_plugins_dir)
        assert plugins["claude"].is_installed() is True


class TestClaudePlugin:
    def test_not_installed_when_no_settings_file(self, tmp_path):
        assert is_installed(config_path=tmp_path / "settings.json") is False

    def test_not_installed_when_no_hook_entry(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({"hooks": {}}))
        assert is_installed(config_path=settings_path) is False

    def test_installed_when_aque_hook_present(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({
            "hooks": {
                "Stop": [{
                    "hooks": [{
                        "type": "command",
                        "command": "echo '{\"event\":\"stop\"}' > ~/.aque/signals/$AQUE_AGENT_ID.json"
                    }]
                }]
            }
        }))
        assert is_installed(config_path=settings_path) is True

    def test_install_hook_creates_settings_file(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        install_hook(config_path=settings_path)
        assert settings_path.exists()
        data = json.loads(settings_path.read_text())
        assert "hooks" in data
        assert "Stop" in data["hooks"]
        # Verify the hook command references aque signals
        hook_cmd = data["hooks"]["Stop"][0]["hooks"][0]["command"]
        assert "~/.aque/signals/$AQUE_AGENT_ID.json" in hook_cmd

    def test_install_hook_preserves_existing_settings(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({
            "permissions": {"allow": ["Bash"]},
            "hooks": {
                "PreToolUse": [{"hooks": [{"type": "command", "command": "echo pre"}]}]
            }
        }))
        install_hook(config_path=settings_path)
        data = json.loads(settings_path.read_text())
        assert data["permissions"] == {"allow": ["Bash"]}
        assert "PreToolUse" in data["hooks"]
        assert "Stop" in data["hooks"]

    def test_install_hook_appends_to_existing_stop_hooks(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({
            "hooks": {
                "Stop": [{"hooks": [{"type": "command", "command": "echo user-hook"}]}]
            }
        }))
        install_hook(config_path=settings_path)
        data = json.loads(settings_path.read_text())
        # Should have both the user's hook and aque's hook
        assert len(data["hooks"]["Stop"]) == 2

    def test_install_hook_idempotent(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        install_hook(config_path=settings_path)
        install_hook(config_path=settings_path)
        data = json.loads(settings_path.read_text())
        # Should still have exactly one aque hook entry
        aque_hooks = [
            h for h in data["hooks"]["Stop"]
            if any("aque/signals" in hh.get("command", "") for hh in h.get("hooks", []))
        ]
        assert len(aque_hooks) == 1


class TestClaudeHookCommandExitCode:
    """The Stop hook must always exit 0 — otherwise Claude Code reports a
    'Stop hook error' even when the hook correctly does nothing (no AQUE_AGENT_ID)."""

    def _run(self, env):
        import subprocess
        from aque.plugins.claude import AQUE_HOOK_COMMAND
        return subprocess.run(["bash", "-c", AQUE_HOOK_COMMAND], env=env)

    def test_exits_zero_when_agent_id_unset(self):
        import os
        env = {k: v for k, v in os.environ.items() if k != "AQUE_AGENT_ID"}
        assert self._run(env).returncode == 0

    def test_writes_signal_and_exits_zero_when_agent_id_set(self, tmp_path, monkeypatch):
        import os
        monkeypatch.setenv("HOME", str(tmp_path))      # ~ -> tmp_path
        (tmp_path / ".aque" / "signals").mkdir(parents=True)
        env = dict(os.environ, AQUE_AGENT_ID="42", HOME=str(tmp_path))
        assert self._run(env).returncode == 0
        signal = tmp_path / ".aque" / "signals" / "42.json"
        assert signal.exists()
        assert '"stop"' in signal.read_text()


class TestInstallHookUpgrade:
    def test_install_hook_upgrades_stale_command(self, tmp_path):
        from aque.plugins.claude import install_hook, AQUE_HOOK_COMMAND
        cfg = tmp_path / "settings.json"
        stale = ('[ -n "$AQUE_AGENT_ID" ] && '
                 'echo \'{"event":"stop"}\' > ~/.aque/signals/$AQUE_AGENT_ID.json')
        cfg.write_text(json.dumps(
            {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": stale}]}]}}
        ))
        install_hook(config_path=cfg)
        data = json.loads(cfg.read_text())
        cmds = [h["command"] for e in data["hooks"]["Stop"] for h in e["hooks"]]
        assert stale not in cmds                 # old command replaced
        assert AQUE_HOOK_COMMAND in cmds         # with the current one
        assert sum("aque/signals" in c for c in cmds) == 1  # not duplicated
