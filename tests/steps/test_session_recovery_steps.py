"""BDD steps for the session-recovery feature.

Tests the orphan-reconciliation logic at the state-management level
(find_orphans + OrphanModal handle_action -> StateManager) without
spinning up the full Textual app.
"""

import pytest
from pytest_bdd import given, when, then, scenarios, parsers

from aque.orphans import find_orphans
from aque.state import AgentInfo, AgentState, StateManager
from aque.widgets.orphan_modal import OrphanModal

scenarios("../../features/session_recovery.feature")


class FakeServer:
    @property
    def sessions(self):
        class L:
            def get(self, session_name=None, default=None):
                return default
        return L()


@pytest.fixture
def ctx(tmp_aque_dir):
    return {
        "aque_dir": tmp_aque_dir,
        "state_mgr": StateManager(tmp_aque_dir),
        "modal": None,
        "actions_log": [],
    }


@given("an aque state file with a claude agent whose tmux session is gone")
def claude_orphan(ctx):
    ctx["state_mgr"].add_agent(AgentInfo(
        id=1, tmux_session="aque-1", label="x", dir="/tmp",
        command=["claude"], state=AgentState.RUNNING, pid=1,
        agent_type="claude",
    ))


@given("the claude agent has a captured session_id")
def claude_has_session(ctx):
    ctx["state_mgr"].set_session_id(1, "uuid-1")


@given("an additional claude agent with no captured session_id")
def claude_no_session(ctx):
    ctx["state_mgr"].add_agent(AgentInfo(
        id=2, tmux_session="aque-2", label="y", dir="/tmp",
        command=["claude"], state=AgentState.RUNNING, pid=2,
        agent_type="claude",
    ))


def _apply_action(ctx, action: str, agent_id: int) -> None:
    mgr: StateManager = ctx["state_mgr"]
    if action == "forget":
        mgr.remove_agent(agent_id)
    elif action == "mark_exited":
        mgr.update_agent_state(agent_id, AgentState.EXITED)


@when("I open aque desk")
def open_desk(ctx):
    state = ctx["state_mgr"].load()
    orphans = find_orphans(state, FakeServer())
    ctx["orphans"] = orphans

    def _on_action(action: str, agent_id: int) -> None:
        ctx["actions_log"].append((action, agent_id))
        _apply_action(ctx, action, agent_id)

    modal = OrphanModal(orphans, on_action=_on_action)
    # Patch dismiss so the modal doesn't try to call self.app.pop_screen()
    # outside a running Textual app — we're testing state-management logic only.
    modal.dismiss = lambda *_: None  # type: ignore[method-assign]
    ctx["modal"] = modal


@when("I click Forget on the orphan")
def click_forget(ctx):
    ctx["modal"].handle_action("forget", 1)


@when(parsers.parse('I click "Mark exited" on the orphan'))
def click_mark_exited(ctx):
    ctx["modal"].handle_action("mark_exited", 1)


@then("the orphan modal is shown")
def modal_shown(ctx):
    assert ctx["modal"] is not None
    assert ctx["modal"].remaining_orphans()


@then("it lists the orphaned claude agent")
def lists_claude(ctx):
    ids = [o.agent.id for o in ctx["modal"].remaining_orphans()]
    assert 1 in ids


@then("the orphan is removed from state.json")
def orphan_removed(ctx):
    agents = ctx["state_mgr"].load().agents
    assert all(a.id != 1 for a in agents)


@then("the agent's state is EXITED")
def state_exited(ctx):
    a = next(a for a in ctx["state_mgr"].load().agents if a.id == 1)
    assert a.state == AgentState.EXITED


@then("the agent remains in state.json")
def agent_remains(ctx):
    ids = [a.id for a in ctx["state_mgr"].load().agents]
    assert 1 in ids


@then("the Resume button is disabled for that agent")
def resume_disabled(ctx):
    # Find the orphan for id=2 (no session_id) and check resumable flag
    orphans = ctx["modal"].remaining_orphans()
    no_session = next(o for o in orphans if o.agent.id == 2)
    assert no_session.resumable is False
