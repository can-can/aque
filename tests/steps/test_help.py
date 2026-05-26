"""BDD tests for help.feature."""
import asyncio

import pytest
from pytest_bdd import scenario, given, when, then, parsers

from aque.desk import DeskApp
from aque.history import HistoryManager
from aque.state import StateManager
from aque.widgets.help_modal import HelpModal


FEATURE = "../../features/help.feature"


@scenario(FEATURE, 'Pressing "?" opens the help overlay')
def test_help_opens():
    pass


@scenario(FEATURE, "Help modal lists the core actions")
def test_help_lists_actions():
    pass


@scenario(FEATURE, "Pressing Escape closes the help overlay")
def test_help_closes():
    pass


@scenario(FEATURE, 'Pressing "?" again closes the help overlay')
def test_help_closes_on_question_mark():
    pass


@scenario(FEATURE, "Help modal lists the responder embed shortcut")
def test_help_lists_responder_embed():
    pass


@scenario(FEATURE, "Help modal no longer lists the removed responders toggle")
def test_help_omits_removed_responders_toggle():
    pass


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


@given("the aque desk is open", target_fixture="ctx")
def given_desk_is_open(ctx):
    ctx.ensure_mounted()
    return ctx


@given("the help modal is open")
def given_help_open(ctx):
    async def _open():
        await ctx.pilot.press("?")
        await ctx.pilot.pause()

    ctx.run(_open())


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


@then("the help modal should be visible")
def then_help_visible(ctx):
    assert isinstance(ctx.app.screen, HelpModal), (
        f"Expected HelpModal on top, got {type(ctx.app.screen).__name__}"
    )


@then("the help modal should be dismissed")
def then_help_dismissed(ctx):
    assert not isinstance(ctx.app.screen, HelpModal), (
        f"Expected HelpModal dismissed, but {type(ctx.app.screen).__name__} is active"
    )


@then(parsers.parse('the help modal should mention "{text}"'))
def then_help_mentions(ctx, text):
    assert isinstance(ctx.app.screen, HelpModal), "Help modal not active"
    box = ctx.app.screen.query_one("#help-box")
    rendered_text = " ".join(
        str(s.render()) for s in box.query("Static")
    )
    assert text in rendered_text, (
        f"Expected '{text}' in help modal, got: {rendered_text!r}"
    )


@then(parsers.parse('the help modal should not mention "{text}"'))
def then_help_does_not_mention(ctx, text):
    assert isinstance(ctx.app.screen, HelpModal), "Help modal not active"
    box = ctx.app.screen.query_one("#help-box")
    rendered_text = " ".join(
        str(s.render()) for s in box.query("Static")
    )
    assert text not in rendered_text, (
        f"Expected '{text}' to be absent from help modal, but got: {rendered_text!r}"
    )
