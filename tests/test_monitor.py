import time
from unittest.mock import patch, MagicMock

from aque.monitor import IdleDetector, has_children


class TestHasChildren:
    def test_no_children(self):
        with patch("aque.monitor.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout="")
            assert has_children(12345) is False

    def test_has_children(self):
        with patch("aque.monitor.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="12346\n")
            assert has_children(12345) is True

    def test_pgrep_failure_assumes_alive(self):
        with patch("aque.monitor.subprocess.run", side_effect=FileNotFoundError):
            assert has_children(12345) is True


class TestIdleDetector:
    def _static_lines(self):
        return ["output", "❯ ", "───", "  [Opus 4.6]"]

    def _changing_lines(self, tick):
        return [f"· Pollinating… ({tick}s · ↓ 1.0k tokens)"]

    def test_no_children_immediately_idle(self):
        """Agent exited — immediately idle."""
        detector = IdleDetector(idle_timeout=10)
        with patch("aque.monitor.has_children", return_value=False):
            detector.update(1, 12345, self._static_lines())
            assert detector.is_idle(1) is True

    def test_stable_content_becomes_idle(self):
        """Screen unchanged for idle_timeout → idle."""
        detector = IdleDetector(idle_timeout=0.1)
        with patch("aque.monitor.has_children", return_value=True):
            detector.update(1, 12345, self._static_lines())
            assert detector.is_idle(1) is False
            time.sleep(0.15)
            detector.update(1, 12345, self._static_lines())
            assert detector.is_idle(1) is True

    def test_changing_content_never_idle(self):
        """Screen keeps changing (spinner ticking) → never idle."""
        detector = IdleDetector(idle_timeout=0.1)
        with patch("aque.monitor.has_children", return_value=True):
            detector.update(1, 12345, self._changing_lines(1))
            time.sleep(0.05)
            detector.update(1, 12345, self._changing_lines(2))
            time.sleep(0.05)
            detector.update(1, 12345, self._changing_lines(3))
            time.sleep(0.05)
            detector.update(1, 12345, self._changing_lines(4))
            assert detector.is_idle(1) is False

    def test_content_change_resets_timer(self):
        """Content change resets the stability timer."""
        detector = IdleDetector(idle_timeout=0.1)
        with patch("aque.monitor.has_children", return_value=True):
            detector.update(1, 12345, ["v1"])
            time.sleep(0.05)
            detector.update(1, 12345, ["v2"])  # changed — reset
            time.sleep(0.08)
            detector.update(1, 12345, ["v2"])  # same, but only 0.08s
            assert detector.is_idle(1) is False

    def test_remove_agent(self):
        detector = IdleDetector(idle_timeout=10)
        with patch("aque.monitor.has_children", return_value=False):
            detector.update(1, 12345, self._static_lines())
        detector.remove_agent(1)
        assert detector.is_idle(1) is False

    def test_multiple_agents_independent(self):
        detector = IdleDetector(idle_timeout=0.1)
        with patch("aque.monitor.has_children", return_value=True):
            detector.update(1, 12345, self._static_lines())
            detector.update(2, 12346, self._static_lines())
            time.sleep(0.15)
            detector.update(1, 12345, self._static_lines())  # same → idle
            detector.update(2, 12346, self._changing_lines(2))  # changed → not idle
            assert detector.is_idle(1) is True
            assert detector.is_idle(2) is False


class TestMonitorStates:
    def test_on_hold_not_in_active_states(self):
        from aque.monitor import MONITORED_STATES
        from aque.state import AgentState
        assert AgentState.ON_HOLD not in MONITORED_STATES
        assert AgentState.RUNNING in MONITORED_STATES
