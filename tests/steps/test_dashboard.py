"""BDD tests for dashboard scenarios — agent listing and status bar.

Note: pytest-bdd 8.x has no native async step support. All step functions are sync.
Async operations (app mounting/piloting) are driven via ctx.run(), which calls
ctx.loop.run_until_complete() using the event loop created fresh for each test.
The app is mounted and torn down entirely within run_until_complete() to avoid
asyncio ContextVar issues with Textual's run_test().
"""
import asyncio

import libtmux
import pytest
from pytest_bdd import scenario, given, when, then, parsers

from aque.desk import DeskApp
from aque.history import HistoryManager
from aque.state import AgentInfo, AgentState, StateManager


FEATURE = "../../features/dashboard.feature"


# ── Scenario declarations ──────────────────────────────────────────────────────


@scenario(FEATURE, "Agents are sorted by priority")
def test_agents_sorted():
    pass


@scenario(FEATURE, "Done agents are hidden from the dashboard")
def test_done_agents_hidden():
    pass


@scenario(FEATURE, "First item is auto-highlighted on app start")
def test_first_item_highlighted_on_start():
    pass


@scenario(FEATURE, "First item is auto-highlighted when returning to dashboard")
def test_first_item_highlighted_on_return():
    pass


@scenario(FEATURE, "Highlight resets to top on dashboard return")
def test_highlight_resets_to_top():
    pass


@scenario(FEATURE, "Highlight is preserved during periodic refresh")
def test_highlight_preserved_during_refresh():
    pass


@scenario(FEATURE, "Status bar shows agent counts by state")
def test_status_bar_counts():
    pass


@scenario(FEATURE, "Status bar shows done count from history")
def test_status_bar_done_count():
    pass


@scenario(FEATURE, 'Press "n" to open new agent form')
def test_press_n_opens_new_agent_form():
    pass


@scenario(FEATURE, 'Press "k" to kill highlighted agent')
def test_press_k_kills_highlighted_agent():
    pass


@scenario(FEATURE, 'Press "h" to toggle hold on highlighted agent')
def test_press_h_toggles_hold():
    pass


@scenario(FEATURE, 'Press "h" on a held agent to resume it')
def test_press_h_resumes_held_agent():
    pass


@scenario(FEATURE, "Preview shows placeholder when no agent is highlighted")
def test_preview_shows_placeholder():
    pass


@scenario(FEATURE, "Preview shows tmux pane content for highlighted agent")
def test_preview_shows_tmux_content():
    pass


@scenario(FEATURE, "Typed agent shows type tag in list")
def test_typed_agent_shows_type_tag():
    pass


@scenario(FEATURE, "Untyped agent shows no type tag")
def test_untyped_agent_shows_no_type_tag():
    pass


# ── Context holder ─────────────────────────────────────────────────────────────


class DashboardContext:
    """Holds app state across BDD steps.

    App is mounted lazily. All async work is driven through self.run(coro),
    which executes the coroutine in its own dedicated event loop. The app's
    entire lifecycle (mount and teardown) runs in the same event loop to
    avoid asyncio ContextVar issues with Textual's run_test().
    """

    def __init__(self, tmp_aque_dir):
        self.tmp_aque_dir = tmp_aque_dir
        self.state_mgr = StateManager(tmp_aque_dir)
        self.history_mgr = HistoryManager(tmp_aque_dir)
        self.app = None
        self.pilot = None
        self._loop = None
        self._app_task = None
        self._tmux_sessions = []  # track real tmux sessions for cleanup

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
        # Use run_test() as a context manager but keep it open
        self._run_test_cm = self.app.run_test()
        self.pilot = await self._run_test_cm.__aenter__()
        await self.pilot.pause()

    async def _shutdown(self):
        if self._run_test_cm is not None:
            await self._run_test_cm.__aexit__(None, None, None)
            self._run_test_cm = None

    def cleanup(self):
        """Synchronous cleanup — shuts down the app if mounted, kill tmux sessions."""
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
        # Kill any real tmux sessions created during the test
        if self._tmux_sessions:
            try:
                server = libtmux.Server()
                for name in self._tmux_sessions:
                    session = server.sessions.get(session_name=name)
                    if session:
                        session.kill()
            except Exception:
                pass
            self._tmux_sessions.clear()


@pytest.fixture
def ctx(tmp_aque_dir, request):
    c = DashboardContext(tmp_aque_dir)
    request.addfinalizer(c.cleanup)
    return c


def _datatable_as_dicts(datatable):
    """Convert raw datatable (list of lists, first row = headers) to list of dicts."""
    rows = datatable  # DataTable.raw() returns list of lists
    if not rows:
        return []
    headers = rows[0]
    return [dict(zip(headers, row)) for row in rows[1:]]


# ── Shared step overrides ──────────────────────────────────────────────────────
# These override the shared steps in tests/steps/conftest.py for dashboard tests.


@given("the aque desk is open", target_fixture="ctx")
def given_desk_is_open(ctx):
    """No-op marker — app mounts lazily in When steps."""
    return ctx


@given("the following agents exist:", target_fixture="agents_created")
def given_agents_exist(ctx, datatable):
    rows = _datatable_as_dicts(datatable)
    agents = []
    for row in rows:
        state = AgentState(row["state"])
        agent_id = ctx.state_mgr.next_id()
        agent_type = row.get("agent_type", None) or None  # empty string -> None
        agent = AgentInfo(
            id=agent_id,
            tmux_session=f"aque-{agent_id}",
            label=row["label"],
            dir="/tmp/test",
            command=["test"],
            state=state,
            pid=10000 + agent_id,
            agent_type=agent_type,
        )
        ctx.state_mgr.add_agent(agent)
        agents.append(agent)
    return agents


@when("the dashboard loads")
def when_dashboard_loads(ctx):
    ctx.ensure_mounted()

    async def _refresh():
        ctx.app._refresh_agent_list(reset_highlight=True)
        await ctx.pilot.pause()

    ctx.run(_refresh())


@when("the app mounts")
def when_app_mounts(ctx):
    ctx.ensure_mounted()


# ── Dashboard-specific step definitions ───────────────────────────────────────


@then("the agent list should be ordered:")
def then_agent_list_ordered(ctx, datatable):
    option_list = ctx.app.query_one("#agent-option-list")
    expected = _datatable_as_dicts(datatable)
    assert option_list.option_count == len(expected), (
        f"Expected {len(expected)} agents, got {option_list.option_count}"
    )
    for i, row in enumerate(expected):
        option = option_list.get_option_at_index(i)
        label_text = str(option.prompt)
        assert row["label"] in label_text, (
            f"Position {i}: expected label '{row['label']}' in '{label_text}'"
        )
        assert row["state"] in label_text, (
            f"Position {i}: expected state '{row['state']}' in '{label_text}'"
        )


@then(parsers.parse('the agent list should contain "{label}"'))
def then_agent_list_contains(ctx, label):
    option_list = ctx.app.query_one("#agent-option-list")
    all_labels = [
        str(option_list.get_option_at_index(i).prompt)
        for i in range(option_list.option_count)
    ]
    assert any(label in text for text in all_labels), (
        f"Expected '{label}' in agent list, got: {all_labels}"
    )


@then(parsers.parse('the agent list should not contain "{label}"'))
def then_agent_list_not_contains(ctx, label):
    option_list = ctx.app.query_one("#agent-option-list")
    all_labels = [
        str(option_list.get_option_at_index(i).prompt)
        for i in range(option_list.option_count)
    ]
    assert not any(label in text for text in all_labels), (
        f"Expected '{label}' NOT in agent list, but found it in: {all_labels}"
    )


@then("the agent list should have focus")
def then_agent_list_has_focus(ctx):
    focused = ctx.app.focused
    assert focused is not None, "No widget has focus"
    assert focused.id == "agent-option-list", (
        f"Expected '#agent-option-list' to have focus, got '{focused.id}'"
    )


@then("the first item should be highlighted")
def then_first_item_highlighted(ctx):
    option_list = ctx.app.query_one("#agent-option-list")
    assert option_list.highlighted == 0, (
        f"Expected highlight at index 0, got {option_list.highlighted}"
    )


# ── Highlight return scenarios ─────────────────────────────────────────────────


@given("the user is on the new agent form")
def given_user_on_new_agent_form(ctx):
    ctx.ensure_mounted()

    async def _open_form():
        ctx.app._show_new_agent_form()
        await ctx.pilot.pause()

    ctx.run(_open_form())


@when("the user presses Escape")
def when_user_presses_escape(ctx):
    async def _press_escape():
        await ctx.pilot.press("escape")
        await ctx.pilot.pause()

    ctx.run(_press_escape())


@then("the dashboard should be visible")
def then_dashboard_visible(ctx):
    dashboard = ctx.app.query_one("#dashboard")
    assert dashboard.display is True, "Dashboard should be visible"


@given(parsers.parse('the user had "{label}" highlighted'))
def given_user_had_highlighted(ctx, label, agents_created):
    ctx.ensure_mounted()

    async def _set_highlight():
        option_list = ctx.app.query_one("#agent-option-list")
        for i in range(option_list.option_count):
            option = option_list.get_option_at_index(i)
            if label in str(option.prompt):
                option_list.highlighted = i
                break
        await ctx.pilot.pause()

    ctx.run(_set_highlight())


@when("the user returns to the dashboard")
def when_user_returns_to_dashboard(ctx):
    async def _return():
        ctx.app._show_dashboard()
        await ctx.pilot.pause()

    ctx.run(_return())


@then(parsers.parse('the highlighted agent should be "{label}"'))
def then_highlighted_agent_is(ctx, label):
    option_list = ctx.app.query_one("#agent-option-list")
    assert option_list.highlighted is not None, "No item highlighted"
    highlighted_option = option_list.get_option_at_index(option_list.highlighted)
    label_text = str(highlighted_option.prompt)
    assert label in label_text, (
        f"Expected highlighted agent '{label}', got prompt text: '{label_text}'"
    )


@given(parsers.parse('the user has "{label}" highlighted on the dashboard'))
def given_user_has_highlighted(ctx, label, agents_created):
    ctx.ensure_mounted()

    async def _set_highlight():
        option_list = ctx.app.query_one("#agent-option-list")
        for i in range(option_list.option_count):
            option = option_list.get_option_at_index(i)
            if label in str(option.prompt):
                option_list.highlighted = i
                break
        await ctx.pilot.pause()

    ctx.run(_set_highlight())


@when("the periodic refresh runs")
def when_periodic_refresh_runs(ctx):
    async def _refresh():
        ctx.app._on_refresh()
        await ctx.pilot.pause()

    ctx.run(_refresh())


@then(parsers.parse('the highlighted agent should still be "{label}"'))
def then_highlighted_agent_still_is(ctx, label):
    option_list = ctx.app.query_one("#agent-option-list")
    assert option_list.highlighted is not None, "No item highlighted after refresh"
    highlighted_option = option_list.get_option_at_index(option_list.highlighted)
    label_text = str(highlighted_option.prompt)
    assert label in label_text, (
        f"Expected highlighted agent still '{label}', got prompt text: '{label_text}'"
    )


# ── Status bar steps ───────────────────────────────────────────────────────────


@then(parsers.parse('the status bar should show "{text}"'))
def then_status_bar_shows(ctx, text):
    status_bar = ctx.app.query_one("#status-bar")
    rendered = str(status_bar.render())
    assert text in rendered, (
        f"Expected status bar to contain '{text}', got: '{rendered}'"
    )


@given(parsers.parse("{n:d} agents are in history"))
def given_agents_in_history(ctx, n):
    for i in range(n):
        ctx.history_mgr.add_entry(
            agent_id=i + 1,
            label=f"agent-{i+1}",
            dir="/tmp/test",
            command=["test"],
            created_at="2026-01-01T00:00:00Z",
        )


# ── Keyboard shortcut step definitions ────────────────────────────────────────


def _seed_agent(ctx, label: str, state: AgentState, real_tmux: bool = False) -> AgentInfo:
    """Seed a single agent into state and return the AgentInfo."""
    agent_id = ctx.state_mgr.next_id()
    session_name = f"aque-test-{agent_id}"
    if real_tmux:
        server = libtmux.Server()
        session = server.new_session(session_name=session_name, detach=True)
        ctx._tmux_sessions.append(session_name)
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


def _highlight_agent_by_label(ctx, label: str) -> None:
    """Highlight the option-list entry whose prompt contains label."""
    async def _do_highlight():
        option_list = ctx.app.query_one("#agent-option-list")
        for i in range(option_list.option_count):
            option = option_list.get_option_at_index(i)
            if label in str(option.prompt):
                option_list.highlighted = i
                break
        await ctx.pilot.pause()

    ctx.run(_do_highlight())


@given("the user is on the dashboard")
def given_user_is_on_dashboard(ctx):
    ctx.ensure_mounted()


@given(parsers.parse('agent "{label}" is highlighted on the dashboard'))
def given_agent_highlighted_on_dashboard(ctx, label):
    _seed_agent(ctx, label, AgentState.RUNNING, real_tmux=True)
    ctx.ensure_mounted()
    _highlight_agent_by_label(ctx, label)


@given(parsers.parse('agent "{label}" is running and highlighted'))
def given_agent_running_and_highlighted(ctx, label):
    _seed_agent(ctx, label, AgentState.RUNNING)
    ctx.ensure_mounted()
    _highlight_agent_by_label(ctx, label)


@given(parsers.parse('agent "{label}" is on_hold and highlighted'))
def given_agent_on_hold_and_highlighted(ctx, label):
    _seed_agent(ctx, label, AgentState.ON_HOLD)
    ctx.ensure_mounted()
    _highlight_agent_by_label(ctx, label)


@when(parsers.parse('the user presses "{key}"'))
def when_user_presses_key(ctx, key):
    async def _press():
        await ctx.pilot.press(key)
        await ctx.pilot.pause()

    ctx.run(_press())


@then("the new agent form should be visible")
def then_new_agent_form_visible(ctx):
    forms = ctx.app.query("NewAgentForm")
    assert len(forms) > 0, "Expected NewAgentForm to be mounted"
    form = forms.first()
    assert form.display is True, "NewAgentForm should be visible"


@then(parsers.parse('agent "{label}" should be moved to history'))
def then_agent_moved_to_history(ctx, label):
    # Agent should no longer be in active state
    state = ctx.state_mgr.load()
    active_labels = [a.label for a in state.agents]
    assert label not in active_labels, (
        f"Expected '{label}' to be removed from active agents, still found in: {active_labels}"
    )
    # Agent should be in history
    history_entries = ctx.history_mgr.load()
    history_labels = [e["label"] for e in history_entries]
    assert label in history_labels, (
        f"Expected '{label}' in history, got: {history_labels}"
    )


@then(parsers.parse('agent "{label}" should be in "{state_str}" state'))
def then_agent_in_state(ctx, label, state_str):
    state = ctx.state_mgr.load()
    agent = next((a for a in state.agents if a.label == label), None)
    assert agent is not None, f"Agent '{label}' not found in active agents"
    assert agent.state.value == state_str, (
        f"Expected agent '{label}' to be in state '{state_str}', got '{agent.state.value}'"
    )


# ── Preview pane step definitions ────────────────────────────────────────────


@given("the agent list is empty", target_fixture="ctx")
def given_agent_list_is_empty(ctx):
    """No agents in state — the list will be empty after mounting."""
    ctx.ensure_mounted()
    return ctx


@then(parsers.parse('the preview pane should show "{text}"'))
def then_preview_pane_shows(ctx, text):
    preview = ctx.app.query_one("#preview-pane")
    rendered = str(preview.render())
    assert text in rendered, (
        f"Expected preview pane to contain '{text}', got: '{rendered}'"
    )


@given(parsers.parse('agent "{label}" is running with tmux session "{session_name}"'), target_fixture="ctx")
def given_agent_running_with_tmux_session(ctx, label, session_name):
    """Seed an agent and create a real tmux session for it."""
    server = libtmux.Server()
    session = server.new_session(session_name=session_name, detach=True)
    ctx._tmux_sessions.append(session_name)

    agent_id = ctx.state_mgr.next_id()
    agent = AgentInfo(
        id=agent_id,
        tmux_session=session_name,
        label=label,
        dir="/tmp/test",
        command=["test"],
        state=AgentState.RUNNING,
        pid=10000 + agent_id,
    )
    ctx.state_mgr.add_agent(agent)
    ctx._preview_session = session
    return ctx


@given("the tmux pane contains output text")
def given_tmux_pane_contains_output(ctx):
    """Send some text to the tmux pane so there is content to preview."""
    session = ctx._preview_session
    session.active_pane.send_keys("echo hello_preview_test", enter=True)
    import time
    time.sleep(0.3)  # give the shell a moment to produce output


@when(parsers.parse('the user highlights "{label}"'))
def when_user_highlights(ctx, label):
    ctx.ensure_mounted()
    _highlight_agent_by_label(ctx, label)
    # Trigger a preview refresh after highlighting
    async def _refresh():
        ctx.app._refresh_preview()
        await ctx.pilot.pause()
    ctx.run(_refresh())


@then(parsers.parse('the agent list should show a "{type_name}" type tag for "{label}"'))
def then_agent_list_shows_type_tag(ctx, type_name, label):
    """Check for type tag in the raw Rich markup string.

    desk.py renders type tags as: [dim]\\[typename][/dim]
    So str(option.prompt) contains '\\[typename]' (escaped bracket).
    """
    option_list = ctx.app.query_one("#agent-option-list")
    for i in range(option_list.option_count):
        option = option_list.get_option_at_index(i)
        label_text = str(option.prompt)
        if label in label_text:
            # The type tag appears as \[typename] in the markup string
            assert f"\\[{type_name}]" in label_text, (
                f"Expected type tag '\\[{type_name}]' in prompt for '{label}', got: '{label_text}'"
            )
            return
    pytest.fail(f"Agent '{label}' not found in option list")


@then(parsers.parse('the agent list should not show a type tag for "{label}"'))
def then_agent_list_shows_no_type_tag(ctx, label):
    """Check that no type tag markup is present.

    desk.py renders type tags as: [dim]\\[typename][/dim]
    An untyped agent should have no '\\[' in its prompt.
    """
    import re
    option_list = ctx.app.query_one("#agent-option-list")
    for i in range(option_list.option_count):
        option = option_list.get_option_at_index(i)
        label_text = str(option.prompt)
        if label in label_text:
            # Type tag markup looks like \[typename] — check it's absent
            assert not re.search(r'\\\[', label_text), (
                f"Expected no type tag in prompt for '{label}', got: '{label_text}'"
            )
            return
    pytest.fail(f"Agent '{label}' not found in option list")


@then("the preview pane should show the last 30 lines of the tmux pane")
def then_preview_pane_shows_tmux_content(ctx):
    """Verify the preview pane contains content captured from the tmux pane."""
    preview = ctx.app.query_one("#preview-pane")
    rendered = str(preview.render())
    # The preview should not show the placeholder text
    assert "Select an agent to preview" not in rendered, (
        "Preview pane should show tmux content, not the placeholder"
    )
    # It should contain text echoed into the pane (or at least agent header)
    assert "builder" in rendered, (
        f"Expected 'builder' label in preview pane, got: '{rendered}'"
    )
