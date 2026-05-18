"""Tests for the auto-responder module."""
from unittest.mock import MagicMock, patch

import pytest

from aque.state import AgentInfo, AgentState, StateManager


class TestSystemPrompt:
    def test_includes_partner_session_and_id(self):
        from aque.responder import system_prompt

        partner = AgentInfo(
            id=7, tmux_session="aque-foo-7", label="foo",
            dir="/tmp", command=["claude"], state=AgentState.RUNNING, pid=100,
        )
        text = system_prompt(partner)
        assert "aque-foo-7" in text
        assert "id 7" in text or "id=7" in text

    def test_mentions_tmux_tools(self):
        from aque.responder import system_prompt

        partner = AgentInfo(
            id=1, tmux_session="aque-foo-1", label="foo",
            dir="/tmp", command=["claude"], state=AgentState.RUNNING, pid=100,
        )
        text = system_prompt(partner)
        assert "tmux capture-pane" in text
        assert "tmux send-keys" in text


class TestFindFor:
    def test_returns_responder_when_paired(self, tmp_aque_dir):
        from aque.responder import find_for

        mgr = StateManager(tmp_aque_dir)
        mgr.add_agent(AgentInfo(
            id=1, tmux_session="aque-1", label="partner",
            dir="/tmp", command=["claude"], state=AgentState.RUNNING, pid=100,
        ))
        mgr.add_agent(AgentInfo(
            id=2, tmux_session="aque-2", label="resp(1)",
            dir="/tmp", command=["claude"], state=AgentState.RUNNING, pid=101,
            is_responder=True, partner_id=1,
        ))
        state = mgr.load()
        responder = find_for(1, state.agents)
        assert responder is not None
        assert responder.id == 2

    def test_returns_none_when_no_pair(self, tmp_aque_dir):
        from aque.responder import find_for

        mgr = StateManager(tmp_aque_dir)
        mgr.add_agent(AgentInfo(
            id=1, tmux_session="aque-1", label="solo",
            dir="/tmp", command=["claude"], state=AgentState.RUNNING, pid=100,
        ))
        state = mgr.load()
        assert find_for(1, state.agents) is None


class TestCreateFor:
    @patch("aque.responder.launch_agent")
    def test_create_for_spawns_responder_record(self, mock_launch, tmp_aque_dir):
        from aque.responder import create_for

        mgr = StateManager(tmp_aque_dir)
        partner = AgentInfo(
            id=1, tmux_session="aque-foo-1", label="foo",
            dir="/tmp/partner", command=["claude"], state=AgentState.RUNNING, pid=100,
        )
        mgr.add_agent(partner)

        # launch_agent is mocked; simulate it adding the responder record itself
        def fake_launch(command, working_dir, label, state_manager, **kw):
            new_id = state_manager.next_id()
            state_manager.add_agent(AgentInfo(
                id=new_id, tmux_session=f"aque-resp-1-{new_id}", label=label,
                dir=working_dir, command=command, state=AgentState.RUNNING, pid=200,
                is_responder=True, partner_id=partner.id,
            ))
            return new_id
        mock_launch.side_effect = fake_launch

        config = {
            "responder_command": ["claude", "--model", "haiku"],
            "responder_dir": None,
            "session_prefix": "aque",
        }
        responder_id = create_for(partner, config, mgr, aque_dir=tmp_aque_dir)

        assert responder_id == 2
        call_kwargs = mock_launch.call_args.kwargs
        assert call_kwargs["command"] == ["claude", "--model", "haiku"]
        assert call_kwargs["working_dir"] == str(tmp_aque_dir / "responders" / "1")
        assert call_kwargs["label"] == "resp(1)"

        state = mgr.load()
        responder = next(a for a in state.agents if a.id == responder_id)
        assert responder.is_responder is True
        assert responder.partner_id == 1

    @patch("aque.responder.launch_agent")
    def test_create_for_uses_explicit_responder_dir(self, mock_launch, tmp_aque_dir):
        from aque.responder import create_for

        mgr = StateManager(tmp_aque_dir)
        partner = AgentInfo(
            id=1, tmux_session="aque-foo-1", label="foo",
            dir="/tmp", command=["claude"], state=AgentState.RUNNING, pid=100,
        )
        mgr.add_agent(partner)

        def fake_launch(command, working_dir, label, state_manager, **kw):
            new_id = state_manager.next_id()
            state_manager.add_agent(AgentInfo(
                id=new_id, tmux_session=f"resp-{new_id}", label=label,
                dir=working_dir, command=command, state=AgentState.RUNNING, pid=200,
                is_responder=True, partner_id=partner.id,
            ))
            return new_id
        mock_launch.side_effect = fake_launch

        config = {
            "responder_command": ["claude"],
            "responder_dir": "/custom/responder/dir",
            "session_prefix": "aque",
        }
        create_for(partner, config, mgr, aque_dir=tmp_aque_dir)
        assert mock_launch.call_args.kwargs["working_dir"] == "/custom/responder/dir"

    @patch("aque.responder.launch_agent")
    def test_create_for_creates_working_dir(self, mock_launch, tmp_aque_dir):
        from aque.responder import create_for

        mgr = StateManager(tmp_aque_dir)
        partner = AgentInfo(
            id=1, tmux_session="aque-foo-1", label="foo",
            dir="/tmp", command=["claude"], state=AgentState.RUNNING, pid=100,
        )
        mgr.add_agent(partner)

        def fake_launch(command, working_dir, label, state_manager, **kw):
            new_id = state_manager.next_id()
            state_manager.add_agent(AgentInfo(
                id=new_id, tmux_session=f"resp-{new_id}", label=label,
                dir=working_dir, command=command, state=AgentState.RUNNING, pid=200,
                is_responder=True, partner_id=partner.id,
            ))
            return new_id
        mock_launch.side_effect = fake_launch

        config = {"responder_command": ["claude"], "responder_dir": None, "session_prefix": "aque"}
        create_for(partner, config, mgr, aque_dir=tmp_aque_dir)

        expected = tmp_aque_dir / "responders" / "1"
        assert expected.is_dir()
