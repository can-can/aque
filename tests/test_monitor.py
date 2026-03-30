import subprocess
import time
from unittest.mock import patch, MagicMock

from aque.monitor import IdleDetector, _looks_idle, check_process_tree, ProcessTree


class TestLooksIdle:
    def test_claude_code_prompt(self):
        lines = ["some output", "❯ ", "───────", "  [Opus 4.6]"]
        assert _looks_idle(lines) is True

    def test_shell_prompt(self):
        lines = ["some output", "$ "]
        assert _looks_idle(lines) is True

    def test_python_repl(self):
        lines = ["some output", ">>> "]
        assert _looks_idle(lines) is True

    def test_active_spinner_not_idle(self):
        lines = ["✽ Working… (41s)", "  ⎿  Running…"]
        assert _looks_idle(lines) is False

    def test_plain_output_not_idle(self):
        lines = ["Line 1", "Line 2", "Line 3"]
        assert _looks_idle(lines) is False

    def test_empty_lines_not_idle(self):
        lines = ["", "", ""]
        assert _looks_idle(lines) is False


class TestIdleDetector:
    def _idle_lines(self):
        return ["output", "❯ "]

    def _active_lines(self):
        return ["✽ Working… (5s)", "  ⎿  Running…"]

    def test_new_agent_is_not_idle(self):
        detector = IdleDetector(idle_timeout=5)
        detector.update(1, self._idle_lines())
        assert detector.is_idle(1) is False

    def test_idle_after_timeout(self):
        detector = IdleDetector(idle_timeout=0.1)
        detector.update(1, self._idle_lines())
        time.sleep(0.15)
        assert detector.is_idle(1) is True

    def test_active_content_resets_idle_timer(self):
        detector = IdleDetector(idle_timeout=0.1)
        detector.update(1, self._idle_lines())
        time.sleep(0.05)
        detector.update(1, self._active_lines())
        time.sleep(0.1)
        assert detector.is_idle(1) is False

    def test_remove_agent(self):
        detector = IdleDetector(idle_timeout=5)
        detector.update(1, self._idle_lines())
        detector.remove_agent(1)
        assert detector.is_idle(1) is False

    def test_multiple_agents_independent(self):
        detector = IdleDetector(idle_timeout=0.1)
        detector.update(1, self._idle_lines())
        detector.update(2, self._idle_lines())
        time.sleep(0.15)
        # Agent 1 still idle, agent 2 becomes active
        detector.update(2, self._active_lines())
        assert detector.is_idle(1) is True
        assert detector.is_idle(2) is False


class TestCheckProcessTree:
    def test_no_children_returns_no_children(self):
        """Shell PID has no child processes — agent exited."""
        with patch("aque.monitor.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            result = check_process_tree(12345)
            assert result == ProcessTree.NO_CHILDREN

    def test_children_no_grandchildren_returns_children_only(self):
        """Shell has one child (the agent), agent has no children."""
        with patch("aque.monitor.subprocess.run") as mock_run:
            def side_effect(cmd, **kwargs):
                pid = cmd[-1]
                if pid == "12345":
                    # shell has one child: agent PID 12346
                    return MagicMock(returncode=0, stdout="12346\n")
                else:
                    # agent has no children
                    return MagicMock(returncode=1, stdout="")
            mock_run.side_effect = side_effect
            result = check_process_tree(12345)
            assert result == ProcessTree.CHILDREN_ONLY

    def test_grandchildren_returns_grandchildren(self):
        """Shell → agent → subprocess (e.g., npm)."""
        with patch("aque.monitor.subprocess.run") as mock_run:
            def side_effect(cmd, **kwargs):
                pid = cmd[-1]
                if pid == "12345":
                    return MagicMock(returncode=0, stdout="12346\n")
                elif pid == "12346":
                    return MagicMock(returncode=0, stdout="12347\n")
                else:
                    return MagicMock(returncode=1, stdout="")
            mock_run.side_effect = side_effect
            result = check_process_tree(12345)
            assert result == ProcessTree.GRANDCHILDREN

    def test_multiple_children_any_grandchild_returns_grandchildren(self):
        """Shell → multiple agents, one has a grandchild."""
        with patch("aque.monitor.subprocess.run") as mock_run:
            def side_effect(cmd, **kwargs):
                pid = cmd[-1]
                if pid == "12345":
                    return MagicMock(returncode=0, stdout="12346\n12347\n")
                elif pid == "12346":
                    return MagicMock(returncode=1, stdout="")
                elif pid == "12347":
                    return MagicMock(returncode=0, stdout="12348\n")
                else:
                    return MagicMock(returncode=1, stdout="")
            mock_run.side_effect = side_effect
            result = check_process_tree(12345)
            assert result == ProcessTree.GRANDCHILDREN

    def test_pgrep_failure_returns_children_only(self):
        """If pgrep raises an exception, treat as ambiguous."""
        with patch("aque.monitor.subprocess.run", side_effect=FileNotFoundError):
            result = check_process_tree(12345)
            assert result == ProcessTree.CHILDREN_ONLY


class TestMonitorSkipsOnHold:
    def test_on_hold_not_in_active_states(self):
        from aque.monitor import MONITORED_STATES
        from aque.state import AgentState
        assert AgentState.ON_HOLD not in MONITORED_STATES
        assert AgentState.RUNNING in MONITORED_STATES
