import time
from aque.monitor import IdleDetector, _looks_idle


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


class TestMonitorSkipsOnHold:
    def test_on_hold_not_in_active_states(self):
        from aque.monitor import MONITORED_STATES
        from aque.state import AgentState
        assert AgentState.ON_HOLD not in MONITORED_STATES
        assert AgentState.RUNNING in MONITORED_STATES
