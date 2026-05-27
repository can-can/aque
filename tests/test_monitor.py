import json
import os
import time
from pathlib import Path

from aque.monitor import (
    IdleDetector,
    check_signal_files,
    cleanup_stale_signals,
    clear_all_signals,
)


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
    def test_check_signal_files_returns_events(self, tmp_path):
        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()
        (signals_dir / "3.json").write_text(
            json.dumps({"event": "stop", "source": "Stop"})
        )
        (signals_dir / "7.json").write_text(
            json.dumps({"event": "start", "source": "UserPromptSubmit"})
        )
        assert check_signal_files(signals_dir) == {
            3: {"event": "stop", "source": "Stop"},
            7: {"event": "start", "source": "UserPromptSubmit"},
        }

    def test_check_signal_files_legacy_payload_without_source(self, tmp_path):
        """Older hook installs wrote ``{"event": "stop"}`` with no source — the
        monitor must still consume them, tagging source as ``legacy`` so the
        debug log can flag pre-upgrade signals on sight."""
        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()
        (signals_dir / "3.json").write_text(json.dumps({"event": "stop"}))
        result = check_signal_files(signals_dir)
        assert result == {3: {"event": "stop", "source": "legacy"}}

    def test_check_signal_files_defaults_malformed_to_stop(self, tmp_path):
        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()
        (signals_dir / "3.json").write_text("not json")
        (signals_dir / "4.json").write_text(json.dumps({"no_event": 1}))
        (signals_dir / "5.json").write_text("[]")  # JSON but not an object
        result = check_signal_files(signals_dir)
        # Unparseable / non-object → flagged as malformed.
        assert result[3] == {"event": "stop", "source": "malformed"}
        assert result[5] == {"event": "stop", "source": "malformed"}
        # Object without ``event`` keeps its own keys and defaults event/source.
        assert result[4]["event"] == "stop"
        assert result[4]["source"] == "legacy"

    def test_check_signal_files_consumes_files(self, tmp_path):
        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()
        (signals_dir / "3.json").write_text(json.dumps({"event": "stop"}))
        check_signal_files(signals_dir)
        assert not (signals_dir / "3.json").exists()

    def test_check_signal_files_empty_dir(self, tmp_path):
        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()
        assert check_signal_files(signals_dir) == {}

    def test_check_signal_files_dir_missing(self, tmp_path):
        assert check_signal_files(tmp_path / "signals") == {}

    def test_check_signal_files_ignores_non_json(self, tmp_path):
        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()
        (signals_dir / "readme.txt").write_text("not a signal")
        (signals_dir / "3.json").write_text(json.dumps({"event": "stop"}))
        result = check_signal_files(signals_dir)
        assert result == {3: {"event": "stop", "source": "legacy"}}
        assert (signals_dir / "readme.txt").exists()

    def test_check_signal_files_ignores_non_numeric_names(self, tmp_path):
        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()
        (signals_dir / "abc.json").write_text(json.dumps({"event": "stop"}))
        assert check_signal_files(signals_dir) == {}

    def test_cleanup_stale_signals(self, tmp_path):
        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()
        (signals_dir / "1.json").write_text(json.dumps({"event": "stop"}))
        (signals_dir / "99.json").write_text(json.dumps({"event": "stop"}))
        active_ids = {1}
        cleanup_stale_signals(signals_dir, active_ids)
        assert (signals_dir / "1.json").exists()
        assert not (signals_dir / "99.json").exists()

    def test_clear_all_signals_removes_every_json_file(self, tmp_path):
        """Regression: a stop signal written during a monitor-restart gap used
        to survive into the new monitor and flip an actively-running Claude
        agent to WAITING. The new monitor now clears every signal on startup."""
        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()
        (signals_dir / "3.json").write_text(json.dumps({"event": "stop"}))
        (signals_dir / "7.json").write_text(json.dumps({"event": "start"}))
        (signals_dir / "11.json").write_text(json.dumps({"event": "stop"}))
        (signals_dir / "readme.txt").write_text("kept")  # non-json untouched
        removed = clear_all_signals(signals_dir)
        assert removed == 3
        assert not (signals_dir / "3.json").exists()
        assert not (signals_dir / "7.json").exists()
        assert not (signals_dir / "11.json").exists()
        assert (signals_dir / "readme.txt").exists()

    def test_clear_all_signals_dir_missing(self, tmp_path):
        assert clear_all_signals(tmp_path / "missing") == 0


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


from aque import monitor
from aque.monitor import IdleDetector, _poll_once
from aque.state import AgentInfo, AgentState, StateManager


def _mk_agent(state, agent_type=None, agent_id=1):
    return AgentInfo(
        id=agent_id, tmux_session=f"aque-{agent_id}", label="t", dir="/tmp",
        command=["claude"], state=state, pid=1, agent_type=agent_type,
    )


def _setup(tmp_path, agent):
    mgr = StateManager(tmp_path)
    mgr.add_agent(agent)
    signals = tmp_path / "signals"
    signals.mkdir(exist_ok=True)
    cfg = {"idle_timeout": 0, "responder_enabled": False, "responder_idle_gap": 30}
    return mgr, signals, cfg


def test_attached_running_agent_skips_idle(monkeypatch, tmp_path):
    agent = _mk_agent(AgentState.RUNNING, agent_type=None)
    mgr, signals, cfg = _setup(tmp_path, agent)
    detector = IdleDetector(idle_timeout=0, aque_dir=tmp_path)
    waiting_hashes: dict[int, str] = {}
    monkeypatch.setattr(monitor, "session_exists", lambda *a, **k: True)
    monkeypatch.setattr(monitor, "capture_pane_content", lambda *a, **k: "stable")
    monkeypatch.setattr(monitor, "_has_attached_client", lambda *a, **k: True)
    _poll_once(mgr, object(), detector, cfg, signals, 600, tmp_path, waiting_hashes)
    _poll_once(mgr, object(), detector, cfg, signals, 600, tmp_path, waiting_hashes)
    assert mgr.load().agents[0].state == AgentState.RUNNING


def test_idle_flips_when_not_attached(monkeypatch, tmp_path):
    agent = _mk_agent(AgentState.RUNNING, agent_type=None)
    mgr, signals, cfg = _setup(tmp_path, agent)
    detector = IdleDetector(idle_timeout=0, aque_dir=tmp_path)
    waiting_hashes: dict[int, str] = {}
    monkeypatch.setattr(monitor, "session_exists", lambda *a, **k: True)
    monkeypatch.setattr(monitor, "capture_pane_content", lambda *a, **k: "stable")
    monkeypatch.setattr(monitor, "_has_attached_client", lambda *a, **k: False)
    _poll_once(mgr, object(), detector, cfg, signals, 600, tmp_path, waiting_hashes)
    _poll_once(mgr, object(), detector, cfg, signals, 600, tmp_path, waiting_hashes)
    assert mgr.load().agents[0].state == AgentState.WAITING


def _mark_attached(tmp_path, agent_id: int) -> None:
    """Drop a desk-attach marker so re-promotion sees an active desk attach."""
    attached_dir = tmp_path / "attached"
    attached_dir.mkdir(exist_ok=True)
    (attached_dir / str(agent_id)).touch()


def test_waiting_becomes_running_on_content_change_while_attached(monkeypatch, tmp_path):
    agent = _mk_agent(AgentState.WAITING, agent_type=None)
    mgr, signals, cfg = _setup(tmp_path, agent)
    detector = IdleDetector(idle_timeout=15, aque_dir=tmp_path)
    waiting_hashes: dict[int, str] = {}
    _mark_attached(tmp_path, agent.id)
    monkeypatch.setattr(monitor, "session_exists", lambda *a, **k: True)
    monkeypatch.setattr(monitor, "capture_pane_content", lambda *a, **k: "before")
    _poll_once(mgr, object(), detector, cfg, signals, 600, tmp_path, waiting_hashes)
    assert mgr.load().agents[0].state == AgentState.WAITING
    monkeypatch.setattr(monitor, "capture_pane_content", lambda *a, **k: "after")
    _poll_once(mgr, object(), detector, cfg, signals, 600, tmp_path, waiting_hashes)
    assert mgr.load().agents[0].state == AgentState.RUNNING


def test_waiting_unchanged_content_does_not_flip(monkeypatch, tmp_path):
    agent = _mk_agent(AgentState.WAITING, agent_type=None)
    mgr, signals, cfg = _setup(tmp_path, agent)
    detector = IdleDetector(idle_timeout=15, aque_dir=tmp_path)
    waiting_hashes: dict[int, str] = {}
    _mark_attached(tmp_path, agent.id)
    monkeypatch.setattr(monitor, "session_exists", lambda *a, **k: True)
    monkeypatch.setattr(monitor, "capture_pane_content", lambda *a, **k: "same")
    _poll_once(mgr, object(), detector, cfg, signals, 600, tmp_path, waiting_hashes)
    _poll_once(mgr, object(), detector, cfg, signals, 600, tmp_path, waiting_hashes)
    assert mgr.load().agents[0].state == AgentState.WAITING


def test_waiting_not_repromoted_without_desk_marker(monkeypatch, tmp_path):
    """Regression for the WAITING↔RUNNING flap caused by external tmux clients.

    Before the marker-file fix, _has_attached_client returned True whenever
    *any* tmux client was attached — ghostty windows, the desk running
    inside an agent's own tmux session, etc. Re-promotion fired on every
    poll despite no actual desk attach, oscillating the state under the
    user. The gate now is the existence of <aque_dir>/attached/<id>, which
    only the desk writes around its own attach-session call.
    """
    agent = _mk_agent(AgentState.WAITING, agent_type=None)
    mgr, signals, cfg = _setup(tmp_path, agent)
    detector = IdleDetector(idle_timeout=15, aque_dir=tmp_path)
    waiting_hashes: dict[int, str] = {}
    # External client is attached (session_attached > 0) but the desk has
    # NOT written its marker — the monitor must leave the agent in WAITING.
    monkeypatch.setattr(monitor, "session_exists", lambda *a, **k: True)
    monkeypatch.setattr(monitor, "_has_attached_client", lambda *a, **k: True)
    monkeypatch.setattr(monitor, "capture_pane_content", lambda *a, **k: "before")
    _poll_once(mgr, object(), detector, cfg, signals, 600, tmp_path, waiting_hashes)
    assert mgr.load().agents[0].state == AgentState.WAITING
    monkeypatch.setattr(monitor, "capture_pane_content", lambda *a, **k: "after")
    _poll_once(mgr, object(), detector, cfg, signals, 600, tmp_path, waiting_hashes)
    assert mgr.load().agents[0].state == AgentState.WAITING, (
        "Content changed but no desk marker — must NOT re-promote"
    )


def test_demoted_agent_does_not_repromote_on_attach_via_stale_hash(monkeypatch, tmp_path):
    """Regression for the WAITING↔RUNNING oscillation on agent_type=None agents.

    A WAITING-period content hash used to linger in ``waiting_hashes`` after the
    agent left WAITING (via spurious re-promotion). When the agent fell back to
    WAITING via idle and was re-attached, the very first poll compared the new
    attach content against that stale hash and falsely promoted again — the
    triage modal then re-popped each cycle in production (see debug.log:
    monitor.idle->waiting / monitor.waiting->running every ~5s).
    """
    agent = _mk_agent(AgentState.RUNNING, agent_type=None)
    mgr, signals, cfg = _setup(tmp_path, agent)
    detector = IdleDetector(idle_timeout=0, aque_dir=tmp_path)
    # Stale hash left over from a prior WAITING-attached cycle (different from
    # whatever capture_pane_content returns now). Without proper cleanup this
    # is the value the re-promotion compares against on the next attach.
    waiting_hashes: dict[int, str] = {agent.id: "stale-from-prior-cycle"}

    monkeypatch.setattr(monitor, "session_exists", lambda *a, **k: True)
    monkeypatch.setattr(monitor, "capture_pane_content", lambda *a, **k: "static")

    # Phase 1: not attached + stable content → RUNNING idles to WAITING.
    monkeypatch.setattr(monitor, "_has_attached_client", lambda *a, **k: False)
    _poll_once(mgr, object(), detector, cfg, signals, 600, tmp_path, waiting_hashes)
    _poll_once(mgr, object(), detector, cfg, signals, 600, tmp_path, waiting_hashes)
    assert mgr.load().agents[0].state == AgentState.WAITING

    # Phase 2: user attaches via the desk; pane text is unchanged. Must NOT
    # re-promote — the stale hash from before the RUNNING window must not
    # survive. Mark the desk attach so the marker-file gate doesn't trivially
    # skip the re-promotion path (which would hide the stale-hash regression).
    _mark_attached(tmp_path, agent.id)
    _poll_once(mgr, object(), detector, cfg, signals, 600, tmp_path, waiting_hashes)
    assert mgr.load().agents[0].state == AgentState.WAITING


# libtmux 0.17+ removed Session.get(); attach state is read via the
# session_attached attribute. These fakes must mirror that (no .get()) or they
# silently mask the real API and let attach-detection regress.
class _FakeSession:
    def __init__(self, attached):
        self.session_attached = attached


def _fake_server(session):
    class FakeServer:
        class sessions:
            @staticmethod
            def get(session_name=None):
                return session
    return FakeServer()


def test_has_attached_client_true():
    from aque import monitor

    assert monitor._has_attached_client(_fake_server(_FakeSession("1")), "aque-1") is True


def test_has_attached_client_true_when_multiple():
    # session_attached is a CLIENT COUNT, not a flag. Two clients (e.g. the
    # embedded terminal plus a lingering full-screen attach) means a client is
    # attached, so re-promotion / idle-suppression must still apply.
    from aque import monitor

    assert monitor._has_attached_client(_fake_server(_FakeSession("2")), "aque-1") is True


def test_has_attached_client_false_when_zero():
    from aque import monitor

    assert monitor._has_attached_client(_fake_server(_FakeSession("0")), "aque-1") is False


def test_has_attached_client_false_when_missing():
    from aque import monitor

    assert monitor._has_attached_client(_fake_server(None), "gone") is False


def _add(mgr, agent_id, state, agent_type):
    from aque.state import AgentInfo
    mgr.add_agent(AgentInfo(
        id=agent_id, tmux_session=f"s-{agent_id}", label=f"a{agent_id}",
        dir="/tmp", command=["x"], state=state, pid=100 + agent_id,
        agent_type=agent_type,
    ))


def _poll(mgr, monkeypatch, *, attached=False, content="x", waiting_hashes=None):
    """Drive one _poll_once with tmux interaction stubbed out."""
    from aque import monitor
    monkeypatch.setattr(monitor, "session_exists", lambda *a, **k: True)
    monkeypatch.setattr(monitor, "capture_pane_content", lambda *a, **k: content)
    monkeypatch.setattr(monitor, "_has_attached_client", lambda *a, **k: attached)
    monkeypatch.setattr(monitor, "process_pending_nudges", lambda *a, **k: None)
    if attached:
        attached_dir = mgr.aque_dir / "attached"
        attached_dir.mkdir(exist_ok=True)
        for a in mgr.load().agents:
            (attached_dir / str(a.id)).touch()
    detector = monitor.IdleDetector(idle_timeout=0.01, aque_dir=mgr.aque_dir)
    monitor._poll_once(
        mgr, server=None, detector=detector, config={},
        signals_dir=mgr.aque_dir / "signals", stall_timeout=600.0,
        aque_dir=mgr.aque_dir,
        waiting_hashes=waiting_hashes if waiting_hashes is not None else {},
    )


class TestEventDrivenSignals:
    def test_stop_event_flips_running_claude_to_waiting(self, tmp_path, monkeypatch):
        from aque.state import StateManager, AgentState
        mgr = StateManager(tmp_path)
        _add(mgr, 1, AgentState.RUNNING, "claude")
        sig = tmp_path / "signals"; sig.mkdir()
        (sig / "1.json").write_text('{"event":"stop"}')
        _poll(mgr, monkeypatch)
        assert mgr.load().agents[0].state == AgentState.WAITING

    def test_start_event_flips_waiting_claude_to_running(self, tmp_path, monkeypatch):
        from aque.state import StateManager, AgentState
        mgr = StateManager(tmp_path)
        _add(mgr, 1, AgentState.WAITING, "claude")
        sig = tmp_path / "signals"; sig.mkdir()
        (sig / "1.json").write_text('{"event":"start"}')
        _poll(mgr, monkeypatch)
        assert mgr.load().agents[0].state == AgentState.RUNNING

    def test_waiting_claude_not_repromoted_by_content_change(self, tmp_path, monkeypatch):
        # The flicker case: a previewed (attached) waiting claude whose pane
        # content changes must STAY waiting (only a 'start' signal resumes it).
        from aque.state import StateManager, AgentState
        mgr = StateManager(tmp_path)
        _add(mgr, 1, AgentState.WAITING, "claude")
        (tmp_path / "signals").mkdir()
        wh = {}
        _poll(mgr, monkeypatch, attached=True, content="frame-A", waiting_hashes=wh)
        _poll(mgr, monkeypatch, attached=True, content="frame-B", waiting_hashes=wh)
        assert mgr.load().agents[0].state == AgentState.WAITING

    def test_waiting_typeless_still_repromoted_by_content_change(self, tmp_path, monkeypatch):
        from aque.state import StateManager, AgentState
        mgr = StateManager(tmp_path)
        _add(mgr, 1, AgentState.WAITING, None)
        (tmp_path / "signals").mkdir()
        wh = {}
        _poll(mgr, monkeypatch, attached=True, content="frame-A", waiting_hashes=wh)
        _poll(mgr, monkeypatch, attached=True, content="frame-B", waiting_hashes=wh)
        assert mgr.load().agents[0].state == AgentState.RUNNING


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
