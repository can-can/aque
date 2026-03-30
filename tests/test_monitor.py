import hashlib
import subprocess
import time
from unittest.mock import patch, MagicMock

from aque.monitor import IdleDetector, _last_line_is_prompt, check_process_tree, ProcessTree


class TestLastLineIsPrompt:
    def test_claude_code_prompt(self):
        lines = ["some output", "❯ "]
        assert _last_line_is_prompt(lines) is True

    def test_shell_prompt(self):
        lines = ["some output", "$ "]
        assert _last_line_is_prompt(lines) is True

    def test_python_repl(self):
        lines = ["some output", ">>> "]
        assert _last_line_is_prompt(lines) is True

    def test_prompt_in_middle_not_detected(self):
        """Old false positive: prompt marker buried in output, not last line."""
        lines = ["❯ ", "some output", "more output"]
        assert _last_line_is_prompt(lines) is False

    def test_dollar_in_variable_not_detected(self):
        """$ without trailing space is not a prompt."""
        lines = ["$HOME/path/to/file"]
        assert _last_line_is_prompt(lines) is False

    def test_ellipsis_not_detected(self):
        """... was removed — too many false positives."""
        lines = ["..."]
        assert _last_line_is_prompt(lines) is False

    def test_active_spinner_not_idle(self):
        lines = ["✽ Working… (41s)", "  ⎿  Running…"]
        assert _last_line_is_prompt(lines) is False

    def test_plain_output_not_idle(self):
        lines = ["Line 1", "Line 2", "Line 3"]
        assert _last_line_is_prompt(lines) is False

    def test_empty_lines_skipped(self):
        """Trailing blank lines should be ignored, prompt above them detected."""
        lines = ["some output", "❯ ", "", "", ""]
        assert _last_line_is_prompt(lines) is True

    def test_all_empty_lines(self):
        lines = ["", "", ""]
        assert _last_line_is_prompt(lines) is False

    def test_claude_prompt_with_decoration(self):
        """Claude Code shows ❯ followed by status lines — last non-empty may vary."""
        lines = ["some output", "❯ ", "───────", "  [Opus 4.6]"]
        # Last non-empty line is "  [Opus 4.6]", not the prompt
        assert _last_line_is_prompt(lines) is False


class TestIdleDetector:
    def _idle_lines(self):
        return ["output", "❯ "]

    def _active_lines(self):
        return ["✽ Working… (5s)", "  ⎿  Running…"]

    def test_grandchildren_always_busy(self):
        """Process tree shows grandchildren — never idle regardless of content."""
        detector = IdleDetector(idle_timeout=0.1)
        with patch("aque.monitor.check_process_tree", return_value=ProcessTree.GRANDCHILDREN):
            detector.update(1, 12345, self._idle_lines())
            import time; time.sleep(0.15)
            detector.update(1, 12345, self._idle_lines())
            assert detector.is_idle(1) is False

    def test_no_children_immediately_idle(self):
        """Process tree shows no children — agent exited, immediately idle."""
        detector = IdleDetector(idle_timeout=10)
        with patch("aque.monitor.check_process_tree", return_value=ProcessTree.NO_CHILDREN):
            detector.update(1, 12345, self._idle_lines())
            assert detector.is_idle(1) is True

    def test_children_only_needs_stable_content_and_prompt(self):
        """Ambiguous case: needs content stability + prompt to be idle."""
        detector = IdleDetector(idle_timeout=0.1)
        with patch("aque.monitor.check_process_tree", return_value=ProcessTree.CHILDREN_ONLY):
            detector.update(1, 12345, self._idle_lines())
            assert detector.is_idle(1) is False  # not enough time
            import time; time.sleep(0.15)
            detector.update(1, 12345, self._idle_lines())  # same content
            assert detector.is_idle(1) is True

    def test_changing_content_resets_timer(self):
        """Content changes reset the stability timer even with prompt visible."""
        detector = IdleDetector(idle_timeout=0.1)
        with patch("aque.monitor.check_process_tree", return_value=ProcessTree.CHILDREN_ONLY):
            detector.update(1, 12345, ["output v1", "❯ "])
            import time; time.sleep(0.05)
            detector.update(1, 12345, ["output v2", "❯ "])  # content changed
            time.sleep(0.08)
            detector.update(1, 12345, ["output v2", "❯ "])  # same as last
            assert detector.is_idle(1) is False  # only 0.08s of stability

    def test_no_prompt_not_idle_even_if_stable(self):
        """Stable content but no prompt — not idle."""
        detector = IdleDetector(idle_timeout=0.1)
        with patch("aque.monitor.check_process_tree", return_value=ProcessTree.CHILDREN_ONLY):
            detector.update(1, 12345, self._active_lines())
            import time; time.sleep(0.15)
            detector.update(1, 12345, self._active_lines())
            assert detector.is_idle(1) is False

    def test_grandchildren_resets_prior_idle_state(self):
        """If agent was building toward idle then spawns a subprocess, reset."""
        detector = IdleDetector(idle_timeout=0.1)
        with patch("aque.monitor.check_process_tree", return_value=ProcessTree.CHILDREN_ONLY):
            detector.update(1, 12345, self._idle_lines())
            import time; time.sleep(0.05)
        with patch("aque.monitor.check_process_tree", return_value=ProcessTree.GRANDCHILDREN):
            detector.update(1, 12345, self._idle_lines())
        with patch("aque.monitor.check_process_tree", return_value=ProcessTree.CHILDREN_ONLY):
            import time; time.sleep(0.08)
            detector.update(1, 12345, self._idle_lines())
            assert detector.is_idle(1) is False  # timer was reset

    def test_remove_agent(self):
        detector = IdleDetector(idle_timeout=10)
        with patch("aque.monitor.check_process_tree", return_value=ProcessTree.NO_CHILDREN):
            detector.update(1, 12345, self._idle_lines())
        detector.remove_agent(1)
        assert detector.is_idle(1) is False

    def test_multiple_agents_independent(self):
        detector = IdleDetector(idle_timeout=0.1)
        with patch("aque.monitor.check_process_tree", return_value=ProcessTree.CHILDREN_ONLY):
            detector.update(1, 12345, self._idle_lines())
            detector.update(2, 12346, self._idle_lines())
            import time; time.sleep(0.15)
            detector.update(1, 12345, self._idle_lines())
            detector.update(2, 12346, self._active_lines())  # agent 2 changed content + no prompt
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


class TestMonitorStates:
    def test_on_hold_not_in_active_states(self):
        from aque.monitor import MONITORED_STATES
        from aque.state import AgentState
        assert AgentState.ON_HOLD not in MONITORED_STATES
        assert AgentState.RUNNING in MONITORED_STATES
