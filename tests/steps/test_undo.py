"""BDD tests for undo.feature."""
import asyncio

import libtmux
import pytest
from pytest_bdd import scenario, given, when, then, parsers

from aque.desk import DeskApp
from aque.history import HistoryManager
from aque.state import AgentInfo, AgentState, StateManager


FEATURE = "../../features/undo.feature"


# ── Scenarios ─────────────────────────────────────────────────────────


@scenario(FEATURE, "Undo bar appears after killing an agent")
def test_undo_bar_appears():
    pass


@scenario(FEATURE, 'Pressing "u" restores a killed agent')
def test_undo_restores():
    pass


@scenario(FEATURE, "After undo, the history count returns to its prior value")
def test_undo_clears_history_entry():
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
        self._tmux_sessions: list[str] = []

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
    c = Ctx(tmp_aque_dir)
    request.addfinalizer(c.cleanup)
    return c


# ── Background ────────────────────────────────────────────────────────


@given("the aque desk is open", target_fixture="ctx")
def given_desk_is_open(ctx):
    return ctx


# ── Givens ────────────────────────────────────────────────────────────


@given(parsers.parse('agent "{label}" is running and highlighted'))
def given_agent_running_highlighted(ctx, label):
    # Use a real tmux session so _kill_agent doesn't error out and the
    # responder cleanup path doesn't trip on a missing partner.
    server = libtmux.Server()
    session_name = f"aque-test-undo-{label}"
    server.new_session(session_name=session_name, detach=True)
    ctx._tmux_sessions.append(session_name)

    agent_id = ctx.state_mgr.next_id()
    ctx.state_mgr.add_agent(AgentInfo(
        id=agent_id,
        tmux_session=session_name,
        label=label,
        dir="/tmp/test",
        command=["test"],
        state=AgentState.RUNNING,
        pid=10000 + agent_id,
    ))
    ctx.ensure_mounted()

    async def _highlight():
        ol = ctx.app.query_one("#agent-option-list")
        for i in range(ol.option_count):
            if label in str(ol.get_option_at_index(i).prompt):
                ol.highlighted = i
                break
        await ctx.pilot.pause()

    ctx.run(_highlight())


@given(parsers.parse("{n:d} agents are in history"))
def given_n_agents_in_history(ctx, n):
    for i in range(n):
        ctx.history_mgr.add_entry(
            agent_id=i + 1,
            label=f"agent-{i+1}",
            dir="/tmp/test",
            command=["test"],
            created_at="2026-01-01T00:00:00Z",
        )


# ── Whens ─────────────────────────────────────────────────────────────


@when(parsers.parse('the user presses "{key}"'))
def when_user_presses(ctx, key):
    async def _press():
        await ctx.pilot.press(key)
        await ctx.pilot.pause()

    ctx.run(_press())


# ── Thens ─────────────────────────────────────────────────────────────


@then("the undo bar should be visible")
def then_undo_bar_visible(ctx):
    bars = ctx.app.query("#undo-bar")
    assert len(bars) == 1, f"Expected 1 undo bar, got {len(bars)}"


@then(parsers.parse('the undo bar should mention "{text}"'))
def then_undo_bar_mentions(ctx, text):
    bar = ctx.app.query_one("#undo-bar")
    rendered = str(bar.render())
    assert text in rendered, f"Expected '{text}' in undo bar, got: {rendered!r}"


@then("the undo bar should be dismissed")
def then_undo_bar_dismissed(ctx):
    bars = ctx.app.query("#undo-bar")
    assert len(bars) == 0, "Expected undo bar to be dismissed"


@then(parsers.parse('the active agents should include "{label}"'))
def then_active_agents_include(ctx, label):
    state = ctx.state_mgr.load()
    labels = [a.label for a in state.agents]
    assert label in labels, f"Expected '{label}' in active agents, got: {labels}"


@then(parsers.parse("the history should contain {n:d} entry"))
@then(parsers.parse("the history should contain {n:d} entries"))
def then_history_contains(ctx, n):
    count = ctx.history_mgr.count()
    assert count == n, f"Expected {n} entries in history, got {count}"
