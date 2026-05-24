from aque.orphans import OrphanedAgent, find_orphans
from aque.state import AgentInfo, AgentState, AppState


class FakeServer:
    """Stand-in for libtmux.Server. `sessions.get` is what monitor.session_exists calls."""

    def __init__(self, live_session_names: set[str]):
        self._live = live_session_names

    @property
    def sessions(self):
        live = self._live

        class _Lookup:
            def get(self, session_name=None, default=None):
                if session_name in live:
                    return object()  # truthy
                return default

        return _Lookup()


def _agent(**kw) -> AgentInfo:
    base = dict(
        id=kw["id"], tmux_session=kw.get("tmux_session", f"aque-{kw['id']}"),
        label=f"label-{kw['id']}", dir="/tmp", command=["claude"],
        state=kw.get("state", AgentState.RUNNING), pid=1,
        agent_type=kw.get("agent_type"),
        session_id=kw.get("session_id"),
        is_responder=kw.get("is_responder", False),
        partner_id=kw.get("partner_id"),
    )
    return AgentInfo(**base)


def test_find_orphans_returns_only_agents_with_missing_sessions():
    agents = [
        _agent(id=1, tmux_session="aque-1"),  # live
        _agent(id=2, tmux_session="aque-2"),  # orphan
    ]
    state = AppState(agents=agents)
    server = FakeServer({"aque-1"})

    orphans = find_orphans(state, server)
    assert [o.agent.id for o in orphans] == [2]


def test_find_orphans_skips_done_agents():
    agents = [_agent(id=1, state=AgentState.DONE)]
    state = AppState(agents=agents)
    server = FakeServer(set())

    assert find_orphans(state, server) == []


def test_find_orphans_skips_responders():
    """Responders are bootstrapped from their partner; user shouldn't see them
    in the orphan modal directly."""
    agents = [_agent(id=1, is_responder=True, partner_id=2)]
    state = AppState(agents=agents)
    server = FakeServer(set())

    assert find_orphans(state, server) == []


def test_find_orphans_marks_resumable_when_capturer_and_session_id_present():
    agents = [
        _agent(id=1, agent_type="claude", session_id="uuid-1"),
        _agent(id=2, agent_type="claude", session_id=None),
        _agent(id=3, agent_type="unknown-type",  session_id="ignored"),
        _agent(id=4, agent_type=None,     session_id=None),
    ]
    state = AppState(agents=agents)
    server = FakeServer(set())

    orphans = {o.agent.id: o.resumable for o in find_orphans(state, server)}
    assert orphans == {1: True, 2: False, 3: False, 4: False}


def test_orphaned_agent_is_dataclass_with_agent_and_resumable():
    o = OrphanedAgent(agent=_agent(id=1), resumable=False)
    assert o.agent.id == 1
    assert o.resumable is False
