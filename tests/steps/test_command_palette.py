"""BDD tests for command_palette.feature."""
import asyncio

import pytest
from pytest_bdd import scenario, given, when, then, parsers

from aque.desk import DeskApp
from aque.history import HistoryManager
from aque.state import AgentInfo, AgentState, StateManager
from aque.widgets.command_palette import CommandPalette


FEATURE = "../../features/command_palette.feature"


@scenario(FEATURE, "Pressing ctrl+k opens the palette")
def test_palette_opens():
    pass


@scenario(FEATURE, "Palette lists each agent as an attach item")
def test_palette_lists_agents():
    pass


@scenario(FEATURE, "Typing filters the palette")
def test_palette_filters():
    pass


@scenario(FEATURE, "Selecting an attach item closes the palette and attaches")
def test_palette_attach_dispatch():
    pass


@scenario(FEATURE, "Pressing Escape closes the palette without acting")
def test_palette_escape_closes():
    pass


class Ctx:
    def __init__(self, tmp_aque_dir):
        self.tmp_aque_dir = tmp_aque_dir
        self.state_mgr = StateManager(tmp_aque_dir)
        self.history_mgr = HistoryManager(tmp_aque_dir)
        self.app = None
        self.pilot = None
        self.attached_label = None
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


@given("the aque desk is open", target_fixture="ctx")
def given_desk_is_open(ctx):
    return ctx


@given("the following agents exist:", target_fixture="agents_created")
def given_agents_exist_table(ctx, datatable):
    out = []
    for row in _datatable_as_dicts(datatable):
        agent_id = ctx.state_mgr.next_id()
        agent = AgentInfo(
            id=agent_id,
            tmux_session=f"aque-{agent_id}",
            label=row["label"],
            dir="/tmp/test",
            command=["test"],
            state=AgentState(row["state"]),
            pid=10000 + agent_id,
        )
        ctx.state_mgr.add_agent(agent)
        out.append(agent)
    return out


@when("the dashboard loads")
def when_dashboard_loads(ctx):
    ctx.ensure_mounted()

    async def _refresh():
        ctx.app._refresh_agent_list(reset_highlight=True)
        await ctx.pilot.pause()

    ctx.run(_refresh())


@when(parsers.parse('the user presses "{key}"'))
def when_user_presses(ctx, key):
    async def _press():
        await ctx.pilot.press(key)
        await ctx.pilot.pause()

    ctx.run(_press())


@when(parsers.parse('the palette receives the query "{q}"'))
def when_palette_receives_query(ctx, q):
    async def _type():
        with ctx.app._context():
            palette = ctx.app.screen
            assert isinstance(palette, CommandPalette), (
                f"Expected CommandPalette on top, got {type(palette).__name__}"
            )
            input_widget = palette.query_one("#cmdk-input")
            input_widget.value = q
            # Trigger the rebuild directly — pytest pilot doesn't simulate typing.
            palette._rebuild_items(q)
            await ctx.pilot.pause()

    ctx.run(_type())


@when(parsers.parse('the palette dispatches "{label}"'))
def when_palette_dispatches(ctx, label):
    """Select the palette item whose label matches and confirm."""
    # Mock the attach so the test doesn't need a real tmux session; record the
    # target so we can assert which agent the palette dispatched to.
    def _mock_attach(agent):
        ctx.attached_label = agent.label
        ctx.app._dismiss_triage_modal()
    ctx.app._attach_to_agent = _mock_attach

    async def _dispatch():
        with ctx.app._context():
            palette = ctx.app.screen
            assert isinstance(palette, CommandPalette), "Palette not active"
            ol = palette.query_one("#cmdk-list")
            for i in range(ol.option_count):
                opt = ol.get_option_at_index(i)
                if label in str(opt.prompt):
                    ol.highlighted = i
                    break
            palette._select_current()
            await ctx.pilot.pause()

    ctx.run(_dispatch())


@when("the user presses Escape")
def when_user_presses_escape(ctx):
    async def _press():
        await ctx.pilot.press("escape")
        await ctx.pilot.pause()

    ctx.run(_press())


@then("the command palette should be dismissed")
def then_palette_dismissed(ctx):
    assert not isinstance(ctx.app.screen, CommandPalette), (
        f"Expected palette dismissed, but {type(ctx.app.screen).__name__} is active"
    )


@then(parsers.parse('the attach should target "{label}"'))
def then_attach_target(ctx, label):
    # Attaching is a tmux session takeover that no longer mutates persisted
    # state, so the observable is the dispatch target the palette chose.
    assert getattr(ctx, "attached_label", None) == label, (
        f"Expected attach to target '{label}', got {getattr(ctx, 'attached_label', None)!r}"
    )


@then("the command palette should be visible")
def then_palette_visible(ctx):
    assert isinstance(ctx.app.screen, CommandPalette), (
        f"Expected CommandPalette to be the active screen, got {type(ctx.app.screen).__name__}"
    )


@then(parsers.parse('the palette should contain an item labelled "{label}"'))
def then_palette_contains_item(ctx, label):
    palette = ctx.app.screen
    assert isinstance(palette, CommandPalette), "Palette not active"
    ol = palette.query_one("#cmdk-list")
    labels = [str(ol.get_option_at_index(i).prompt) for i in range(ol.option_count)]
    assert any(label in text for text in labels), (
        f"Expected '{label}' in palette items, got: {labels}"
    )


@then(parsers.parse('the palette should not contain an item labelled "{label}"'))
def then_palette_not_contains_item(ctx, label):
    palette = ctx.app.screen
    assert isinstance(palette, CommandPalette), "Palette not active"
    ol = palette.query_one("#cmdk-list")
    labels = [str(ol.get_option_at_index(i).prompt) for i in range(ol.option_count)]
    assert not any(label in text for text in labels), (
        f"Expected '{label}' NOT in palette items, got: {labels}"
    )
