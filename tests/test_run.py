from pathlib import Path
from unittest.mock import MagicMock, patch

from aque.run import launch_agent
from aque.state import AgentState, StateManager


class TestLaunchAgent:
    @patch("aque.run.libtmux.Server")
    def test_launch_creates_session_and_registers_agent(self, mock_server_cls, tmp_aque_dir):
        mock_server = MagicMock()
        mock_server_cls.return_value = mock_server
        mock_session = MagicMock()
        mock_session.name = "aque-1"
        mock_pane = MagicMock()
        mock_pane.pane_pid = "99999"
        mock_session.active_pane = mock_pane
        mock_server.new_session.return_value = mock_session

        mgr = StateManager(tmp_aque_dir)
        agent_id = launch_agent(
            command=["claude", "--model", "opus"],
            working_dir="/tmp/my-api",
            label="auth fix",
            state_manager=mgr,
        )

        assert agent_id == 1
        mock_server.new_session.assert_called_once()
        state = mgr.load()
        assert len(state.agents) == 1
        assert state.agents[0].label == "auth fix"
        assert state.agents[0].state == AgentState.RUNNING
        assert state.agents[0].dir == "/tmp/my-api"
        assert state.agents[0].command == ["claude", "--model", "opus"]

    @patch("aque.run.libtmux.Server")
    def test_launch_default_label(self, mock_server_cls, tmp_aque_dir):
        mock_server = MagicMock()
        mock_server_cls.return_value = mock_server
        mock_session = MagicMock()
        mock_session.name = "aque-1"
        mock_pane = MagicMock()
        mock_pane.pane_pid = "99999"
        mock_session.active_pane = mock_pane
        mock_server.new_session.return_value = mock_session

        mgr = StateManager(tmp_aque_dir)
        launch_agent(
            command=["claude"],
            working_dir="/tmp/my-api",
            label=None,
            state_manager=mgr,
        )

        state = mgr.load()
        assert state.agents[0].label == "claude . my-api"
