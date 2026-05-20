"""BDD tests for quick_launch.feature.

Mirrors tests/steps/test_new_agent.py: a sync context holder drives the
Textual pilot via run_until_complete. launch_agent is mocked so no real tmux
session is created; the responder and monitor fork are disabled.
"""
import asyncio
from unittest.mock import patch

import pytest
from pytest_bdd import scenario, given, when, then, parsers

from aque.desk import DeskApp, QuickLaunchForm
from aque.history import HistoryManager
from aque.state import StateManager, AgentInfo, AgentState


FEATURE = "../../features/quick_launch.feature"


@scenario(FEATURE, "Pressing r with no history shows an empty state")
def test_empty_state():
    pass


@scenario(FEATURE, "Pressing r lists recent tasks")
def test_lists_recent_tasks():
    pass


@scenario(FEATURE, "Pressing Escape on the quick launch form returns to the dashboard")
def test_escape_returns_to_dashboard():
    pass


class QLContext:
    def __init__(self, tmp_aque_dir):
        self.tmp_aque_dir = tmp_aque_dir
        self.state_mgr = StateManager(tmp_aque_dir)
        self.history_mgr = HistoryManager(tmp_aque_dir)
        self.app = None
        self.pilot = None
        self._loop = None
        self._cm = None
        self.data = {}

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
        self.app.config["responder_enabled"] = False
        self.app._ensure_monitor_running = lambda: None
        self._cm = self.app.run_test()
        self.pilot = await self._cm.__aenter__()
        await self.pilot.pause()

    async def _shutdown(self):
        if self._cm is not None:
            await self._cm.__aexit__(None, None, None)
            self._cm = None

    def cleanup(self):
        patcher = self.data.get("_patcher")
        if patcher is not None:
            patcher.stop()
        if self.app is not None and self._loop is not None:
            try:
                self._loop.run_until_complete(self._shutdown())
            except Exception:
                pass
        if self._loop is not None:
            self._loop.close()
            self._loop = None


@pytest.fixture
def ctx(tmp_aque_dir, request):
    c = QLContext(tmp_aque_dir)
    request.addfinalizer(c.cleanup)
    return c


def _install_fake_launch(ctx):
    def _fake_launch(command, working_dir, label, state_manager,
                     prefix="aque", background=False, agent_type=None):
        agent_id = state_manager.next_id()
        state_manager.add_agent(AgentInfo(
            id=agent_id, tmux_session=f"{prefix}-fake-{agent_id}",
            label=label or "fake-agent", dir=working_dir, command=command,
            state=AgentState.RUNNING, pid=99999, agent_type=agent_type,
        ))
        return agent_id
    patcher = patch("aque.desk.launch_agent", side_effect=_fake_launch)
    ctx.data["mock_launch"] = patcher.start()
    ctx.data["_patcher"] = patcher


# ── Shared steps ────────────────────────────────────────────────────────────


@given("the aque desk is open", target_fixture="ctx")
def given_desk_open(ctx):
    return ctx


@given("the history has no tasks")
def given_no_tasks(ctx):
    pass  # tmp history is empty by default


@given(parsers.parse('the history has a recent "{agent_type}" task in "{dir}" labeled "{label}"'))
def given_recent_task(ctx, agent_type, dir, label):
    ctx.history_mgr.add_entry(
        agent_id=1, label=label, dir=dir, command=[agent_type],
        created_at="2026-01-01T00:00:00Z", agent_type=agent_type,
    )


@when('the user presses "r"')
def when_press_r(ctx):
    ctx.ensure_mounted()

    async def _press():
        await ctx.pilot.press("r")
        await ctx.pilot.pause()

    ctx.run(_press())


@when("the user presses Escape")
def when_press_escape(ctx):
    async def _press():
        await ctx.pilot.press("escape")
        await ctx.pilot.pause()

    ctx.run(_press())


@then("the quick launch form should be visible")
def then_form_visible(ctx):
    forms = ctx.app.query("QuickLaunchForm")
    assert len(forms) > 0, "Expected QuickLaunchForm in the DOM"


@then(parsers.parse('the quick launch form should show "{text}"'))
def then_form_shows(ctx, text):
    empty = ctx.app.query_one("#quick-launch-empty")
    assert text in str(empty.render())


@then(parsers.parse('the quick launch list should contain "{text}"'))
def then_list_contains(ctx, text):
    ol = ctx.app.query_one("#quick-launch-list")
    prompts = [str(ol.get_option_at_index(i).prompt) for i in range(ol.option_count)]
    assert any(text in p for p in prompts), f"{text!r} not in {prompts}"


@then("the dashboard should be visible")
def then_dashboard_visible(ctx):
    assert ctx.app._mode == "dashboard"
    assert ctx.app.query_one("#dashboard").display is True


@scenario(FEATURE, "Selecting a typed recent task launches a new agent")
def test_select_typed_task_launches():
    pass


@when("the user selects the first recent task")
def when_select_first_task(ctx):
    _install_fake_launch(ctx)

    async def _select():
        ol = ctx.app.query_one("#quick-launch-list")
        ol.highlighted = 0
        await ctx.pilot.pause()
        await ctx.pilot.press("enter")
        await ctx.pilot.pause()

    ctx.run(_select())


@then(parsers.parse('a new agent should be launched with command "{command}" in "{dir}"'))
def then_agent_launched(ctx, command, dir):
    mock = ctx.data.get("mock_launch")
    assert mock is not None and mock.called, "launch_agent was not called"
    _, kwargs = mock.call_args
    assert kwargs["command"] == [command], kwargs
    assert kwargs["working_dir"] == dir, kwargs
    state = ctx.app.state_mgr.load()
    assert any(a.dir == dir for a in state.agents), "agent not in state"
