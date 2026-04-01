# tests/test_integration.py
import time
from unittest.mock import MagicMock, patch

from aque.history import HistoryManager
from aque.monitor import IdleDetector
from aque.run import launch_agent
from aque.state import AgentState, StateManager


class TestFullLifecycleV2:
    @patch("aque.run._wait_for_shell")
    @patch("aque.run.libtmux.Server")
    def test_launch_idle_review_done_to_history(self, mock_server_cls, mock_wait, tmp_aque_dir):
        mock_server = MagicMock()
        mock_server_cls.return_value = mock_server
        mock_session = MagicMock()
        mock_session.name = "aque-1"
        mock_pane = MagicMock()
        mock_pane.pane_pid = "99999"
        mock_session.active_pane = mock_pane
        mock_server.new_session.return_value = mock_session

        mgr = StateManager(tmp_aque_dir)
        hmgr = HistoryManager(tmp_aque_dir)

        # 1. Launch
        agent_id = launch_agent(
            command=["claude"], working_dir="/tmp/test",
            label="test agent", state_manager=mgr,
        )
        assert mgr.load().agents[0].state == AgentState.RUNNING

        # 2. Idle detection (no children → agent exited → immediately idle)
        detector = IdleDetector(idle_timeout=0.1)
        idle_lines = ["some output", "❯ "]
        with patch("aque.monitor.has_children", return_value=False):
            detector.update(1, 99999, idle_lines)
        assert detector.is_idle(1) is True

        # 3. Monitor marks waiting
        mgr.update_agent_state(1, AgentState.WAITING)
        assert mgr.load().agents[0].state == AgentState.WAITING

        # 4. User attaches
        mgr.update_agent_state(1, AgentState.FOCUSED)
        assert mgr.load().agents[0].state == AgentState.FOCUSED

        # 5. User dismisses
        mgr.update_agent_state(1, AgentState.RUNNING)
        assert mgr.load().agents[0].state == AgentState.RUNNING

        # 6. User marks done → moves to history
        mgr.done_agent(1, hmgr)
        assert len(mgr.load().agents) == 0
        assert hmgr.count() == 1
        assert hmgr.load()[0]["label"] == "test agent"

    @patch("aque.run._wait_for_shell")
    @patch("aque.run.libtmux.Server")
    def test_on_hold_lifecycle(self, mock_server_cls, mock_wait, tmp_aque_dir):
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
            command=["claude"], working_dir="/tmp/test",
            label="hold test", state_manager=mgr,
        )

        # Put on hold
        mgr.update_agent_state(1, AgentState.ON_HOLD)
        assert mgr.load().agents[0].state == AgentState.ON_HOLD

        # Resume
        mgr.update_agent_state(1, AgentState.RUNNING)
        assert mgr.load().agents[0].state == AgentState.RUNNING
