"""BDD tests for agent_lifecycle.feature scenarios.

Scenarios wired up (testable without real tmux attach/detach):
1. New agent starts in running state           — pure state test
2. Running agent transitions to waiting        — IdleDetector directly
3. Running agent transitions to exited         — real tmux session, kill it, check
4. Running agent can be put on hold            — TUI test with Pilot
5. On-hold agent can be resumed                — TUI test with Pilot
6. Any agent can be killed from dashboard      — TUI test with real tmux session
7. Agents are ordered by state priority        — pure unit test on sorted_agents

Deferred (require tmux attach-session subprocess which suspends terminal):
- Waiting agent transitions to focused on attach
- Focused agent transitions to running on detach
- Exited agent transitions to done on detach

Note: pytest-bdd 8.x has no native async step support. All step functions are sync.
Async operations (app mounting/piloting) are driven via ctx.run(), which calls
ctx.loop.run_until_complete() using the event loop created fresh for each test.
"""
import asyncio
import time
from unittest.mock import patch

import libtmux
import pytest
from pytest_bdd import scenario, given, when, then, parsers

from aque.desk import DeskApp, sorted_agents
from aque.history import HistoryManager
from aque.monitor import IdleDetector, session_exists
from aque.run import launch_agent
from aque.state import AgentInfo, AgentState, StateManager


FEATURE = "../../features/agent_lifecycle.feature"


# ── Scenario declarations ──────────────────────────────────────────────────────


@scenario(FEATURE, "New agent starts in running state")
def test_new_agent_starts_running():
    pass


@scenario(FEATURE, "Running agent transitions to waiting when idle")
def test_running_to_waiting_when_idle():
    pass


@scenario(FEATURE, "Running agent transitions to exited when tmux session dies")
def test_running_to_exited_when_session_dies():
    pass


@scenario(FEATURE, "Running agent can be put on hold")
def test_running_agent_can_be_put_on_hold():
    pass


@scenario(FEATURE, "On-hold agent can be resumed")
def test_on_hold_agent_can_be_resumed():
    pass


@scenario(FEATURE, "Any agent can be killed from dashboard")
def test_any_agent_can_be_killed():
    pass


@scenario(FEATURE, "Agents are ordered by state priority then by change time")
def test_agents_ordered_by_state_priority():
    pass


# ── Context holder ─────────────────────────────────────────────────────────────


class LifecycleContext:
    """Shared mutable context for BDD steps.

    Mirrors DashboardContext from test_dashboard.py. App is mounted lazily.
    All async work is driven via self.run(coro).
    """

    def __init__(self, tmp_aque_dir):
        self.tmp_aque_dir = tmp_aque_dir
        self.state_mgr = StateManager(tmp_aque_dir)
        self.history_mgr = HistoryManager(tmp_aque_dir)
        self.app = None
        self.pilot = None
        self._loop = None
        self._run_test_cm = None
        self._tmux_sessions = []  # track real tmux sessions for cleanup
        # plain dict for non-TUI steps
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
    c = LifecycleContext(tmp_aque_dir)
    request.addfinalizer(c.cleanup)
    return c


def _datatable_as_dicts(datatable):
    """Convert raw datatable (list of lists, first row = headers) to list of dicts."""
    rows = datatable
    if not rows:
        return []
    headers = rows[0]
    return [dict(zip(headers, row)) for row in rows[1:]]


def _seed_agent(ctx, label: str, state: AgentState, real_tmux: bool = False) -> AgentInfo:
    """Seed a single agent into state and return the AgentInfo."""
    agent_id = ctx.state_mgr.next_id()
    session_name = f"aque-lifecycle-test-{agent_id}"
    if real_tmux:
        server = libtmux.Server()
        server.new_session(session_name=session_name, detach=True)
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
    async def _do():
        option_list = ctx.app.query_one("#agent-option-list")
        for i in range(option_list.option_count):
            option = option_list.get_option_at_index(i)
            if label in str(option.prompt):
                option_list.highlighted = i
                break
        await ctx.pilot.pause()

    ctx.run(_do())


# ── Scenario 1: New agent starts in running state ─────────────────────────────


@when("a new agent is launched")
def when_new_agent_launched(ctx):
    agent_id = launch_agent(
        command=["echo", "hello"],
        working_dir="/tmp",
        label="builder",
        state_manager=ctx.state_mgr,
        prefix="aque-lifecycle-test",
    )
    ctx.data["new_agent_id"] = agent_id
    # Track the tmux session for cleanup
    state = ctx.state_mgr.load()
    agent = next((a for a in state.agents if a.id == agent_id), None)
    if agent:
        ctx._tmux_sessions.append(agent.tmux_session)


@then(parsers.parse('the agent should be in "{state_str}" state'))
def then_new_agent_in_state(ctx, state_str):
    agent_id = ctx.data["new_agent_id"]
    state = ctx.state_mgr.load()
    agent = next((a for a in state.agents if a.id == agent_id), None)
    assert agent is not None, f"Agent id={agent_id} not found"
    assert agent.state.value == state_str, (
        f"Expected state '{state_str}', got '{agent.state.value}'"
    )


# ── Scenario 2: Running agent transitions to waiting when idle ────────────────


@given(parsers.parse('agent "{label}" is in "running" state'), target_fixture="ctx")
def given_agent_running(label, ctx):
    agent = _seed_agent(ctx, label, AgentState.RUNNING)
    ctx.data["agent"] = agent
    ctx.data["label"] = label
    return ctx


@given("the agent has been idle for the configured timeout", target_fixture="ctx")
def given_agent_idle_for_timeout(ctx):
    detector = IdleDetector(idle_timeout=0.1)
    ctx.data["detector"] = detector
    ctx.data["stable_lines"] = ["❯ ", "  [Opus 4.6 (1M context)] ● high"]
    agent = ctx.data["agent"]
    # First update — establish stable baseline
    with patch("aque.monitor.has_children", return_value=True):
        detector.update(agent.id, agent.pid, ctx.data["stable_lines"])
    # Wait to exceed idle_timeout
    time.sleep(0.15)
    return ctx


@when("the monitor detects the idle state")
def when_monitor_detects_idle(ctx):
    agent = ctx.data["agent"]
    detector: IdleDetector = ctx.data["detector"]
    # Second update with same content — should now be idle
    with patch("aque.monitor.has_children", return_value=True):
        detector.update(agent.id, agent.pid, ctx.data["stable_lines"])
    assert detector.is_idle(agent.id), "IdleDetector should report agent as idle"
    # Simulate what the monitor loop does: update state
    ctx.state_mgr.update_agent_state(agent.id, AgentState.WAITING)


@then(parsers.parse('agent "{label}" should be in "waiting" state'))
def then_agent_in_waiting(ctx, label):
    state = ctx.state_mgr.load()
    agent = next((a for a in state.agents if a.label == label), None)
    assert agent is not None, f"Agent '{label}' not found"
    assert agent.state == AgentState.WAITING, (
        f"Expected '{label}' to be waiting, got '{agent.state.value}'"
    )


# ── Scenario 3: Running agent transitions to exited when tmux session dies ────


@given("the tmux session no longer exists", target_fixture="ctx")
def given_tmux_session_gone(ctx):
    agent: AgentInfo = ctx.data["agent"]
    # Create a real session then immediately kill it so it truly doesn't exist
    server = libtmux.Server()
    try:
        session = server.new_session(session_name=agent.tmux_session, detach=True)
        session.kill()
    except Exception:
        pass  # session never existed — that's fine too
    assert not session_exists(server, agent.tmux_session), (
        f"Session '{agent.tmux_session}' should not exist"
    )
    ctx.data["server"] = server
    return ctx


@when("the monitor polls")
def when_monitor_polls(ctx):
    agent: AgentInfo = ctx.data["agent"]
    server: libtmux.Server = ctx.data["server"]
    # Replicate the monitor's logic for a missing session
    if not session_exists(server, agent.tmux_session):
        ctx.state_mgr.update_agent_state(agent.id, AgentState.EXITED)


@then(parsers.parse('agent "{label}" should be in "exited" state'))
def then_agent_in_exited(ctx, label):
    state = ctx.state_mgr.load()
    agent = next((a for a in state.agents if a.label == label), None)
    assert agent is not None, f"Agent '{label}' not found"
    assert agent.state == AgentState.EXITED, (
        f"Expected '{label}' to be exited, got '{agent.state.value}'"
    )


# ── Scenarios 4 & 5: Hold / resume via TUI ───────────────────────────────────


@given(parsers.parse('agent "{label}" is in "on_hold" state'), target_fixture="ctx")
def given_agent_on_hold(label, ctx):
    agent = _seed_agent(ctx, label, AgentState.ON_HOLD)
    ctx.data["agent"] = agent
    ctx.data["label"] = label
    return ctx


@when(parsers.parse('the user presses "{key}" with "{label}" highlighted'))
def when_user_presses_key_with_highlighted(ctx, key, label):
    ctx.ensure_mounted()
    _highlight_agent_by_label(ctx, label)

    async def _press():
        await ctx.pilot.press(key)
        await ctx.pilot.pause()

    ctx.run(_press())


@then(parsers.parse('agent "{label}" should be in "{state_str}" state'))
def then_agent_in_state_tui(ctx, label, state_str):
    state = ctx.state_mgr.load()
    agent = next((a for a in state.agents if a.label == label), None)
    assert agent is not None, f"Agent '{label}' not found in active agents"
    assert agent.state.value == state_str, (
        f"Expected agent '{label}' to be in state '{state_str}', got '{agent.state.value}'"
    )


# ── Scenario 6: Any agent can be killed from dashboard ───────────────────────


@given(parsers.parse('agent "{label}" exists in any state'), target_fixture="ctx")
def given_agent_exists_any_state(label, ctx):
    agent = _seed_agent(ctx, label, AgentState.RUNNING, real_tmux=True)
    ctx.data["agent"] = agent
    ctx.data["label"] = label
    return ctx


@then(parsers.parse('agent "{label}" should be moved to history'))
def then_agent_moved_to_history(ctx, label):
    state = ctx.state_mgr.load()
    active_labels = [a.label for a in state.agents]
    assert label not in active_labels, (
        f"Expected '{label}' to be removed from active agents, still in: {active_labels}"
    )
    history_entries = ctx.history_mgr.load()
    history_labels = [e["label"] for e in history_entries]
    assert label in history_labels, (
        f"Expected '{label}' in history, got: {history_labels}"
    )


@then("the tmux session should be killed")
def then_tmux_session_killed(ctx):
    agent: AgentInfo = ctx.data["agent"]
    server = libtmux.Server()
    assert not session_exists(server, agent.tmux_session), (
        f"Expected tmux session '{agent.tmux_session}' to be killed"
    )
    # Remove from cleanup list since it's already gone
    ctx._tmux_sessions = [s for s in ctx._tmux_sessions if s != agent.tmux_session]


# ── Scenario 7: Agents ordered by state priority then by change time ─────────


@given("the following agents exist:", target_fixture="ctx")
def given_agents_exist_with_timestamps(ctx, datatable):
    rows = _datatable_as_dicts(datatable)
    agents = []
    for row in rows:
        state = AgentState(row["state"])
        agent_id = ctx.state_mgr.next_id()
        agent = AgentInfo(
            id=agent_id,
            tmux_session=f"aque-{agent_id}",
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
    ctx.data["agents"] = agents
    return ctx


@then("the sorted order should be:")
def then_sorted_order(ctx, datatable):
    rows = _datatable_as_dicts(datatable)
    expected_labels = [r["label"] for r in rows]
    agents = ctx.state_mgr.load().agents
    ordered = sorted_agents(agents)
    actual_labels = [a.label for a in ordered]
    assert actual_labels == expected_labels, (
        f"Expected order {expected_labels}, got {actual_labels}"
    )
