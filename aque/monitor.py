import hashlib
import os
import signal
import time
from datetime import datetime, timezone
from pathlib import Path

import libtmux

from aque import responder
from aque.config import load_config
from aque.debug import dbg
from aque.state import AgentInfo, AgentState, StateManager

MONITORED_STATES = {AgentState.RUNNING}


class IdleDetector:
    def __init__(self, idle_timeout: float, aque_dir: Path | None = None):
        self.idle_timeout = idle_timeout
        self.aque_dir = aque_dir
        self._content_hash: dict[int, str] = {}
        self._stable_since: dict[int, float] = {}
        self._is_idle: dict[int, bool] = {}

    def update(self, agent_id: int, lines: list[str]) -> None:
        now = time.monotonic()

        content = "\n".join(lines)
        content_hash = hashlib.md5(content.encode()).hexdigest()
        prev_hash = self._content_hash.get(agent_id)
        self._content_hash[agent_id] = content_hash

        if content_hash != prev_hash:
            self._stable_since[agent_id] = now
            self._is_idle[agent_id] = False
            dbg(
                "detector.changed",
                self.aque_dir,
                agent_id=agent_id,
                prev=(prev_hash[:8] if prev_hash else None),
                new=content_hash[:8],
            )
            return

        # Content unchanged — check if stable long enough
        if agent_id not in self._stable_since:
            self._stable_since[agent_id] = now

        elapsed = now - self._stable_since[agent_id]
        was_idle = self._is_idle.get(agent_id, False)
        self._is_idle[agent_id] = elapsed >= self.idle_timeout
        if self._is_idle[agent_id] and not was_idle:
            dbg(
                "detector.idle",
                self.aque_dir,
                agent_id=agent_id,
                elapsed=f"{elapsed:.2f}s",
                timeout=f"{self.idle_timeout}s",
            )

    def is_idle(self, agent_id: int) -> bool:
        return self._is_idle.get(agent_id, False)

    def remove_agent(self, agent_id: int) -> None:
        self._content_hash.pop(agent_id, None)
        self._stable_since.pop(agent_id, None)
        self._is_idle.pop(agent_id, None)

    def stable_seconds(self, agent_id: int) -> float:
        start = self._stable_since.get(agent_id)
        if start is None:
            return 0.0
        return time.monotonic() - start

    def tracked_ids(self) -> set[int]:
        return set(self._content_hash.keys())


def prune_detector(detector: "IdleDetector", running_ids: set[int]) -> set[int]:
    """Drop detector state for any tracked agent not in `running_ids`.

    Called once per monitor poll so that an agent returning from FOCUSED
    (or any non-RUNNING state) gets a fresh idle-timer baseline.
    """
    stale = detector.tracked_ids() - running_ids
    for sid in stale:
        detector.remove_agent(sid)
    return stale


def capture_pane_content(server: libtmux.Server, session_name: str) -> str | None:
    try:
        session = server.sessions.get(session_name=session_name)
        if session is None:
            return None
        pane = session.active_pane
        lines = pane.capture_pane()
        return "\n".join(lines)
    except Exception:
        return None


def session_exists(server: libtmux.Server, session_name: str) -> bool:
    try:
        return server.sessions.get(session_name=session_name) is not None
    except Exception:
        return False


def handle_session_gone(
    agent: AgentInfo,
    state_manager: StateManager,
    server: libtmux.Server,
    *,
    aque_dir: Path,
) -> None:
    """Flip agent to EXITED. If it's a non-responder partner, clean up its responder."""
    state_manager.update_agent_state(agent.id, AgentState.EXITED)
    if not agent.is_responder:
        responder.cleanup(agent, state_manager, server, aque_dir=aque_dir)


def check_signal_files(signals_dir: Path) -> set[int]:
    """Read and consume signal files. Returns set of agent IDs that signaled."""
    signaled: set[int] = set()
    if not signals_dir.is_dir():
        return signaled
    for f in signals_dir.iterdir():
        if f.suffix != ".json":
            continue
        try:
            agent_id = int(f.stem)
        except ValueError:
            # Malformed filename (e.g. ".json" from an unset AQUE_AGENT_ID).
            # Drop it so it doesn't sit around forever.
            f.unlink(missing_ok=True)
            continue
        signaled.add(agent_id)
        f.unlink(missing_ok=True)
    return signaled


def cleanup_stale_signals(signals_dir: Path, active_ids: set[int]) -> None:
    """Remove signal files for agents that no longer exist."""
    if not signals_dir.is_dir():
        return
    for f in signals_dir.iterdir():
        if f.suffix != ".json":
            continue
        try:
            agent_id = int(f.stem)
        except ValueError:
            continue
        if agent_id not in active_ids:
            f.unlink(missing_ok=True)


def process_pending_nudges(
    state_manager: StateManager,
    server: libtmux.Server,
    config: dict,
) -> None:
    """Walk WAITING partners and nudge their responders when idle-gap has elapsed.

    Triggered once per monitor poll.
    """
    if not config.get("responder_enabled", True):
        return

    gap = float(config.get("responder_idle_gap", 30))
    now = datetime.now(timezone.utc)
    state = state_manager.load()
    agents = state.agents

    for partner in agents:
        if partner.is_responder:
            continue
        if partner.state != AgentState.WAITING:
            continue
        if not partner.auto_respond:
            continue

        resp = responder.find_for(partner.id, agents)
        if resp is None:
            continue

        if partner.last_nudge_at is None:
            ref = datetime.fromisoformat(partner.last_change_at)
        else:
            ref = datetime.fromisoformat(partner.last_nudge_at)
        if (now - ref).total_seconds() < gap:
            continue

        responder.nudge(partner, resp, server, state_manager=state_manager)


def run_monitor(aque_dir: Path) -> None:
    config = load_config(aque_dir)
    mgr = StateManager(aque_dir)
    detector = IdleDetector(idle_timeout=config["idle_timeout"], aque_dir=aque_dir)
    interval = config["snapshot_interval"]
    stall_timeout = config["stall_timeout"]
    dbg(
        "monitor.start",
        aque_dir,
        idle_timeout=config["idle_timeout"],
        stall_timeout=stall_timeout,
        interval=interval,
    )

    pid_file = aque_dir / "monitor.pid"
    pid_file.write_text(str(os.getpid()))

    signals_dir = aque_dir / "signals"
    signals_dir.mkdir(exist_ok=True)

    server = libtmux.Server()

    # Cleanup stale signals on startup
    state = mgr.load()
    active_ids = {a.id for a in state.agents}
    cleanup_stale_signals(signals_dir, active_ids)

    try:
        while True:
            # Heartbeat: bump monitor.pid mtime each poll so the desk can tell a
            # live monitor from a dead/hung one (kill(pid,0) alone can't).
            try:
                pid_file.write_text(str(os.getpid()))
            except OSError:
                pass

            state = mgr.load()
            active_agents = [
                a for a in state.agents if a.state in MONITORED_STATES
            ]

            # Prune detector state for agents that are no longer RUNNING (e.g. FOCUSED
            # after a user attach, or deleted entirely). Prevents stable-content timers
            # from carrying across the attach window and causing spurious idle.
            running_ids = {a.id for a in active_agents}
            for stale_id in prune_detector(detector, running_ids):
                dbg("monitor.detector.prune", aque_dir, agent_id=stale_id)

            # Check signal files first (instant detection)
            signaled_ids = check_signal_files(signals_dir)
            for agent in active_agents:
                if agent.id in signaled_ids:
                    dbg("monitor.signal->waiting", aque_dir, agent_id=agent.id)
                    mgr.update_agent_state(agent.id, AgentState.WAITING)
                    detector.remove_agent(agent.id)

            # Re-load state after signal transitions
            if signaled_ids:
                state = mgr.load()
                active_agents = [
                    a for a in state.agents if a.state in MONITORED_STATES
                ]

            for agent in active_agents:
                if agent.state != AgentState.RUNNING:
                    continue

                if not session_exists(server, agent.tmux_session):
                    dbg("monitor.session-gone->exited", aque_dir, agent_id=agent.id)
                    handle_session_gone(agent, mgr, server, aque_dir=aque_dir)
                    detector.remove_agent(agent.id)
                    continue

                content = capture_pane_content(server, agent.tmux_session)
                if content is not None:
                    detector.update(agent.id, content.split("\n"))

                if agent.agent_type is not None:
                    # Hooks are primary for typed agents. Only fall back to
                    # content-hash if the pane has been frozen for much longer
                    # than the normal idle timeout — a hook that never fires
                    # is the only plausible cause of a real stall that long.
                    stable = detector.stable_seconds(agent.id)
                    if stable >= stall_timeout:
                        dbg(
                            "monitor.stall->waiting",
                            aque_dir,
                            agent_id=agent.id,
                            elapsed=f"{stable:.1f}s",
                            threshold=f"{stall_timeout}s",
                        )
                        mgr.update_agent_state(agent.id, AgentState.WAITING)
                        detector.remove_agent(agent.id)
                elif detector.is_idle(agent.id):
                    dbg("monitor.idle->waiting", aque_dir, agent_id=agent.id)
                    mgr.update_agent_state(agent.id, AgentState.WAITING)
                    detector.remove_agent(agent.id)

            # End of per-agent loop. Now process auto-responder nudges.
            process_pending_nudges(mgr, server, config)

            time.sleep(interval)
    finally:
        pid_file.unlink(missing_ok=True)


def start_monitor_daemon(aque_dir: Path) -> int:
    pid = os.fork()
    if pid == 0:
        os.setsid()
        run_monitor(aque_dir)
        os._exit(0)
    else:
        state = StateManager(aque_dir).load()
        state.monitor_pid = pid
        StateManager(aque_dir).save(state)
        return pid


def stop_monitor(aque_dir: Path) -> None:
    mgr = StateManager(aque_dir)
    state = mgr.load()
    if state.monitor_pid:
        try:
            os.kill(state.monitor_pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        state.monitor_pid = None
        mgr.save(state)
    pid_file = aque_dir / "monitor.pid"
    pid_file.unlink(missing_ok=True)
