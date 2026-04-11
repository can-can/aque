"""BDD tests for hook_installation.feature scenarios.

Scenarios wired up:
1. Known agent type is discovered as a plugin        — plugin discovery
2. Unknown agent type returns no plugin              — plugin discovery
3. First launch with type installs hook              — hook installation
4. Hook installation preserves existing settings     — hook installation
5. Hook installation is idempotent                   — hook installation
6. Launching with type sets AQUE_AGENT_ID            — launch integration (mocked)
7. Launching without type does not export env var    — launch integration (mocked)
8. Launching with unknown type falls back to polling — launch integration (mocked)
"""
import json
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, call, patch

import pytest
from pytest_bdd import scenario, given, when, then, parsers

from aque.plugins import discover_plugins, get_plugin
from aque.plugins.claude import is_installed, install_hook
from aque.state import AgentInfo, AgentState, StateManager


FEATURE = "../../features/hook_installation.feature"


# ── Scenario declarations ──────────────────────────────────────────────────────


@scenario(FEATURE, "Known agent type is discovered as a plugin")
def test_known_plugin_discovered():
    pass


@scenario(FEATURE, "Unknown agent type returns no plugin")
def test_unknown_plugin_not_found():
    pass


@scenario(FEATURE, "First launch with type installs hook with confirmation")
def test_first_launch_installs_hook():
    pass


@scenario(FEATURE, "Hook installation preserves existing settings")
def test_hook_install_preserves_existing():
    pass


@scenario(FEATURE, "Hook installation is idempotent")
def test_hook_install_idempotent():
    pass


@scenario(FEATURE, "Launching with type sets the AQUE_AGENT_ID environment variable")
def test_launch_with_type_exports_id():
    pass


@scenario(FEATURE, "Launching without type does not export environment variable")
def test_launch_without_type_no_export():
    pass


@scenario(FEATURE, "Launching with unknown type falls back to polling")
def test_launch_unknown_type_falls_back():
    pass


# ── Context fixture ────────────────────────────────────────────────────────────


@pytest.fixture
def ctx():
    """Shared dict for state across BDD steps."""
    return {}


# ── Plugin discovery steps ─────────────────────────────────────────────────────


@given(parsers.parse('the "{agent_type}" plugin is available'))
def given_plugin_available(ctx, agent_type):
    plugins = discover_plugins()
    assert agent_type in plugins, (
        f"Expected plugin '{agent_type}' to be available, found: {list(plugins)}"
    )
    ctx["plugins"] = plugins


@when(parsers.parse('I look up the plugin for type "{agent_type}"'))
def when_look_up_plugin(ctx, agent_type):
    ctx["plugin"] = get_plugin(agent_type)
    ctx["agent_type"] = agent_type


@then("the plugin should be found")
def then_plugin_found(ctx):
    assert ctx.get("plugin") is not None, (
        f"Expected plugin for '{ctx.get('agent_type')}' to be found"
    )


@then("the plugin should not be found")
def then_plugin_not_found(ctx):
    assert ctx.get("plugin") is None, (
        f"Expected plugin for '{ctx.get('agent_type')}' to be None"
    )


@then("it should have an is_installed method")
def then_plugin_has_is_installed(ctx):
    plugin = ctx["plugin"]
    assert callable(getattr(plugin, "is_installed", None)), (
        "Plugin should have a callable is_installed method"
    )


@then("it should have an install_hook method")
def then_plugin_has_install_hook(ctx):
    plugin = ctx["plugin"]
    assert callable(getattr(plugin, "install_hook", None)), (
        "Plugin should have a callable install_hook method"
    )


# ── Hook installation steps ────────────────────────────────────────────────────


@given(parsers.parse('the "{agent_type}" hook is not installed'))
def given_hook_not_installed(ctx, agent_type, tmp_path):
    config_path = tmp_path / "settings.json"
    # File doesn't exist — hook is definitely not installed
    assert not is_installed(config_path=config_path)
    ctx["config_path"] = config_path
    ctx["agent_type"] = agent_type


@given("the agent settings file has existing configuration")
def given_settings_has_existing_config(ctx, tmp_path):
    config_path = tmp_path / "settings.json"
    existing = {"model": "claude-opus-4-5", "theme": "dark"}
    config_path.write_text(json.dumps(existing))
    ctx["config_path"] = config_path
    ctx["existing_config"] = existing


@given(parsers.parse('the "{agent_type}" hook is already installed'))
def given_hook_already_installed(ctx, agent_type, tmp_path):
    config_path = tmp_path / "settings.json"
    # Install the hook once
    install_hook(config_path=config_path)
    assert is_installed(config_path=config_path)
    ctx["config_path"] = config_path
    ctx["agent_type"] = agent_type


@when(parsers.parse('I install the "{agent_type}" hook'))
def when_install_hook(ctx, agent_type):
    install_hook(config_path=ctx["config_path"])


@when(parsers.parse('I install the "{agent_type}" hook again'))
def when_install_hook_again(ctx, agent_type):
    install_hook(config_path=ctx["config_path"])


@then("the hook should be configured in the agent's settings")
def then_hook_configured(ctx):
    assert is_installed(config_path=ctx["config_path"]), (
        "Expected the aque hook to be installed in the settings file"
    )


@then("the hook command should write to the aque signals directory")
def then_hook_command_writes_to_signals(ctx):
    data = json.loads(ctx["config_path"].read_text())
    stop_hooks = data.get("hooks", {}).get("Stop", [])
    found = False
    for entry in stop_hooks:
        for hook in entry.get("hooks", []):
            if "aque/signals" in hook.get("command", ""):
                found = True
                break
    assert found, "Expected hook command referencing 'aque/signals' in settings"


@then("the existing configuration should be preserved")
def then_existing_config_preserved(ctx):
    data = json.loads(ctx["config_path"].read_text())
    existing = ctx.get("existing_config", {})
    for key, value in existing.items():
        assert data.get(key) == value, (
            f"Expected existing key '{key}' = {value!r} to be preserved, "
            f"got {data.get(key)!r}"
        )


@then("the aque hook should be added")
def then_aque_hook_added(ctx):
    assert is_installed(config_path=ctx["config_path"]), (
        "Expected the aque hook to be present alongside existing config"
    )


@then("there should still be exactly one aque hook entry")
def then_exactly_one_hook_entry(ctx):
    data = json.loads(ctx["config_path"].read_text())
    stop_hooks = data.get("hooks", {}).get("Stop", [])
    aque_entries = [
        entry for entry in stop_hooks
        if any("aque/signals" in h.get("command", "") for h in entry.get("hooks", []))
    ]
    assert len(aque_entries) == 1, (
        f"Expected exactly 1 aque hook entry, found {len(aque_entries)}"
    )


# ── Launch integration steps (mocked libtmux) ─────────────────────────────────


def _make_mock_pane(pane_pid="9999"):
    """Create a MagicMock that looks like a libtmux Pane."""
    pane = MagicMock()
    pane.pane_pid = pane_pid
    pane.capture_pane.return_value = ["$ "]
    return pane


def _make_mock_session(pane):
    """Create a MagicMock that looks like a libtmux Session."""
    session = MagicMock()
    session.active_pane = pane
    return session


def _make_mock_server(session):
    """Create a MagicMock that looks like a libtmux Server."""
    server = MagicMock()
    server.sessions.get.return_value = None
    server.new_session.return_value = session
    return server


@when(parsers.parse('an agent is launched with type "{agent_type}"'))
def when_launch_with_type(ctx, agent_type, tmp_aque_dir):
    pane = _make_mock_pane()
    session = _make_mock_session(pane)
    server = _make_mock_server(session)

    state_mgr = StateManager(tmp_aque_dir)

    with patch("aque.run.libtmux.Server", return_value=server), \
         patch("aque.run._wait_for_shell"):
        from aque.run import launch_agent
        # Only known types set the env var; nonexistent falls through
        resolved_type = agent_type if get_plugin(agent_type) is not None else None
        agent_id = launch_agent(
            command=["claude", "."],
            working_dir=str(tmp_aque_dir),
            label=None,
            state_manager=state_mgr,
            agent_type=resolved_type,
        )

    ctx["pane"] = pane
    ctx["agent_id"] = agent_id
    ctx["agent_type"] = agent_type
    ctx["resolved_type"] = resolved_type
    ctx["state_mgr"] = state_mgr


@when("an agent is launched without a type")
def when_launch_without_type(ctx, tmp_aque_dir):
    pane = _make_mock_pane()
    session = _make_mock_session(pane)
    server = _make_mock_server(session)

    state_mgr = StateManager(tmp_aque_dir)

    with patch("aque.run.libtmux.Server", return_value=server), \
         patch("aque.run._wait_for_shell"):
        from aque.run import launch_agent
        agent_id = launch_agent(
            command=["claude", "."],
            working_dir=str(tmp_aque_dir),
            label=None,
            state_manager=state_mgr,
            agent_type=None,
        )

    ctx["pane"] = pane
    ctx["agent_id"] = agent_id
    ctx["agent_type"] = None
    ctx["resolved_type"] = None
    ctx["state_mgr"] = state_mgr


@when(parsers.parse('an agent is launched with type "nonexistent"'))
def when_launch_with_nonexistent_type(ctx, tmp_aque_dir):
    # nonexistent has no plugin, so we fall back to no type
    when_launch_without_type(ctx, tmp_aque_dir)
    ctx["agent_type"] = "nonexistent"


@then("the tmux session should have AQUE_AGENT_ID exported")
def then_aque_agent_id_exported(ctx):
    pane = ctx["pane"]
    agent_id = ctx["agent_id"]
    expected_export = f"export AQUE_AGENT_ID={agent_id}"
    calls = [str(c) for c in pane.send_keys.call_args_list]
    assert any(expected_export in c for c in calls), (
        f"Expected pane.send_keys to be called with '{expected_export}'. "
        f"Actual calls: {calls}"
    )


@then(parsers.parse('the agent should be registered with type "{agent_type}"'))
def then_agent_registered_with_type(ctx, agent_type):
    state_mgr = ctx["state_mgr"]
    state = state_mgr.load()
    assert len(state.agents) >= 1
    agent = state.agents[0]
    assert agent.agent_type == agent_type, (
        f"Expected agent_type='{agent_type}', got '{agent.agent_type}'"
    )


@then("no AQUE_AGENT_ID should be exported")
def then_no_aque_agent_id_exported(ctx):
    pane = ctx["pane"]
    calls = [str(c) for c in pane.send_keys.call_args_list]
    assert not any("AQUE_AGENT_ID" in c for c in calls), (
        f"Expected no AQUE_AGENT_ID export. Actual calls: {calls}"
    )


@then("the agent should be registered with no type")
def then_agent_registered_no_type(ctx):
    state_mgr = ctx["state_mgr"]
    state = state_mgr.load()
    assert len(state.agents) >= 1
    agent = state.agents[0]
    assert agent.agent_type is None, (
        f"Expected agent_type=None, got '{agent.agent_type}'"
    )
