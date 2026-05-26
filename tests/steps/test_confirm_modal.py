"""BDD tests for confirm_modal.feature — generic yes/no confirmation dialog.

The ``ConfirmModal`` widget is reused for any destructive action (kill, etc.).
These scenarios pin its keyboard contract independently of any caller so
regressions surface here rather than via downstream tests.
"""
import asyncio

import pytest
from pytest_bdd import scenario, given, when, then, parsers

from aque.desk import DeskApp
from aque.state import StateManager
from aque.widgets.confirm_modal import ConfirmModal


FEATURE = "../../features/confirm_modal.feature"


# ── Scenarios ─────────────────────────────────────────────────────────


@scenario(FEATURE, "Pressing y confirms the destructive action")
def test_y_confirms():
    pass


@scenario(FEATURE, "Pressing n cancels the destructive action")
def test_n_cancels():
    pass


@scenario(FEATURE, "Pressing Escape cancels the destructive action")
def test_escape_cancels():
    pass


@scenario(FEATURE, "Cancel button is focused by default so a stray Enter is safe")
def test_cancel_focused_by_default():
    pass


# ── Context ───────────────────────────────────────────────────────────


class Ctx:
    def __init__(self, tmp_aque_dir):
        self.tmp_aque_dir = tmp_aque_dir
        self.state_mgr = StateManager(tmp_aque_dir)
        self.app = None
        self.pilot = None
        self._loop = None
        self._run_test_cm = None
        # Captured dismiss result from the modal (True/False), or sentinel
        # ``_NOT_DISMISSED`` while the screen is still up.
        self.result = _NOT_DISMISSED

    def _get_loop(self):
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
        return self._loop

    def run(self, coro):
        # Set Textual's active_app contextvar so callbacks on the pushed
        # ModalScreen can resolve self.app.
        from textual._context import active_app

        async def _wrapped():
            token = active_app.set(self.app) if self.app is not None else None
            try:
                return await coro
            finally:
                if token is not None:
                    active_app.reset(token)

        return self._get_loop().run_until_complete(_wrapped())

    async def _mount(self):
        self.app = DeskApp(aque_dir=self.tmp_aque_dir, _skip_attach=True)
        # Skip orphan scan so it doesn't push its own modal over ours.
        self.app._scan_for_orphans = lambda: None
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


_NOT_DISMISSED = object()


@pytest.fixture
def ctx(tmp_aque_dir, request):
    c = Ctx(tmp_aque_dir)
    request.addfinalizer(c.cleanup)
    return c


# ── Steps ─────────────────────────────────────────────────────────────


@given(parsers.parse('a confirm modal is pushed with prompt "{prompt}"'),
       target_fixture="ctx")
def given_confirm_modal_pushed(ctx, prompt):
    """Mount the desk and push a ConfirmModal on top with the given prompt,
    capturing whatever dismiss(result) gets called with into ctx.result."""
    ctx.run(ctx._mount())

    def _capture(result):
        ctx.result = result

    async def _push():
        modal = ConfirmModal(prompt)
        await ctx.app.push_screen(modal, _capture)
        await ctx.pilot.pause()

    ctx.run(_push())
    return ctx


@when(parsers.parse('the user presses "{key}"'))
def when_user_presses_key(ctx, key):
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


@then(parsers.parse("the confirm modal should dismiss with result {value:l}"))
def then_modal_dismisses_with_result(ctx, value):
    expected = {"true": True, "false": False}[value.lower()]
    assert ctx.result is expected, (
        f"Expected dismiss(result={expected!r}); got {ctx.result!r}"
    )
    assert not isinstance(ctx.app.screen, ConfirmModal), (
        "Expected ConfirmModal to be off the screen stack"
    )


@then(parsers.parse('the focused button id should be "{button_id}"'))
def then_focused_button_id(ctx, button_id):
    focused = ctx.app.focused
    assert focused is not None, "Nothing has focus"
    assert getattr(focused, "id", None) == button_id, (
        f"Expected focused id={button_id!r}; got id={getattr(focused, 'id', None)!r} "
        f"(widget={type(focused).__name__})"
    )
