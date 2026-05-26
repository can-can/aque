"""BDD tests for resume_picker.feature — create-time session continuity.

The ``ResumePickerScreen`` widget shows prior conversation sessions for a
directory + agent type and returns ``PickerResult | None`` via ``dismiss``.
These scenarios pin its keyboard + selection contract without depending on
real on-disk session files.
"""
import asyncio
from datetime import datetime, timezone

import pytest
from pytest_bdd import scenario, given, when, then, parsers

from aque.desk import DeskApp
from aque.sessions import SessionSummary
from aque.state import StateManager
from aque.widgets.resume_picker import PickerResult, ResumePickerScreen


FEATURE = "../../features/resume_picker.feature"


# ── Scenarios ─────────────────────────────────────────────────────────


@scenario(FEATURE, '"Start fresh" is pre-selected when the picker opens')
def test_fresh_preselected():
    pass


@scenario(FEATURE, "Each session row shows age, size, and the first prompt")
def test_rows_show_age_size_prompt():
    pass


@scenario(FEATURE, 'Selecting "Start fresh" dismisses with a fresh result')
def test_select_fresh_returns_fresh():
    pass


@scenario(FEATURE, "Selecting a session dismisses with its session_id")
def test_select_session_returns_session_id():
    pass


@scenario(FEATURE, "Pressing Escape dismisses with no result")
def test_escape_returns_none():
    pass


# ── Context ───────────────────────────────────────────────────────────


_NOT_DISMISSED = object()


class Ctx:
    def __init__(self, tmp_aque_dir):
        self.tmp_aque_dir = tmp_aque_dir
        self.state_mgr = StateManager(tmp_aque_dir)
        self.app = None
        self.pilot = None
        self._loop = None
        self._run_test_cm = None
        self.result = _NOT_DISMISSED

    def _get_loop(self):
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
        return self._loop

    def run(self, coro):
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


@pytest.fixture
def ctx(tmp_aque_dir, request):
    c = Ctx(tmp_aque_dir)
    request.addfinalizer(c.cleanup)
    return c


# ── Steps ─────────────────────────────────────────────────────────────


@given("the resume picker is opened with the following sessions:",
       target_fixture="ctx")
def given_picker_opened(ctx, datatable):
    """Build SessionSummary entries from the datatable, push the picker
    over the desk, capture its dismiss result into ctx.result."""
    headers = datatable[0]
    rows = [dict(zip(headers, row)) for row in datatable[1:]]

    summaries: list[SessionSummary] = []
    for row in rows:
        summaries.append(SessionSummary(
            uuid=row["uuid"],
            first_prompt=row["first_prompt"],
            last_activity=None,
            mtime=datetime.fromisoformat(row["mtime"]),
            size_bytes=int(row["size_bytes"]),
        ))

    ctx.run(ctx._mount())

    def _capture(result):
        ctx.result = result

    async def _push():
        screen = ResumePickerScreen(
            summaries=summaries, cwd="/tmp/test", agent_type="claude",
        )
        await ctx.app.push_screen(screen, _capture)
        await ctx.pilot.pause()

    ctx.run(_push())
    return ctx


def _picker_list(ctx):
    return ctx.app.screen.query_one("#resume-picker-list")


@then(parsers.parse('the picker\'s highlighted option id should be "{opt_id}"'))
def then_highlighted_is(ctx, opt_id):
    ol = _picker_list(ctx)
    assert ol.highlighted is not None, "Nothing highlighted"
    opt = ol.get_option_at_index(ol.highlighted)
    assert opt.id == opt_id, (
        f"Expected highlighted id={opt_id!r}; got {opt.id!r}"
    )


@then(parsers.parse('the picker should list an option mentioning "{text}"'))
def then_list_mentions(ctx, text):
    ol = _picker_list(ctx)
    prompts = [str(ol.get_option_at_index(i).prompt) for i in range(ol.option_count)]
    joined = " | ".join(prompts)
    assert text in joined, f"Expected {text!r} in: {joined!r}"


@when(parsers.parse('the picker selects the option with id "{opt_id}"'))
def when_picker_selects(ctx, opt_id):
    async def _do():
        ol = _picker_list(ctx)
        for i in range(ol.option_count):
            if ol.get_option_at_index(i).id == opt_id:
                ol.highlighted = i
                break
        await ctx.pilot.pause()
        await ctx.pilot.press("enter")
        await ctx.pilot.pause()

    ctx.run(_do())


@when("the user presses Escape on the picker")
def when_user_presses_escape(ctx):
    async def _do():
        await ctx.pilot.press("escape")
        await ctx.pilot.pause()

    ctx.run(_do())


@then(parsers.parse(
    'the picker should dismiss with action "{action}" and session_id {session_id}'
))
def then_dismissed_with(ctx, action, session_id):
    assert isinstance(ctx.result, PickerResult), (
        f"Expected PickerResult, got: {ctx.result!r}"
    )
    expected_sid = None if session_id == "None" else session_id.strip('"')
    assert ctx.result.action == action, (
        f"Expected action={action!r}; got {ctx.result.action!r}"
    )
    assert ctx.result.session_id == expected_sid, (
        f"Expected session_id={expected_sid!r}; got {ctx.result.session_id!r}"
    )


@then("the picker should dismiss with no result")
def then_dismissed_with_none(ctx):
    assert ctx.result is None, (
        f"Expected dismiss(None); got: {ctx.result!r}"
    )
