"""BDD tests for auto_attach.feature — triage pill for waiting agents.

The forced-modal countdown was replaced with a non-blocking ``TriagePill``
that mounts inside the dashboard layout. Tests assert on the pill's
presence, its label content, and the side effects of the three actions
(Enter/Space/s + Esc as snooze synonym).
"""
import asyncio
from unittest.mock import patch

import pytest
from pytest_bdd import scenario, given, when, then, parsers

from aque.desk import DeskApp
from aque.history import HistoryManager
from aque.state import AgentInfo, AgentState, StateManager


FEATURE = "../../features/auto_attach.feature"


# ── Scenario declarations ──────────────────────────────────────────────


@scenario(FEATURE, "Triage pill appears when returning to dashboard with a waiting agent")
def test_pill_appears_on_return():
    pass


@scenario(FEATURE, "Triage pill appears when an agent transitions to waiting on the dashboard")
def test_pill_appears_on_transition():
    pass


@scenario(FEATURE, "No triage pill when there are no waiting agents")
def test_no_pill_without_waiting():
    pass


@scenario(FEATURE, "Pressing Enter attaches to the triaged agent")
def test_enter_attaches():
    pass


@scenario(FEATURE, "Pressing Space peeks the triaged agent without attaching")
def test_space_peeks():
    pass


@scenario(FEATURE, 'Pressing "s" snoozes the triaged agent')
def test_s_snoozes():
    pass


@scenario(FEATURE, "Pressing Escape snoozes the triaged agent")
def test_escape_snoozes():
    pass


@scenario(FEATURE, "Triage targets the top-priority waiting agent")
def test_pill_targets_top_priority():
    pass


@scenario(FEATURE, "Triage does not trigger when skip_attach is set")
def test_no_pill_when_skip_attach():
    pass


@scenario(FEATURE, "Snooze decays when the agent transitions to waiting again")
def test_snooze_decays():
    pass


@scenario(FEATURE, "Pill shows the queue length when more than one agent is waiting")
def test_pill_queue_indicator():
    pass


# ── Context ────────────────────────────────────────────────────────────


class Ctx:
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
        return self._get_loop().run_until_complete(coro)

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

    def pill_present(self) -> bool:
        if self.app is None:
            return False
        return bool(self.app.query("#triage-pill"))

    def pill_text(self) -> str:
        from textual.widgets import Static
        try:
            pill = self.app.query_one("#triage-pill")
        except Exception:
            return ""
        parts: list[str] = []
        for w in pill.query(Static):
            rendered = w.render()
            try:
                # Rich renderable → plain text via Console capture.
                from rich.console import Console
                console = Console(width=80, file=open("/dev/null", "w"), record=True)
                console.print(rendered, end="")
                parts.append(console.export_text())
            except Exception:
                parts.append(str(rendered))
        return " | ".join(parts)


@pytest.fixture
def ctx(tmp_aque_dir, request):
    # Default skip_attach=False so the triage flow can run.
    c = Ctx(tmp_aque_dir, skip_attach=False)
    request.addfinalizer(c.cleanup)
    return c


def _datatable_as_dicts(datatable):
    if not datatable:
        return []
    headers = datatable[0]
    return [dict(zip(headers, row)) for row in datatable[1:]]


# ── Background ─────────────────────────────────────────────────────────


@given("the aque desk is open", target_fixture="ctx")
def given_desk_is_open(ctx):
    return ctx


# ── Givens ─────────────────────────────────────────────────────────────


@given(parsers.parse('agent "{label}" is in "{state_str}" state'))
def given_agent_in_state(ctx, label, state_str):
    agent_id = ctx.state_mgr.next_id()
    ctx.state_mgr.add_agent(AgentInfo(
        id=agent_id,
        tmux_session=f"aque-test-{agent_id}",
        label=label,
        dir="/tmp/test",
        command=["test"],
        state=AgentState(state_str),
        pid=10000 + agent_id,
    ))


@given(parsers.parse('all agents are in "{state_str}" state'))
def given_all_agents_in_state(ctx, state_str):
    for label in ("agent-a", "agent-b"):
        agent_id = ctx.state_mgr.next_id()
        ctx.state_mgr.add_agent(AgentInfo(
            id=agent_id,
            tmux_session=f"aque-test-{agent_id}",
            label=label,
            dir="/tmp/test",
            command=["test"],
            state=AgentState(state_str),
            pid=10000 + agent_id,
        ))


@given(parsers.parse("the desk is opened with skip_attach=True"))
def given_desk_opened_with_skip_attach(ctx):
    ctx._skip_attach = True


@given("the following agents exist:", target_fixture="agents_created")
def given_agents_exist_table(ctx, datatable):
    rows = _datatable_as_dicts(datatable)
    out = []
    for row in rows:
        agent_id = ctx.state_mgr.next_id()
        agent = AgentInfo(
            id=agent_id,
            tmux_session=f"aque-test-{agent_id}",
            label=row["label"],
            dir="/tmp/test",
            command=["test"],
            state=AgentState(row["state"]),
            pid=10000 + agent_id,
        )
        if "last_change_at" in row:
            agent.last_change_at = row["last_change_at"]
        ctx.state_mgr.add_agent(agent)
        out.append(agent)
    return out


@given(parsers.parse('the triage pill is showing for agent "{label}"'))
def given_triage_pill_showing(ctx, label):
    # Seed waiting agent, mount, and trigger the pill.
    agent_id = ctx.state_mgr.next_id()
    ctx.state_mgr.add_agent(AgentInfo(
        id=agent_id,
        tmux_session=f"aque-test-{agent_id}",
        label=label,
        dir="/tmp/test",
        command=["test"],
        state=AgentState.WAITING,
        pid=10000 + agent_id,
    ))
    ctx.ensure_mounted()

    async def _trigger():
        ctx.app._show_dashboard()
        await ctx.pilot.pause()

    ctx.run(_trigger())
    assert ctx.pill_present(), "Pill failed to appear in setup"


@given("the user is on the dashboard")
def given_user_on_dashboard(ctx):
    ctx.ensure_mounted()


# ── Whens ──────────────────────────────────────────────────────────────


@when("the user returns to the dashboard")
def when_user_returns_to_dashboard(ctx):
    ctx.ensure_mounted()

    async def _return():
        ctx.app._show_dashboard()
        await ctx.pilot.pause()

    ctx.run(_return())


@when("the periodic refresh runs")
@then("the periodic refresh runs")
def periodic_refresh_runs(ctx):
    ctx.ensure_mounted()

    async def _refresh():
        ctx.app._on_refresh()
        await ctx.pilot.pause()

    ctx.run(_refresh())


@when(parsers.parse('the monitor changes agent "{label}" to "{state_str}"'))
def when_monitor_changes_state(ctx, label, state_str):
    state = ctx.state_mgr.load()
    agent = next((a for a in state.agents if a.label == label), None)
    assert agent is not None, f"Agent '{label}' not found"
    ctx.state_mgr.update_agent_state(agent.id, AgentState(state_str))


@when("the user presses Enter")
def when_user_presses_enter(ctx):
    # Mock _attach_to_agent to avoid real tmux interaction.
    def _mock_attach(agent):
        ctx.attached_agent_label = agent.label
        ctx.app._dismiss_triage_widget()
        ctx.app._triage_agent = None

    ctx.app._attach_to_agent = _mock_attach

    async def _press():
        await ctx.pilot.press("enter")
        await ctx.pilot.pause()

    ctx.run(_press())


@when("the user presses Space")
def when_user_presses_space(ctx):
    async def _press():
        await ctx.pilot.press("space")
        await ctx.pilot.pause()

    ctx.run(_press())


@when("the user presses Escape")
def when_user_presses_escape(ctx):
    async def _press():
        await ctx.pilot.press("escape")
        await ctx.pilot.pause()

    ctx.run(_press())


@when(parsers.parse('the user presses "{key}"'))
def when_user_presses_key(ctx, key):
    async def _press():
        await ctx.pilot.press(key)
        await ctx.pilot.pause()

    ctx.run(_press())


# ── Thens ──────────────────────────────────────────────────────────────


@then("a triage pill should appear")
def then_triage_pill_appears(ctx):
    assert ctx.pill_present(), "Expected TriagePill to be mounted, but it is not"


@then("no triage pill should appear")
def then_no_triage_pill(ctx):
    ctx.ensure_mounted()
    assert not ctx.pill_present(), (
        "Expected no TriagePill to be present, but one is mounted"
    )


@then(parsers.parse('the triage pill should mention "{label}"'))
def then_pill_mentions(ctx, label):
    assert ctx.pill_present(), "Pill not present"
    text = ctx.pill_text()
    assert label in text, f"Expected '{label}' in pill content, got: {text!r}"


@then("the triage pill should be dismissed")
def then_pill_dismissed(ctx):
    assert not ctx.pill_present(), "Expected pill to be dismissed, but it is still mounted"


@then(parsers.parse('agent "{label}" should still be in "{state_str}" state'))
def then_agent_still_in_state(ctx, label, state_str):
    state = ctx.state_mgr.load()
    agent = next((a for a in state.agents if a.label == label), None)
    assert agent is not None, f"Agent '{label}' not found"
    assert agent.state.value == state_str, (
        f"Expected agent '{label}' in '{state_str}', got '{agent.state.value}'"
    )


@then(parsers.parse('the user should be attached to agent "{label}"'))
def then_attached_to_agent(ctx, label):
    assert getattr(ctx, "attached_agent_label", None) == label, (
        f"Expected attach to '{label}', got '{getattr(ctx, 'attached_agent_label', None)}'"
    )


@then(parsers.parse('the highlighted agent should be "{label}"'))
def then_highlighted_agent(ctx, label):
    from textual.widgets import OptionList
    ol = ctx.app.query_one("#agent-option-list", OptionList)
    assert ol.highlighted is not None, "No agent highlighted"
    opt = ol.get_option_at_index(ol.highlighted)
    assert label in str(opt.prompt), (
        f"Expected '{label}' highlighted, got: {str(opt.prompt)}"
    )
