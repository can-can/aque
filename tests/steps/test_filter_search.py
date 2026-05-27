"""BDD tests for filter_search.feature.

Reuses the DashboardContext pattern from test_dashboard.py so app mount and
shutdown share an event loop, sidestepping Textual's ContextVar quirks.
"""
import asyncio

import pytest
from pytest_bdd import scenario, given, when, then, parsers

from aque.desk import DeskApp
from aque.history import HistoryManager
from aque.state import AgentInfo, AgentState, StateManager
from textual.widgets import Input


FEATURE = "../../features/filter_search.feature"


# ── Scenarios ─────────────────────────────────────────────────────────


@scenario(FEATURE, 'Pressing "2" filters the list to waiting agents')
def test_two_filters_waiting():
    pass


@scenario(FEATURE, "Pressing the same filter key again clears the filter")
def test_same_key_toggles_filter():
    pass


@scenario(FEATURE, "Pressing Escape clears the filter")
def test_escape_clears_filter():
    pass


@scenario(FEATURE, 'Pressing "/" focuses the search input')
def test_slash_opens_search():
    pass


@scenario(FEATURE, "Pressing Escape closes the open search input even when empty")
def test_escape_closes_empty_search_input():
    pass


@scenario(FEATURE, "Typing in the search input filters the list")
def test_search_input_filters():
    pass


@scenario(FEATURE, "Searching by agent type matches even though the type is not shown on the row")
def test_search_by_agent_type():
    pass


@scenario(FEATURE, "Active filter is highlighted in the status bar")
def test_active_filter_indicator():
    pass


@scenario(FEATURE, "Filter and search compose — both must match")
def test_filter_and_search_combine():
    pass


@scenario(FEATURE, "Pressing Escape clears both the filter and the search query")
def test_escape_clears_both():
    pass


# ── Context ───────────────────────────────────────────────────────────


class Ctx:
    def __init__(self, tmp_aque_dir):
        self.tmp_aque_dir = tmp_aque_dir
        self.state_mgr = StateManager(tmp_aque_dir)
        self.history_mgr = HistoryManager(tmp_aque_dir)
        self.app = None
        self.pilot = None
        self._loop = None
        self._run_test_cm = None

    def _get_loop(self):
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
        return self._loop

    def run(self, coro):
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
    c = Ctx(tmp_aque_dir)
    request.addfinalizer(c.cleanup)
    return c


def _datatable_as_dicts(datatable):
    if not datatable:
        return []
    headers = datatable[0]
    return [dict(zip(headers, row)) for row in datatable[1:]]


# ── Step overrides ────────────────────────────────────────────────────


@given("the aque desk is open", target_fixture="ctx")
def given_desk_is_open(ctx):
    return ctx


@given("the following agents exist:", target_fixture="agents_created")
def given_agents_exist(ctx, datatable):
    rows = _datatable_as_dicts(datatable)
    out = []
    for row in rows:
        agent_id = ctx.state_mgr.next_id()
        agent_type = row.get("agent_type") or None
        agent = AgentInfo(
            id=agent_id,
            tmux_session=f"aque-{agent_id}",
            label=row["label"],
            dir="/tmp/test",
            command=["test"],
            state=AgentState(row["state"]),
            pid=10000 + agent_id,
            agent_type=agent_type,
        )
        ctx.state_mgr.add_agent(agent)
        out.append(agent)
    return out


@when("the dashboard loads")
def when_dashboard_loads(ctx):
    ctx.ensure_mounted()

    async def _refresh():
        ctx.app._refresh_agent_list(reset_highlight=True)
        ctx.app._refresh_status_bar()
        await ctx.pilot.pause()

    ctx.run(_refresh())


@when(parsers.parse('the user presses "{key}"'))
def when_user_presses(ctx, key):
    async def _press():
        await ctx.pilot.press(key)
        await ctx.pilot.pause()

    ctx.run(_press())


@when("the user presses Escape")
def when_user_presses_escape(ctx):
    async def _press():
        await ctx.pilot.press("escape")
        await ctx.pilot.pause()

    ctx.run(_press())


@when(parsers.parse('the user opens search and types "{text}"'))
def when_user_opens_search_and_types(ctx, text):
    async def _act():
        await ctx.pilot.press("slash")
        await ctx.pilot.pause()
        # Pilot.press doesn't type strings; drive the input directly.
        search = ctx.app.query_one("#search-input", Input)
        search.value = text
        # Manually fire the on_input_changed path so filter updates.
        ctx.app._set_search(text)
        await ctx.pilot.pause()

    ctx.run(_act())


# ── Thens ─────────────────────────────────────────────────────────────


@then(parsers.parse('the agent list should contain "{label}"'))
def then_agent_list_contains(ctx, label):
    ol = ctx.app.query_one("#agent-option-list")
    labels = [str(ol.get_option_at_index(i).prompt) for i in range(ol.option_count)]
    assert any(label in text for text in labels), (
        f"Expected '{label}' in agent list, got: {labels}"
    )


@then(parsers.parse('the agent list should not contain "{label}"'))
def then_agent_list_not_contains(ctx, label):
    ol = ctx.app.query_one("#agent-option-list")
    labels = [str(ol.get_option_at_index(i).prompt) for i in range(ol.option_count)]
    assert not any(label in text for text in labels), (
        f"Expected '{label}' NOT in agent list, got: {labels}"
    )


@then("the search input should be visible")
def then_search_visible(ctx):
    inputs = ctx.app.query("#search-input")
    assert len(inputs) == 1, "Search input not mounted"
    assert inputs.first().display is True


@then("the search input should not be visible")
def then_search_not_visible(ctx):
    inputs = ctx.app.query("#search-input")
    assert len(inputs) == 0, (
        f"Expected #search-input to be unmounted, but {len(inputs)} found"
    )


@then("the search input should have focus")
def then_search_focused(ctx):
    focused = ctx.app.focused
    assert focused is not None and focused.id == "search-input", (
        f"Expected #search-input focused, got: {focused}"
    )


@then(parsers.parse('the status bar should show "{text}"'))
def then_status_bar_shows(ctx, text):
    status_bar = ctx.app.query_one("#status-bar")
    rendered = str(status_bar.render())
    assert text in rendered, (
        f"Expected status bar to contain '{text}', got: '{rendered}'"
    )
