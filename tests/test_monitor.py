import json
import os
import time
from pathlib import Path

from aque.monitor import IdleDetector, check_signal_files, cleanup_stale_signals


class TestIdleDetector:
    def _static_lines(self):
        return ["output", "❯ ", "───", "  [Opus 4.6]"]

    def _changing_lines(self, tick):
        return [f"· Pollinating… ({tick}s · ↓ 1.0k tokens)"]

    def test_stable_content_becomes_idle(self):
        """Screen unchanged for idle_timeout → idle."""
        detector = IdleDetector(idle_timeout=0.1)
        detector.update(1, self._static_lines())
        assert detector.is_idle(1) is False
        time.sleep(0.15)
        detector.update(1, self._static_lines())
        assert detector.is_idle(1) is True

    def test_changing_content_never_idle(self):
        """Screen keeps changing (spinner ticking) → never idle."""
        detector = IdleDetector(idle_timeout=0.1)
        detector.update(1, self._changing_lines(1))
        time.sleep(0.05)
        detector.update(1, self._changing_lines(2))
        time.sleep(0.05)
        detector.update(1, self._changing_lines(3))
        time.sleep(0.05)
        detector.update(1, self._changing_lines(4))
        assert detector.is_idle(1) is False

    def test_content_change_resets_timer(self):
        """Content change resets the stability timer."""
        detector = IdleDetector(idle_timeout=0.1)
        detector.update(1, ["v1"])
        time.sleep(0.05)
        detector.update(1, ["v2"])  # changed — reset
        time.sleep(0.08)
        detector.update(1, ["v2"])  # same, but only 0.08s
        assert detector.is_idle(1) is False

    def test_remove_agent(self):
        detector = IdleDetector(idle_timeout=0.1)
        detector.update(1, self._static_lines())
        time.sleep(0.15)
        detector.update(1, self._static_lines())
        assert detector.is_idle(1) is True
        detector.remove_agent(1)
        assert detector.is_idle(1) is False

    def test_multiple_agents_independent(self):
        detector = IdleDetector(idle_timeout=0.1)
        detector.update(1, self._static_lines())
        detector.update(2, self._static_lines())
        time.sleep(0.15)
        detector.update(1, self._static_lines())  # same → idle
        detector.update(2, self._changing_lines(2))  # changed → not idle
        assert detector.is_idle(1) is True
        assert detector.is_idle(2) is False

    def test_tracked_ids(self):
        detector = IdleDetector(idle_timeout=0.1)
        assert detector.tracked_ids() == set()
        detector.update(1, self._static_lines())
        detector.update(2, self._static_lines())
        assert detector.tracked_ids() == {1, 2}
        detector.remove_agent(1)
        assert detector.tracked_ids() == {2}

    def test_remove_agent_resets_stable_baseline(self):
        """Regression: attaching to an agent (→ FOCUSED) must clear the stable
        timer. Otherwise, when it returns to RUNNING, the detector treats the
        attach window as 'stable content' and fires idle immediately."""
        detector = IdleDetector(idle_timeout=0.1)
        detector.update(1, self._static_lines())  # t=0: baseline
        time.sleep(0.08)                          # ~80% of timeout elapses
        detector.remove_agent(1)                  # simulates RUNNING → FOCUSED prune
        detector.update(1, self._static_lines())  # same content, FOCUSED → RUNNING
        assert detector.is_idle(1) is False, (
            "Fresh baseline expected after prune; must not inherit prior elapsed"
        )
        time.sleep(0.05)
        detector.update(1, self._static_lines())
        # Only 0.05s since the post-prune baseline — still below 0.1s timeout
        assert detector.is_idle(1) is False


class TestMonitorStates:
    def test_on_hold_not_in_active_states(self):
        from aque.monitor import MONITORED_STATES
        from aque.state import AgentState
        assert AgentState.ON_HOLD not in MONITORED_STATES
        assert AgentState.RUNNING in MONITORED_STATES


class TestSignalFiles:
    def test_check_signal_files_returns_agent_ids(self, tmp_path):
        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()
        (signals_dir / "3.json").write_text(json.dumps({"event": "stop"}))
        (signals_dir / "7.json").write_text(json.dumps({"event": "stop"}))
        ids = check_signal_files(signals_dir)
        assert ids == {3, 7}

    def test_check_signal_files_consumes_files(self, tmp_path):
        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()
        (signals_dir / "3.json").write_text(json.dumps({"event": "stop"}))
        check_signal_files(signals_dir)
        assert not (signals_dir / "3.json").exists()

    def test_check_signal_files_empty_dir(self, tmp_path):
        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()
        ids = check_signal_files(signals_dir)
        assert ids == set()

    def test_check_signal_files_dir_missing(self, tmp_path):
        signals_dir = tmp_path / "signals"
        ids = check_signal_files(signals_dir)
        assert ids == set()

    def test_check_signal_files_ignores_non_json(self, tmp_path):
        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()
        (signals_dir / "readme.txt").write_text("not a signal")
        (signals_dir / "3.json").write_text(json.dumps({"event": "stop"}))
        ids = check_signal_files(signals_dir)
        assert ids == {3}
        assert (signals_dir / "readme.txt").exists()

    def test_check_signal_files_ignores_non_numeric_names(self, tmp_path):
        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()
        (signals_dir / "abc.json").write_text(json.dumps({"event": "stop"}))
        ids = check_signal_files(signals_dir)
        assert ids == set()

    def test_cleanup_stale_signals(self, tmp_path):
        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()
        (signals_dir / "1.json").write_text(json.dumps({"event": "stop"}))
        (signals_dir / "99.json").write_text(json.dumps({"event": "stop"}))
        active_ids = {1}
        cleanup_stale_signals(signals_dir, active_ids)
        assert (signals_dir / "1.json").exists()
        assert not (signals_dir / "99.json").exists()


"""Append these tests to tests/test_monitor.py."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from aque.state import AgentInfo, AgentState, StateManager


class TestResponderNudgeIntegration:
    def _make_state(self, tmp_aque_dir, *, waiting_seconds_ago: int):
        mgr = StateManager(tmp_aque_dir)
        last_change = (datetime.now(timezone.utc) - timedelta(seconds=waiting_seconds_ago)).isoformat()
        partner = AgentInfo(
            id=1, tmux_session="aque-foo-1", label="foo",
            dir="/tmp", command=["claude"], state=AgentState.WAITING, pid=100,
            last_change_at=last_change,
        )
        responder = AgentInfo(
            id=2, tmux_session="aque-resp-1-2", label="resp(1)",
            dir="/tmp", command=["claude"], state=AgentState.RUNNING, pid=101,
            is_responder=True, partner_id=1,
        )
        mgr.add_agent(partner)
        mgr.add_agent(responder)
        return mgr

    @patch("aque.monitor.responder.nudge")
    def test_nudge_fires_after_idle_gap(self, mock_nudge, tmp_aque_dir):
        from aque.monitor import process_pending_nudges

        mgr = self._make_state(tmp_aque_dir, waiting_seconds_ago=10)
        config = {"responder_idle_gap": 5, "responder_enabled": True}
        process_pending_nudges(mgr, MagicMock(), config)
        assert mock_nudge.call_count == 1

    @patch("aque.monitor.responder.nudge")
    def test_no_nudge_before_idle_gap(self, mock_nudge, tmp_aque_dir):
        from aque.monitor import process_pending_nudges

        mgr = self._make_state(tmp_aque_dir, waiting_seconds_ago=2)
        config = {"responder_idle_gap": 5, "responder_enabled": True}
        process_pending_nudges(mgr, MagicMock(), config)
        mock_nudge.assert_not_called()

    @patch("aque.monitor.responder.nudge")
    def test_no_nudge_when_responder_enabled_false(self, mock_nudge, tmp_aque_dir):
        from aque.monitor import process_pending_nudges

        mgr = self._make_state(tmp_aque_dir, waiting_seconds_ago=10)
        config = {"responder_idle_gap": 5, "responder_enabled": False}
        process_pending_nudges(mgr, MagicMock(), config)
        mock_nudge.assert_not_called()

    @patch("aque.monitor.responder.nudge")
    def test_no_nudge_for_responder_in_waiting(self, mock_nudge, tmp_aque_dir):
        from aque.monitor import process_pending_nudges

        mgr = StateManager(tmp_aque_dir)
        last = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        mgr.add_agent(AgentInfo(
            id=1, tmux_session="aque-1", label="partner",
            dir="/tmp", command=["claude"], state=AgentState.RUNNING, pid=100,
            last_change_at=last,
        ))
        mgr.add_agent(AgentInfo(
            id=2, tmux_session="aque-2", label="resp(1)",
            dir="/tmp", command=["claude"], state=AgentState.WAITING, pid=101,
            is_responder=True, partner_id=1, last_change_at=last,
        ))
        config = {"responder_idle_gap": 5, "responder_enabled": True}
        process_pending_nudges(mgr, MagicMock(), config)
        mock_nudge.assert_not_called()

    @patch("aque.monitor.responder.nudge")
    def test_renudge_after_another_gap(self, mock_nudge, tmp_aque_dir):
        from aque.monitor import process_pending_nudges

        mgr = self._make_state(tmp_aque_dir, waiting_seconds_ago=30)
        with mgr._locked():
            state = mgr.load()
            for a in state.agents:
                if a.id == 1:
                    a.last_nudge_at = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
            mgr.save(state)

        config = {"responder_idle_gap": 5, "responder_enabled": True}
        process_pending_nudges(mgr, MagicMock(), config)
        assert mock_nudge.call_count == 1

    @patch("aque.monitor.responder.nudge")
    def test_no_renudge_within_gap(self, mock_nudge, tmp_aque_dir):
        from aque.monitor import process_pending_nudges

        mgr = self._make_state(tmp_aque_dir, waiting_seconds_ago=30)
        with mgr._locked():
            state = mgr.load()
            for a in state.agents:
                if a.id == 1:
                    a.last_nudge_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
            mgr.save(state)

        config = {"responder_idle_gap": 5, "responder_enabled": True}
        process_pending_nudges(mgr, MagicMock(), config)
        mock_nudge.assert_not_called()


class TestResponderCleanupIntegration:
    @patch("aque.monitor.responder.cleanup")
    def test_cleanup_called_on_running_to_exited(self, mock_cleanup, tmp_aque_dir):
        """When monitor flips partner running→exited, cleanup fires."""
        from aque.monitor import handle_session_gone

        mgr = StateManager(tmp_aque_dir)
        partner = AgentInfo(
            id=1, tmux_session="aque-foo-1", label="foo",
            dir="/tmp", command=["claude"], state=AgentState.RUNNING, pid=100,
        )
        mgr.add_agent(partner)
        handle_session_gone(partner, mgr, MagicMock(), aque_dir=tmp_aque_dir)

        state = mgr.load()
        assert state.agents[0].state == AgentState.EXITED
        mock_cleanup.assert_called_once()


def test_run_monitor_refreshes_pid_heartbeat(tmp_aque_dir, monkeypatch):
    """Each poll iteration should rewrite monitor.pid, bumping its mtime."""
    import aque.monitor as monitor

    pid_file = tmp_aque_dir / "monitor.pid"
    seen_mtimes = []

    def fake_sleep(_interval):
        # Capture the heartbeat mtime as seen at the end of this iteration.
        seen_mtimes.append(pid_file.stat().st_mtime)
        if len(seen_mtimes) >= 2:
            raise KeyboardInterrupt
        # Backdate the file so a refresh on the next iteration is observable.
        old = pid_file.stat().st_mtime
        os.utime(pid_file, (old - 100, old - 100))

    monkeypatch.setattr(monitor.time, "sleep", fake_sleep)
    # No agents in state, so the per-agent tmux loop is a no-op.
    try:
        monitor.run_monitor(tmp_aque_dir)
    except KeyboardInterrupt:
        pass

    assert len(seen_mtimes) == 2
    # Second iteration must have refreshed the backdated mtime forward.
    assert seen_mtimes[1] > seen_mtimes[0]
