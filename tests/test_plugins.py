from aque.plugins import discover_plugins, get_plugin, has_session_capture


class TestDiscoverPlugins:
    def test_discovers_builtin_claude_plugin(self):
        plugins = discover_plugins()
        assert "claude" in plugins

    def test_get_plugin_returns_module(self):
        plugin = get_plugin("claude")
        assert plugin is not None
        # Claude is capture-only after the hook removal — no is_installed.
        assert hasattr(plugin, "preassign")
        assert hasattr(plugin, "summarize")
        assert hasattr(plugin, "resume_command")

    def test_get_plugin_returns_none_for_unknown(self):
        plugin = get_plugin("nonexistent_agent_xyz")
        assert plugin is None

    def test_discovers_hook_only_user_plugin(self, tmp_path):
        """A user plugin exposing the hook bundle (no capture) is still valid."""
        user_plugins_dir = tmp_path / "plugins"
        user_plugins_dir.mkdir()
        (user_plugins_dir / "hookplugin.py").write_text(
            "def is_installed():\n    return False\n"
            "def install_hook():\n    pass\n"
        )
        plugins = discover_plugins(user_plugin_dir=user_plugins_dir)
        assert "hookplugin" in plugins

    def test_discovers_capture_only_user_plugin(self, tmp_path):
        """A user plugin exposing only the capture bundle (no hook) is valid —
        this is the shape the built-in claude now takes after hook removal."""
        user_plugins_dir = tmp_path / "plugins"
        user_plugins_dir.mkdir()
        (user_plugins_dir / "captureonly.py").write_text(
            "def preassign(cmd): return (cmd, 'sid')\n"
            "def summarize(cwd): return []\n"
            "def resume_command(cmd, sid): return cmd\n"
        )
        plugins = discover_plugins(user_plugin_dir=user_plugins_dir)
        assert "captureonly" in plugins

    def test_user_plugin_overrides_builtin(self, tmp_path):
        user_plugins_dir = tmp_path / "plugins"
        user_plugins_dir.mkdir()
        (user_plugins_dir / "claude.py").write_text(
            "def preassign(cmd): return (cmd, 'sid')\n"
            "def summarize(cwd): return []\n"
            "def resume_command(cmd, sid): return cmd\n"
            "def custom_marker(): return 'override'\n"
        )
        plugins = discover_plugins(user_plugin_dir=user_plugins_dir)
        assert plugins["claude"].custom_marker() == "override"

    def test_unknown_capability_warns(self, tmp_path, caplog):
        """A user plugin function whose name isn't in KNOWN_CAPABILITIES gets a
        warn-log — catches typos like ``presign`` vs ``preassign``."""
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
        user_plugins_dir = tmp_path / "plugins"
        user_plugins_dir.mkdir()
        (user_plugins_dir / "withcapture.py").write_text(
            "def preassign(cmd): return (cmd, 'sid')\n"
            "def summarize(cwd): return []\n"
            "def resume_command(cmd, sid): return cmd\n"
        )
        (user_plugins_dir / "hookonly.py").write_text(
            "def is_installed(): return False\n"
            "def install_hook(): pass\n"
        )
        plugins = discover_plugins(user_plugin_dir=user_plugins_dir)
        for name, plugin in plugins.items():
            answers = {has_session_capture(plugin) for _ in range(3)}
            assert len(answers) == 1, f"{name}: predicate is non-deterministic"
        assert has_session_capture(plugins["withcapture"]) is True
        assert has_session_capture(plugins["hookonly"]) is False


class TestClaudePluginCapture:
    """Capture-bundle contract for the built-in claude plugin."""

    def test_preassign_appends_session_id_flag(self):
        from aque.plugins.claude import preassign
        cmd, sid = preassign(["claude"])
        assert "--session-id" in cmd
        assert sid in cmd
        # New uuid each call.
        _, sid2 = preassign(["claude"])
        assert sid != sid2

    def test_resume_command_appends_resume_flag_when_not_preassigned(self):
        from aque.plugins.claude import resume_command
        result = resume_command(["claude"], "abc-123")
        assert result == ["claude", "--resume", "abc-123"]

    def test_resume_command_rewrites_preassigned_session_id_to_resume(self):
        # The stored launch command carries the preassigned ``--session-id``;
        # resuming must swap it for ``--resume`` (claude refuses to re-create a
        # session that already exists).
        from aque.plugins.claude import resume_command
        out = resume_command(["claude", "--session-id", "xxx"], "xxx")
        assert out == ["claude", "--resume", "xxx"]
        assert "--session-id" not in out

    def test_existing_uuids_empty_for_missing_dir(self, tmp_path, monkeypatch):
        from aque.plugins.claude import existing_uuids
        monkeypatch.setattr("aque.plugins.claude.Path.home", lambda: tmp_path)
        assert existing_uuids("/nonexistent/dir") == set()
