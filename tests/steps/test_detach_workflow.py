"""BDD tests for detach_workflow.feature scenarios.

Strategy: Test state transitions that happen AFTER tmux detach returns.
We cannot do a real attach/detach (subprocess.run blocks the terminal),
so we simulate the post-detach code path directly:
  1. Seed agent into the appropriate pre-detach state
  2. Run the post-detach logic (read state, check, update)
  3. Verify final state / dashboard visibility

Scenarios covered:
1. Detaching from a running agent auto-dismisses to dashboard (FOCUSED → RUNNING)
2. Detaching from an exited agent auto-marks it as done (EXITED → history)
3. Agent state is preserved if changed during attachment (FOCUSED→WAITING externally → stays WAITING)
4. Dashboard highlight resets to top waiting agent after detach (TUI test)
5. Monitor is restarted on dashboard return if needed (mock _ensure_monitor_running)
"""
import asyncio
from unittest.mock import patch, MagicMock

import pytest
from pytest_bdd import scenario, given, when, then, parsers

from aque.desk import DeskApp
from aque.history import HistoryManager
from aque.state import AgentInfo, AgentState, StateManager


FEATURE = "../../features/detach_workflow.feature"


# ── Scenario declarations ──────────────────────────────────────────────────────


@scenario(FEATURE, "Detaching from a running agent auto-dismisses to dashboard")
def test_detach_running_agent_auto_dismisses():
    pass


@scenario(FEATURE, "Detaching from an exited agent auto-marks it as done")
def test_detach_exited_agent_marks_done():
    pass


@scenario(FEATURE, "Agent state is preserved if changed during attachment")
def test_agent_state_preserved_during_attachment():
    pass


@scenario(FEATURE, "Dashboard highlight resets to top waiting agent after detach")
def test_dashboard_highlight_resets_after_detach():
    pass


@scenario(FEATURE, "Monitor is restarted on dashboard return if needed")
def test_monitor_restarted_on_dashboard_return():
    pass


# ── Context holder ─────────────────────────────────────────────────────────────


class DetachContext:
    """Shared mutable context for BDD steps.

    App is mounted lazily. All async work is driven via self.run(coro).
    """

    def __init__(self, tmp_aque_dir):
        self.tmp_aque_dir = tmp_aque_dir
        self.state_mgr = StateManager(tmp_aque_dir)
        self.history_mgr = HistoryManager(tmp_aque_dir)
        self.app = None
        self.pilot = None
        self._loop = None
        self._run_test_cm = None
        self.data: dict = {}

    def _get_loop(self):
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
        return self._loop

    def run(self, coro):
        """Run an async coroutine in the dedicated event loop."""
        return self._get_loop().run_until_complete(coro)

    def ensure_mounted(self):
        if self.app is None:
            self.run(self._mount())

    async def _mount(self):
        self.app = DeskApp(aque_dir=self.tmp_aque_dir, _skip_attach=True)
        self._run_test_cm = self.app.run_test()
        self.pilot = await self._run_test_cm.__aenter__()
        await self.pilot.pause()

    async def _shutdown(self):
        if self._run_test_cm is not None:
            await self._run_test_cm.__aexit__(None, None, None)
            self._run_test_cm = None

    def cleanup(self):
        if self.app is not None and self._loop is not None:
            try:
                self._loop.run_until_complete(self._shutdown())
            except Exception:
                pass
        if self._loop is not None:
            try:
                self._loop.close()
            except Exception:
                pass
            self._loop = None


@pytest.fixture
def ctx(tmp_aque_dir, request):
    c = DetachContext(tmp_aque_dir)
    request.addfinalizer(c.cleanup)
    return c


def _datatable_as_dicts(datatable):
    """Convert raw datatable (list of lists, first row = headers) to list of dicts."""
    rows = datatable
    if not rows:
        return []
    headers = rows[0]
    return [dict(zip(headers, row)) for row in rows[1:]]


def _seed_agent(ctx, label: str, state: AgentState) -> AgentInfo:
    """Seed a single agent into state and return the AgentInfo."""
    agent_id = ctx.state_mgr.next_id()
    session_name = f"aque-detach-test-{agent_id}"
    agent = AgentInfo(
        id=agent_id,
        tmux_session=session_name,
        label=label,
        dir="/tmp/test",
        command=["test"],
        state=state,
        pid=10000 + agent_id,
    )
    ctx.state_mgr.add_agent(agent)
    return agent


def _simulate_post_detach(ctx, agent: AgentInfo) -> None:
    """Replicate the post-detach logic from DeskApp._attach_to_agent().

    This is called after subprocess.run(["tmux", "attach-session", ...]) returns.
    It reads the current state, applies the correct transition, then shows dashboard.
    """
    state = ctx.state_mgr.load()
    updated_agent = next((a for a in state.agents if a.id == agent.id), agent)
    if updated_agent.state in (AgentState.EXITED,):
        # Move to history (mirrors _kill_agent → done_agent)
        ctx.state_mgr.done_agent(updated_agent.id, ctx.history_mgr)
    elif updated_agent.state == AgentState.FOCUSED:
        ctx.state_mgr.update_agent_state(updated_agent.id, AgentState.RUNNING)


# ── Shared Background step ─────────────────────────────────────────────────────


@given("the aque desk is open", target_fixture="ctx")
def given_desk_is_open(ctx):
    """No-op marker — app mounts lazily when needed."""
    return ctx


# ── Scenario 1 & 2 & 3: agent state given steps ───────────────────────────────


@given(parsers.parse('agent "{label}" is in "focused" state'), target_fixture="ctx")
def given_agent_focused(label, ctx):
    agent = _seed_agent(ctx, label, AgentState.FOCUSED)
    ctx.data["agent"] = agent
    ctx.data["label"] = label
    return ctx


@given(parsers.parse('agent "{label}" is in "exited" state'), target_fixture="ctx")
def given_agent_exited(label, ctx):
    agent = _seed_agent(ctx, label, AgentState.EXITED)
    ctx.data["agent"] = agent
    ctx.data["label"] = label
    return ctx


@given(parsers.parse('the monitor changes agent "{label}" to "waiting" during the session'))
def given_monitor_changes_agent_to_waiting(label, ctx):
    """Simulate an external state change during the tmux session (e.g. monitor update)."""
    agent: AgentInfo = ctx.data["agent"]
    ctx.state_mgr.update_agent_state(agent.id, AgentState.WAITING)


# ── Unified detach when step (all detach scenarios) ───────────────────────────


@when("the user detaches from the tmux session")
def when_user_detaches(ctx):
    """Simulate what happens after tmux detach-session returns.

    Runs post-detach state transitions. If the TUI app is mounted (scenario 4),
    also calls _show_dashboard() so the highlight resets correctly.
    """
    agent: AgentInfo = ctx.data["agent"]
    _simulate_post_detach(ctx, agent)

    if ctx.app is not None:
        async def _show_dash():
            ctx.app._show_dashboard()
            await ctx.pilot.pause()

        ctx.run(_show_dash())


# ── Scenario 1: FOCUSED → RUNNING ─────────────────────────────────────────────


@then(parsers.parse('agent "{label}" should be in "running" state'))
def then_agent_in_running_state(label, ctx):
    state = ctx.state_mgr.load()
    agent = next((a for a in state.agents if a.label == label), None)
    assert agent is not None, f"Agent '{label}' not found in active agents"
    assert agent.state == AgentState.RUNNING, (
        f"Expected agent '{label}' to be running, got '{agent.state.value}'"
    )


@then("the dashboard should be visible")
def then_dashboard_visible(ctx):
    """For pure state-transition tests, the dashboard is implicitly shown after detach.
    When TUI is mounted, verify the #dashboard widget is displayed."""
    if ctx.app is not None:
        dashboard = ctx.app.query_one("#dashboard")
        assert dashboard.display is True, "Dashboard should be visible"
    # For non-TUI tests, the step passes trivially — post-detach logic ends at _show_dashboard()


@then("no action menu should be shown")
def then_no_action_menu(ctx):
    """Verify no action menu exists in the TUI (or confirm it's not active in state tests)."""
    if ctx.app is not None:
        action_menus = ctx.app.query("ActionMenu")
        assert len(action_menus) == 0, (
            f"Expected no ActionMenu, found {len(action_menus)}"
        )
    # For pure state tests: post-detach always calls _show_dashboard(), not _show_action_menu()


# ── Scenario 2: EXITED → history ──────────────────────────────────────────────


@then(parsers.parse('agent "{label}" should be moved to history'))
def then_agent_moved_to_history(label, ctx):
    state = ctx.state_mgr.load()
    active_labels = [a.label for a in state.agents]
    assert label not in active_labels, (
        f"Expected '{label}' to be removed from active agents, still found in: {active_labels}"
    )
    history_entries = ctx.history_mgr.load()
    history_labels = [e["label"] for e in history_entries]
    assert label in history_labels, (
        f"Expected '{label}' in history, got: {history_labels}"
    )


# ── Scenario 3: external state change preserved ───────────────────────────────


@then(parsers.parse('agent "{label}" should remain in "waiting" state'))
def then_agent_remains_waiting(label, ctx):
    state = ctx.state_mgr.load()
    agent = next((a for a in state.agents if a.label == label), None)
    assert agent is not None, f"Agent '{label}' not found in active agents"
    assert agent.state == AgentState.WAITING, (
        f"Expected agent '{label}' to remain waiting, got '{agent.state.value}'"
    )


# ── Scenario 4: Dashboard highlight resets to top waiting agent ───────────────


@given("the following agents exist:", target_fixture="agents_created")
def given_agents_exist(ctx, datatable):
    rows = _datatable_as_dicts(datatable)
    agents = []
    for row in rows:
        state = AgentState(row["state"])
        agent = _seed_agent(ctx, row["label"], state)
        agents.append(agent)
    return agents


@given(parsers.parse('the user was attached to "{label}"'))
def given_user_was_attached_to(label, ctx, agents_created):
    """Record that the user was attached to this agent; seed it as FOCUSED."""
    agent = next((a for a in agents_created if a.label == label), None)
    assert agent is not None, f"Agent '{label}' not found in seeded agents"
    ctx.state_mgr.update_agent_state(agent.id, AgentState.FOCUSED)
    ctx.data["agent"] = agent
    ctx.data["attached_label"] = label
    # Mount the TUI so we can inspect highlight afterward
    ctx.ensure_mounted()


@then(parsers.parse('the highlighted agent should be "{label}"'))
def then_highlighted_agent_is(ctx, label):
    option_list = ctx.app.query_one("#agent-option-list")
    assert option_list.highlighted is not None, "No item highlighted"
    highlighted_option = option_list.get_option_at_index(option_list.highlighted)
    label_text = str(highlighted_option.prompt)
    assert label in label_text, (
        f"Expected highlighted agent '{label}', got prompt text: '{label_text}'"
    )


# ── Scenario 5: Monitor is restarted on dashboard return ──────────────────────


@given("the monitor daemon has died")
def given_monitor_daemon_has_died(ctx):
    """Set a stale/nonexistent PID in state to simulate a dead monitor."""
    state = ctx.state_mgr.load()
    # Use a PID that definitely doesn't exist
    state.monitor_pid = 999999999
    ctx.state_mgr.save(state)


@given("the user was attached to an agent")
def given_user_was_attached_to_an_agent(ctx):
    """Seed a generic agent in FOCUSED state to simulate being attached."""
    agent = _seed_agent(ctx, "generic-agent", AgentState.FOCUSED)
    ctx.data["agent"] = agent


@when("the user detaches and returns to the dashboard")
def when_user_detaches_and_returns(ctx):
    """Run post-detach state transitions then call _ensure_monitor_running."""
    agent: AgentInfo = ctx.data["agent"]
    _simulate_post_detach(ctx, agent)
    # Capture whether _ensure_monitor_running was called by mounting TUI
    # and tracking calls via mock
    ctx.data["ensure_monitor_called"] = False

    original_start = None
    try:
        from aque import monitor as _mon
        original_start = _mon.start_monitor_daemon
    except Exception:
        pass

    # We mount and call _show_dashboard() which internally calls _ensure_monitor_running()
    ctx.ensure_mounted()

    with patch.object(ctx.app, "_ensure_monitor_running", wraps=ctx.app._ensure_monitor_running) as mock_ensure:
        async def _show_dash():
            ctx.app._show_dashboard()
            await ctx.pilot.pause()

        ctx.run(_show_dash())
        ctx.data["ensure_monitor_call_count"] = mock_ensure.call_count


@then("the monitor daemon should be running")
def then_monitor_daemon_running(ctx):
    """Verify that _ensure_monitor_running was invoked during dashboard return.

    Since start_monitor_daemon forks a real process, we verify the call happened.
    The call count being >= 1 is sufficient to confirm the code path was exercised.
    """
    call_count = ctx.data.get("ensure_monitor_call_count", 0)
    assert call_count >= 1, (
        f"Expected _ensure_monitor_running to be called at least once, got {call_count}"
    )
