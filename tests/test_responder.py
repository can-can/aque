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
