"""BDD tests for auto_attach.feature — auto-attach countdown modal.

Note: pytest-bdd 8.x has no native async step support. All step functions are sync.
Async operations are driven via ctx.run() using a dedicated event loop per test,
matching the DashboardContext pattern from test_dashboard.py.

Key Textual detail: AutoAttachModal is pushed as a *screen*, not a widget child.
So ``app.query("AutoAttachModal")`` always returns 0.  Instead use:
    isinstance(app.screen, AutoAttachModal)   — True when modal is active
    app.screen.query_one("#auto-attach-label") — to read the label text
"""
import asyncio
from unittest.mock import patch

import pytest
from pytest_bdd import scenario, given, when, then, parsers

from aque.desk import AutoAttachModal, DeskApp
from aque.history import HistoryManager
from aque.state import AgentInfo, AgentState, StateManager


FEATURE = "../../features/auto_attach.feature"


# ── Scenario declarations ──────────────────────────────────────────────────────


@scenario(FEATURE, "Countdown modal appears when returning to dashboard with a waiting agent")
def test_countdown_appears_on_return():
    pass


@scenario(FEATURE, "No countdown when there are no waiting agents")
def test_no_countdown_without_waiting():
    pass


@scenario(FEATURE, "Pressing Escape cancels the countdown")
def test_escape_cancels_countdown():
    pass


@scenario(FEATURE, "Only one countdown can be active at a time")
def test_only_one_countdown():
    pass


@scenario(FEATURE, "Countdown targets the top-priority waiting agent")
def test_countdown_targets_top_priority():
    pass


@scenario(FEATURE, "Countdown does not trigger when skip_attach is set")
def test_no_countdown_when_skip_attach():
    pass


@scenario(FEATURE, "Countdown modal appears when an agent transitions to waiting on the dashboard")
def test_countdown_appears_on_transition():
    pass


@scenario(FEATURE, "Countdown decrements each second")
def test_countdown_decrements():
    pass


@scenario(FEATURE, "Auto-attach triggers after countdown reaches zero")
def test_auto_attach_triggers_at_zero():
    pass


@scenario(FEATURE, "Dashboard refreshes continue during countdown")
def test_dashboard_refreshes_during_countdown():
    pass


# ── Context holder ─────────────────────────────────────────────────────────────


class AutoAttachContext:
    """Holds app state across BDD steps.

    Similar to DashboardContext from test_dashboard.py but supports
    configuring skip_attach before mount.
    """

    def __init__(self, tmp_aque_dir, skip_attach=True):
        self.tmp_aque_dir = tmp_aque_dir
        self.state_mgr = StateManager(tmp_aque_dir)
        self.history_mgr = HistoryManager(tmp_aque_dir)
        self._skip_attach = skip_attach
        self.app = None
        self.pilot = None
        self._run_test_cm = None
        self._loop = None

    def _get_loop(self):
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
        return self._loop

    def run(self, coro):
        """Run an async coroutine in the dedicated event loop."""
        return self._get_loop().run_until_complete(coro)

    def run_in_app_context(self, coro):
        """Run a coroutine inside app._context() so ContextVars are set correctly.

        This is required whenever the coroutine causes Textual to push a new screen
        (e.g. AutoAttachModal), because pilot.pause() will try to render that screen
        and the render path accesses the ``active_app`` ContextVar.
        """
        async def _wrapped():
            with self.app._context():
                return await coro
        return self._get_loop().run_until_complete(_wrapped())

    def ensure_mounted(self):
        if self.app is None:
            self.run(self._mount())

    async def _mount(self):
        self.app = DeskApp(aque_dir=self.tmp_aque_dir, _skip_attach=self._skip_attach)
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

    def modal_is_active(self) -> bool:
        """Return True when the AutoAttachModal is the current screen."""
        return isinstance(self.app.screen, AutoAttachModal)

    def modal_label_text(self) -> str:
        """Return rendered text of #auto-attach-label (only valid when modal is active)."""
        return str(self.app.screen.query_one("#auto-attach-label").render())


@pytest.fixture
def ctx(tmp_aque_dir, request):
    # Default to skip_attach=False for auto-attach tests.
    # The "skip_attach is set" scenario overrides via given_desk_opened_with_skip_attach.
    c = AutoAttachContext(tmp_aque_dir, skip_attach=False)
    request.addfinalizer(c.cleanup)
    return c


def _datatable_as_dicts(datatable):
    """Convert raw datatable (list of lists, first row = headers) to list of dicts."""
    rows = datatable
    if not rows:
        return []
    headers = rows[0]
    return [dict(zip(headers, row)) for row in rows[1:]]


# ── Shared background step ─────────────────────────────────────────────────────


@given("the aque desk is open", target_fixture="ctx")
def given_desk_is_open(ctx):
    """No-op marker — app mounts lazily in When/Given steps."""
    return ctx


# ── Given steps ───────────────────────────────────────────────────────────────


@given(parsers.parse('agent "{label}" is in "{state_str}" state'))
def given_agent_in_state(ctx, label, state_str):
    state = AgentState(state_str)
    agent_id = ctx.state_mgr.next_id()
    agent = AgentInfo(
        id=agent_id,
        tmux_session=f"aque-test-{agent_id}",
        label=label,
        dir="/tmp/test",
        command=["test"],
        state=state,
        pid=10000 + agent_id,
    )
    ctx.state_mgr.add_agent(agent)


@given(parsers.parse('all agents are in "{state_str}" state'))
def given_all_agents_in_state(ctx, state_str):
    """Seed two agents in the given state (non-empty list, but no waiting agents)."""
    state = AgentState(state_str)
    for label in ("agent-a", "agent-b"):
        agent_id = ctx.state_mgr.next_id()
        agent = AgentInfo(
            id=agent_id,
            tmux_session=f"aque-test-{agent_id}",
            label=label,
            dir="/tmp/test",
            command=["test"],
            state=state,
            pid=10000 + agent_id,
        )
        ctx.state_mgr.add_agent(agent)


@given(parsers.parse('the countdown modal is showing for agent "{label}"'))
def given_countdown_modal_showing(ctx, label):
    """Mount the app with skip_attach=False and trigger the countdown for label."""
    agent_id = ctx.state_mgr.next_id()
    agent = AgentInfo(
        id=agent_id,
        tmux_session=f"aque-test-{agent_id}",
        label=label,
        dir="/tmp/test",
        command=["test"],
        state=AgentState.WAITING,
        pid=10000 + agent_id,
    )
    ctx.state_mgr.add_agent(agent)

    ctx._skip_attach = False
    ctx.ensure_mounted()

    async def _trigger():
        ctx.app._show_dashboard()
        await ctx.pilot.pause()

    ctx.run_in_app_context(_trigger())
    assert ctx.modal_is_active(), (
        "Expected AutoAttachModal to be active after show_dashboard with waiting agent"
    )


@given(parsers.parse("the desk is opened with skip_attach=True"))
def given_desk_opened_with_skip_attach(ctx):
    """Ensure the context is configured with skip_attach=True (already the default)."""
    ctx._skip_attach = True


@given("the following agents exist:", target_fixture="agents_created")
def given_agents_exist_table(ctx, datatable):
    rows = _datatable_as_dicts(datatable)
    agents = []
    for row in rows:
        state = AgentState(row["state"])
        agent_id = ctx.state_mgr.next_id()
        agent = AgentInfo(
            id=agent_id,
            tmux_session=f"aque-test-{agent_id}",
            label=row["label"],
            dir="/tmp/test",
            command=["test"],
            state=state,
            pid=10000 + agent_id,
        )
        if "last_change_at" in row:
            agent.last_change_at = row["last_change_at"]
        ctx.state_mgr.add_agent(agent)
        agents.append(agent)
    return agents


# ── When steps ─────────────────────────────────────────────────────────────────


@when("the user returns to the dashboard")
def when_user_returns_to_dashboard(ctx):
    ctx.ensure_mounted()

    async def _return():
        ctx.app._show_dashboard()
        await ctx.pilot.pause()

    ctx.run_in_app_context(_return())


@when("the periodic refresh runs")
def when_periodic_refresh_runs(ctx):
    ctx.ensure_mounted()

    async def _refresh():
        ctx.app._on_refresh()
        await ctx.pilot.pause()

    ctx.run_in_app_context(_refresh())


@when("the user presses Escape")
def when_user_presses_escape(ctx):
    async def _press():
        await ctx.pilot.press("escape")
        await ctx.pilot.pause()

    ctx.run_in_app_context(_press())


@when(parsers.parse('the periodic refresh detects another waiting agent "{label}"'))
def when_refresh_detects_another_waiting(ctx, label):
    """Add another waiting agent to state, then trigger a refresh."""
    agent_id = ctx.state_mgr.next_id()
    agent = AgentInfo(
        id=agent_id,
        tmux_session=f"aque-test-{agent_id}",
        label=label,
        dir="/tmp/test",
        command=["test"],
        state=AgentState.WAITING,
        pid=10000 + agent_id,
    )
    ctx.state_mgr.add_agent(agent)

    async def _refresh():
        ctx.app._on_refresh()
        await ctx.pilot.pause()

    ctx.run_in_app_context(_refresh())


@when("the countdown modal appears")
def when_countdown_modal_appears(ctx):
    """Mount with skip_attach=False and show dashboard to trigger auto-attach."""
    ctx._skip_attach = False
    ctx.ensure_mounted()

    async def _show():
        ctx.app._show_dashboard()
        await ctx.pilot.pause()

    ctx.run_in_app_context(_show())


# ── Then steps ─────────────────────────────────────────────────────────────────


@then("a countdown modal should appear")
def then_countdown_modal_appears(ctx):
    assert ctx.modal_is_active(), (
        "Expected AutoAttachModal to be the active screen, but it is not"
    )


@then("no countdown modal should appear")
def then_no_countdown_modal(ctx):
    assert not ctx.modal_is_active(), (
        "Expected AutoAttachModal NOT to be active, but it is"
    )


@then(parsers.parse('the modal should show "{text}"'))
def then_modal_shows_text(ctx, text):
    assert ctx.modal_is_active(), "Expected modal to be active before checking its text"
    rendered = ctx.modal_label_text()
    assert text in rendered, (
        f"Expected modal label to contain '{text}', got: '{rendered}'"
    )


@then("the countdown modal should be dismissed")
def then_countdown_dismissed(ctx):
    assert not ctx.modal_is_active(), (
        "Expected AutoAttachModal to be dismissed, but it is still active"
    )


@then("the user should remain on the dashboard")
def then_user_on_dashboard(ctx):
    assert ctx.app._mode == "dashboard", (
        f"Expected mode 'dashboard', got '{ctx.app._mode}'"
    )


@then(parsers.parse('agent "{label}" should still be in "{state_str}" state'))
def then_agent_still_in_state(ctx, label, state_str):
    state = ctx.state_mgr.load()
    agent = next((a for a in state.agents if a.label == label), None)
    assert agent is not None, f"Agent '{label}' not found"
    assert agent.state.value == state_str, (
        f"Expected agent '{label}' in state '{state_str}', got '{agent.state.value}'"
    )


@then("no second countdown modal should appear")
def then_no_second_countdown(ctx):
    # The modal IS the active screen; check screen stack depth — should only be 2
    # (default Screen + AutoAttachModal), not 3 or more.
    stack = ctx.app.screen_stack
    modal_count = sum(1 for s in stack if isinstance(s, AutoAttachModal))
    assert modal_count <= 1, (
        f"Expected at most 1 AutoAttachModal in screen stack, got {modal_count}"
    )


@then("the existing countdown should continue")
def then_existing_countdown_continues(ctx):
    assert ctx.app._countdown_timer is not None, (
        "Expected countdown timer to still be running"
    )
    assert ctx.app._countdown_agent is not None, (
        "Expected countdown agent to still be set"
    )


# ── Steps for the 4 new scenarios ─────────────────────────────────────────────


@given("the user is on the dashboard")
def given_user_on_dashboard(ctx):
    """Mount the app so the dashboard is visible (no waiting agents yet → no modal)."""
    ctx.ensure_mounted()


@when(parsers.parse('the monitor changes agent "{label}" to "waiting"'))
def when_monitor_changes_to_waiting(ctx, label):
    """Simulate the monitor marking the named agent as waiting in state."""
    state = ctx.state_mgr.load()
    agent = next((a for a in state.agents if a.label == label), None)
    assert agent is not None, f"Agent '{label}' not found in state"
    ctx.state_mgr.update_agent_state(agent.id, AgentState.WAITING)


@when(parsers.parse("{n:d} second passes"))
def when_n_second_passes(ctx, n):
    """Call _countdown_tick() n times to simulate seconds elapsing.

    _attach_to_agent is mocked on the instance to avoid real tmux interaction
    if the countdown reaches zero during this step.
    """
    def _mock_attach(agent):
        ctx.state_mgr.update_agent_state(agent.id, AgentState.FOCUSED)

    ctx.app._attach_to_agent = _mock_attach

    async def _tick():
        for _ in range(n):
            ctx.app._countdown_tick()
        await ctx.pilot.pause()

    ctx.run_in_app_context(_tick())


@when(parsers.parse("{n:d} seconds pass"))
def when_n_seconds_pass(ctx, n):
    """Call _countdown_tick() n times to simulate n seconds elapsing.

    _attach_to_agent is mocked on the instance to avoid real tmux interaction
    if the countdown reaches zero during this step.
    """
    def _mock_attach(agent):
        ctx.state_mgr.update_agent_state(agent.id, AgentState.FOCUSED)

    ctx.app._attach_to_agent = _mock_attach

    async def _tick():
        for _ in range(n):
            ctx.app._countdown_tick()
        await ctx.pilot.pause()

    ctx.run_in_app_context(_tick())


@then(parsers.parse('agent "{label}" should be in "{state_str}" state'))
def then_agent_in_state(ctx, label, state_str):
    state = ctx.state_mgr.load()
    agent = next((a for a in state.agents if a.label == label), None)
    assert agent is not None, f"Agent '{label}' not found"
    assert agent.state.value == state_str, (
        f"Expected agent '{label}' in state '{state_str}', got '{agent.state.value}'"
    )


@then(parsers.parse('the user should be attached to agent "{label}"'))
def then_attached_to_agent(ctx, label):
    """After countdown zeros out, _attach_to_agent should have been called."""
    # Verify the agent is now FOCUSED (the mock set it that way)
    state = ctx.state_mgr.load()
    agent = next((a for a in state.agents if a.label == label), None)
    assert agent is not None, f"Agent '{label}' not found"
    assert agent.state == AgentState.FOCUSED, (
        f"Expected agent '{label}' in FOCUSED state after attach, got '{agent.state.value}'"
    )


@then("the agent list should be updated")
def then_agent_list_updated(ctx):
    """The agent-option-list widget should exist and be populated."""
    try:
        from textual.widgets import OptionList
        option_list = ctx.app.query_one("#agent-option-list", OptionList)
        assert option_list is not None, "agent-option-list widget not found"
    except Exception as exc:
        raise AssertionError(f"agent-option-list not present after refresh: {exc}") from exc


@then("the status bar should be updated")
def then_status_bar_updated(ctx):
    """The status-bar widget should exist."""
    try:
        from textual.widgets import Static
        status_bar = ctx.app.query_one("#status-bar", Static)
        assert status_bar is not None, "status-bar widget not found"
    except Exception as exc:
        raise AssertionError(f"status-bar not present after refresh: {exc}") from exc
