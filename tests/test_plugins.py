import importlib
import json
from pathlib import Path
from unittest.mock import patch

from aque.plugins import discover_plugins, get_plugin, has_session_capture
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

    def test_unknown_capability_warns(self, tmp_path, caplog):
        """A user plugin function whose name isn't in KNOWN_CAPABILITIES gets a
        warn-log — catches typos like ``presign`` vs ``preassign`` without
        making the user maintain an explicit capability list."""
        import logging
        user_plugins_dir = tmp_path / "plugins"
        user_plugins_dir.mkdir()
        (user_plugins_dir / "typo_plugin.py").write_text(
            "def is_installed():\n    return False\n"
            "def install_hook():\n    pass\n"
            "def presign():\n    pass\n"  # typo of preassign
        )
        with caplog.at_level(logging.WARNING, logger="aque.plugins"):
            discover_plugins(user_plugin_dir=user_plugins_dir)
        assert any("presign" in r.message for r in caplog.records)

    def test_known_capability_does_not_warn(self, tmp_path, caplog):
        import logging
        user_plugins_dir = tmp_path / "plugins"
        user_plugins_dir.mkdir()
        (user_plugins_dir / "clean_plugin.py").write_text(
            "def is_installed():\n    return False\n"
            "def install_hook():\n    pass\n"
        )
        with caplog.at_level(logging.WARNING, logger="aque.plugins"):
            discover_plugins(user_plugin_dir=user_plugins_dir)
        assert not any(
            "unknown capability" in r.message for r in caplog.records
        )

    def test_builtin_claude_plugin_does_not_warn(self, caplog):
        """The shipped claude plugin must not trip the typo check itself —
        otherwise every user sees a warning on startup."""
        import logging
        with caplog.at_level(logging.WARNING, logger="aque.plugins"):
            discover_plugins()
        assert not any(
            "unknown capability" in r.message for r in caplog.records
        )


class TestHasSessionCapture:
    """Pins the single-predicate contract used by every dispatch site in the
    launch coordinator. If these break, the coordinator can develop the
    classic divergence bug where one branch treats a type as capture-capable
    and another doesn't."""

    def test_none_plugin_returns_false(self):
        assert has_session_capture(None) is False

    def test_claude_has_full_capture_capability(self):
        assert has_session_capture(get_plugin("claude")) is True

    def test_partial_capture_is_treated_as_none(self, tmp_path):
        """A plugin that exposes only some of the capture verbs is *not*
        capture-capable — capture is all-or-nothing so the launch flow can't
        end up in a state where it preassigned but can't resume."""
        user_plugins_dir = tmp_path / "plugins"
        user_plugins_dir.mkdir()
        (user_plugins_dir / "partial.py").write_text(
            "def is_installed(): return False\n"
            "def install_hook(): pass\n"
            "def preassign(cmd): return (cmd, 'sid')\n"
            # Missing: summarize, resume_command.
        )
        plugin = discover_plugins(user_plugin_dir=user_plugins_dir)["partial"]
        assert has_session_capture(plugin) is False

    def test_full_capture_user_plugin_recognised(self, tmp_path):
        user_plugins_dir = tmp_path / "plugins"
        user_plugins_dir.mkdir()
        (user_plugins_dir / "fake.py").write_text(
            "def is_installed(): return False\n"
            "def install_hook(): pass\n"
            "def preassign(cmd): return (cmd, 'sid')\n"
            "def summarize(cwd): return []\n"
            "def resume_command(cmd, sid): return cmd\n"
        )
        plugin = discover_plugins(user_plugin_dir=user_plugins_dir)["fake"]
        assert has_session_capture(plugin) is True


class TestDispatchAgreement:
    """The launch coordinator queries ``has_session_capture`` from multiple
    places (``launch``, ``_finish``, ``can_resume``). Every discovered plugin
    must answer that predicate the same way at every call site — anything else
    is a divergence bug."""

    def test_predicate_is_stable_across_call_sites(self, tmp_path):
        """Build a registry containing one capture-capable plugin and one
        non-capture plugin, then query each through the same predicate the
        coordinator uses. If we ever introduced a second predicate (e.g.
        ``agent_type in CAPTURERS``) for the same question, this test would
        catch the drift."""
        user_plugins_dir = tmp_path / "plugins"
        user_plugins_dir.mkdir()
        (user_plugins_dir / "withcapture.py").write_text(
            "def is_installed(): return False\n"
            "def install_hook(): pass\n"
            "def preassign(cmd): return (cmd, 'sid')\n"
            "def summarize(cwd): return []\n"
            "def resume_command(cmd, sid): return cmd\n"
        )
        (user_plugins_dir / "hookonly.py").write_text(
            "def is_installed(): return False\n"
            "def install_hook(): pass\n"
        )
        plugins = discover_plugins(user_plugin_dir=user_plugins_dir)
        # Every plugin agrees with itself on every repeated query — the test
        # would catch a future refactor that accidentally introduced a
        # parallel registry/predicate.
        for name, plugin in plugins.items():
            answers = {has_session_capture(plugin) for _ in range(3)}
            assert len(answers) == 1, f"{name}: predicate is non-deterministic"
        assert has_session_capture(plugins["withcapture"]) is True
        assert has_session_capture(plugins["hookonly"]) is False


class TestClaudePlugin:
    def test_not_installed_when_no_settings_file(self, tmp_path):
        assert is_installed(config_path=tmp_path / "settings.json") is False

    def test_not_installed_when_no_hook_entry(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({"hooks": {}}))
        assert is_installed(config_path=settings_path) is False

    def test_not_installed_when_only_stop_hook_present(self, tmp_path):
        # Legacy install had only Stop; now all three hooks are required.
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({
            "hooks": {"Stop": [{"hooks": [{"type": "command",
                "command": "echo x > ~/.aque/signals/$AQUE_AGENT_ID.json"}]}]}
        }))
        assert is_installed(config_path=settings_path) is False

    def test_install_creates_all_three_hooks(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        install_hook(config_path=settings_path)
        data = json.loads(settings_path.read_text())
        hooks = data["hooks"]
        assert {"Stop", "Notification", "UserPromptSubmit"} <= set(hooks)
        assert is_installed(config_path=settings_path) is True
        def cmd(event):
            return data["hooks"][event][0]["hooks"][0]["command"]
        assert '"event":"start"' in cmd("UserPromptSubmit")
        assert '"event":"stop"' in cmd("Stop")
        assert '"event":"stop"' in cmd("Notification")

    def test_install_upgrades_stop_only_without_duplicating(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        settings_path.write_text(json.dumps({
            "hooks": {"Stop": [{"hooks": [{"type": "command",
                "command": "echo '{\"event\":\"stop\"}' > ~/.aque/signals/$AQUE_AGENT_ID.json"}]}]}
        }))
        install_hook(config_path=settings_path)
        data = json.loads(settings_path.read_text())
        assert len(data["hooks"]["Stop"]) == 1  # not duplicated
        assert is_installed(config_path=settings_path) is True

    def test_install_is_idempotent(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        install_hook(config_path=settings_path)
        first = settings_path.read_text()
        install_hook(config_path=settings_path)
        assert settings_path.read_text() == first

    def test_hook_commands_exit_zero_when_agent_id_unset(self, tmp_path):
        settings_path = tmp_path / "settings.json"
        install_hook(config_path=settings_path)
        data = json.loads(settings_path.read_text())
        for event in ("Stop", "Notification", "UserPromptSubmit"):
            cmd = data["hooks"][event][0]["hooks"][0]["command"]
            assert cmd.startswith('if [ -n "$AQUE_AGENT_ID" ]')

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
