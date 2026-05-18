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
