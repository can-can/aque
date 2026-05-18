import json
from datetime import datetime, timezone

from aque.state import AgentState, StateManager, AgentInfo


class TestAgentInfo:
    def test_create_agent_info(self):
        agent = AgentInfo(
            id=1,
            tmux_session="aque-1",
            label="claude . my-api",
            dir="/tmp/my-api",
            command=["claude"],
            state=AgentState.RUNNING,
            pid=12345,
        )
        assert agent.id == 1
        assert agent.state == AgentState.RUNNING
        assert agent.tmux_session == "aque-1"

    def test_agent_to_dict_and_back(self):
        agent = AgentInfo(
            id=1,
            tmux_session="aque-1",
            label="claude . my-api",
            dir="/tmp/my-api",
            command=["claude"],
            state=AgentState.RUNNING,
            pid=12345,
        )
        d = agent.to_dict()
        restored = AgentInfo.from_dict(d)
        assert restored.id == agent.id
        assert restored.state == agent.state
        assert restored.label == agent.label

    def test_agent_type_defaults_to_none(self):
        agent = AgentInfo(
            id=1, tmux_session="aque-1", label="test",
            dir="/tmp", command=["claude"], state=AgentState.RUNNING, pid=100,
        )
        assert agent.agent_type is None

    def test_agent_type_set_explicitly(self):
        agent = AgentInfo(
            id=1, tmux_session="aque-1", label="test",
            dir="/tmp", command=["claude"], state=AgentState.RUNNING, pid=100,
            agent_type="claude",
        )
        assert agent.agent_type == "claude"

    def test_agent_type_roundtrips_through_dict(self):
        agent = AgentInfo(
            id=1, tmux_session="aque-1", label="test",
            dir="/tmp", command=["claude"], state=AgentState.RUNNING, pid=100,
            agent_type="claude",
        )
        d = agent.to_dict()
        assert d["agent_type"] == "claude"
        restored = AgentInfo.from_dict(d)
        assert restored.agent_type == "claude"

    def test_agent_type_none_roundtrips_through_dict(self):
        agent = AgentInfo(
            id=1, tmux_session="aque-1", label="test",
            dir="/tmp", command=["claude"], state=AgentState.RUNNING, pid=100,
        )
        d = agent.to_dict()
        assert d["agent_type"] is None
        restored = AgentInfo.from_dict(d)
        assert restored.agent_type is None

    def test_from_dict_handles_missing_agent_type(self):
        """Backward compat: existing state.json entries without agent_type."""
        d = {
            "id": 1, "tmux_session": "aque-1", "label": "test",
            "dir": "/tmp", "command": ["claude"], "state": "running", "pid": 100,
            "created_at": "2026-04-11T00:00:00Z", "last_change_at": "2026-04-11T00:00:00Z",
        }
        agent = AgentInfo.from_dict(d)
        assert agent.agent_type is None

    def test_responder_fields_default(self):
        agent = AgentInfo(
            id=1, tmux_session="aque-1", label="test",
            dir="/tmp", command=["claude"], state=AgentState.RUNNING, pid=100,
        )
        assert agent.is_responder is False
        assert agent.partner_id is None
        assert agent.auto_respond is True
        assert agent.last_nudge_at is None

    def test_responder_fields_set_explicitly(self):
        agent = AgentInfo(
            id=2, tmux_session="aque-2", label="resp(1)",
            dir="/tmp", command=["claude"], state=AgentState.RUNNING, pid=101,
            is_responder=True, partner_id=1,
        )
        assert agent.is_responder is True
        assert agent.partner_id == 1

    def test_responder_fields_roundtrip_through_dict(self):
        agent = AgentInfo(
            id=2, tmux_session="aque-2", label="resp(1)",
            dir="/tmp", command=["claude"], state=AgentState.RUNNING, pid=101,
            is_responder=True, partner_id=1, auto_respond=False,
            last_nudge_at="2026-05-16T10:00:00+00:00",
        )
        d = agent.to_dict()
        restored = AgentInfo.from_dict(d)
        assert restored.is_responder is True
        assert restored.partner_id == 1
        assert restored.auto_respond is False
        assert restored.last_nudge_at == "2026-05-16T10:00:00+00:00"

    def test_from_dict_handles_missing_responder_fields(self):
        """Backward compat: pre-upgrade state.json entries."""
        d = {
            "id": 1, "tmux_session": "aque-1", "label": "test",
            "dir": "/tmp", "command": ["claude"], "state": "running", "pid": 100,
            "created_at": "2026-05-16T10:00:00Z", "last_change_at": "2026-05-16T10:00:00Z",
        }
        agent = AgentInfo.from_dict(d)
        assert agent.is_responder is False
        assert agent.partner_id is None
        assert agent.auto_respond is True
        assert agent.last_nudge_at is None


class TestStateManager:
    def test_load_empty_state(self, tmp_aque_dir):
        mgr = StateManager(tmp_aque_dir)
        state = mgr.load()
        assert state.agents == []
        assert state.monitor_pid is None

    def test_add_agent(self, tmp_aque_dir):
        mgr = StateManager(tmp_aque_dir)
        agent = AgentInfo(
            id=1,
            tmux_session="aque-1",
            label="claude . my-api",
            dir="/tmp/my-api",
            command=["claude"],
            state=AgentState.RUNNING,
            pid=12345,
        )
        mgr.add_agent(agent)
        state = mgr.load()
        assert len(state.agents) == 1
        assert state.agents[0].id == 1

    def test_update_agent_state(self, tmp_aque_dir):
        mgr = StateManager(tmp_aque_dir)
        agent = AgentInfo(
            id=1,
            tmux_session="aque-1",
            label="test",
            dir="/tmp",
            command=["test"],
            state=AgentState.RUNNING,
            pid=100,
        )
        mgr.add_agent(agent)
        mgr.update_agent_state(1, AgentState.WAITING)
        state = mgr.load()
        assert state.agents[0].state == AgentState.WAITING

    def test_remove_agent(self, tmp_aque_dir):
        mgr = StateManager(tmp_aque_dir)
        agent = AgentInfo(
            id=1,
            tmux_session="aque-1",
            label="test",
            dir="/tmp",
            command=["test"],
            state=AgentState.RUNNING,
            pid=100,
        )
        mgr.add_agent(agent)
        mgr.remove_agent(1)
        state = mgr.load()
        assert len(state.agents) == 0

    def test_next_id_increments(self, tmp_aque_dir):
        mgr = StateManager(tmp_aque_dir)
        assert mgr.next_id() == 1
        agent = AgentInfo(
            id=1,
            tmux_session="aque-1",
            label="test",
            dir="/tmp",
            command=["test"],
            state=AgentState.RUNNING,
            pid=100,
        )
        mgr.add_agent(agent)
        assert mgr.next_id() == 2

    def test_update_agent_state_missing_raises_key_error(self, tmp_aque_dir):
        mgr = StateManager(tmp_aque_dir)
        import pytest
        with pytest.raises(KeyError):
            mgr.update_agent_state(999, AgentState.WAITING)

    def test_get_agents_by_state(self, tmp_aque_dir):
        mgr = StateManager(tmp_aque_dir)
        for i, s in enumerate([AgentState.RUNNING, AgentState.WAITING, AgentState.RUNNING], 1):
            mgr.add_agent(AgentInfo(
                id=i, tmux_session=f"aque-{i}", label=f"agent-{i}",
                dir="/tmp", command=["test"], state=s, pid=100 + i,
            ))
        waiting = mgr.get_agents_by_state(AgentState.WAITING)
        assert len(waiting) == 1
        assert waiting[0].id == 2


class TestOnHoldState:
    def test_on_hold_enum_exists(self):
        from aque.state import AgentState
        assert AgentState.ON_HOLD == "on_hold"

    def test_agent_can_transition_to_on_hold(self, tmp_aque_dir):
        from aque.state import AgentState, AgentInfo, StateManager
        mgr = StateManager(tmp_aque_dir)
        mgr.add_agent(AgentInfo(
            id=1, tmux_session="aque-1", label="test",
            dir="/tmp", command=["test"], state=AgentState.RUNNING, pid=100,
        ))
        mgr.update_agent_state(1, AgentState.ON_HOLD)
        state = mgr.load()
        assert state.agents[0].state == AgentState.ON_HOLD

    def test_on_hold_roundtrips_through_json(self, tmp_aque_dir):
        from aque.state import AgentState, AgentInfo, StateManager
        mgr = StateManager(tmp_aque_dir)
        mgr.add_agent(AgentInfo(
            id=1, tmux_session="aque-1", label="test",
            dir="/tmp", command=["test"], state=AgentState.ON_HOLD, pid=100,
        ))
        state = mgr.load()
        assert state.agents[0].state == AgentState.ON_HOLD


class TestDoneAgent:
    def test_done_agent_removes_from_state(self, tmp_aque_dir):
        from aque.state import AgentState, AgentInfo, StateManager
        from aque.history import HistoryManager
        mgr = StateManager(tmp_aque_dir)
        hmgr = HistoryManager(tmp_aque_dir)
        mgr.add_agent(AgentInfo(
            id=1, tmux_session="aque-1", label="test",
            dir="/tmp", command=["test"], state=AgentState.RUNNING, pid=100,
        ))
        mgr.done_agent(1, hmgr)
        state = mgr.load()
        assert len(state.agents) == 0

    def test_done_agent_adds_to_history(self, tmp_aque_dir):
        from aque.state import AgentState, AgentInfo, StateManager
        from aque.history import HistoryManager
        mgr = StateManager(tmp_aque_dir)
        hmgr = HistoryManager(tmp_aque_dir)
        mgr.add_agent(AgentInfo(
            id=1, tmux_session="aque-1", label="test",
            dir="/tmp", command=["test"], state=AgentState.RUNNING, pid=100,
        ))
        mgr.done_agent(1, hmgr)
        entries = hmgr.load()
        assert len(entries) == 1
        assert entries[0]["label"] == "test"

    def test_done_agent_raises_for_missing_id(self, tmp_aque_dir):
        import pytest
        from aque.state import StateManager
        from aque.history import HistoryManager
        mgr = StateManager(tmp_aque_dir)
        hmgr = HistoryManager(tmp_aque_dir)
        with pytest.raises(KeyError):
            mgr.done_agent(999, hmgr)


class TestDoneAgentLeavesResponderToCaller:
    def test_done_agent_does_not_remove_responder_directly(self, tmp_aque_dir):
        """done_agent removes the partner only — responder cleanup is caller-driven."""
        from aque.history import HistoryManager
        mgr = StateManager(tmp_aque_dir)
        hmgr = HistoryManager(tmp_aque_dir)
        mgr.add_agent(AgentInfo(
            id=1, tmux_session="aque-1", label="partner",
            dir="/tmp", command=["claude"], state=AgentState.RUNNING, pid=100,
        ))
        mgr.add_agent(AgentInfo(
            id=2, tmux_session="aque-2", label="resp(1)",
            dir="/tmp", command=["claude"], state=AgentState.RUNNING, pid=101,
            is_responder=True, partner_id=1,
        ))
        mgr.done_agent(1, hmgr)
        state = mgr.load()
        ids = {a.id for a in state.agents}
        assert 1 not in ids
        assert 2 in ids
