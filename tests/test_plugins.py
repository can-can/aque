import importlib
from pathlib import Path
from unittest.mock import patch

from aque.plugins import discover_plugins, get_plugin


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
