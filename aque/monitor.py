import hashlib
import json
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

    def tracked_ids(self) -> set[int]:
        return set(self._content_hash.keys())


def prune_detector(detector: "IdleDetector", running_ids: set[int]) -> set[int]:
    """Drop detector state for any tracked agent not in `running_ids`.

    Called once per monitor poll so that an agent returning to RUNNING after
    being attached (or any non-RUNNING transition) gets a fresh idle-timer
    baseline.
    """
    stale = detector.tracked_ids() - running_ids
    for sid in stale:
        detector.remove_agent(sid)
    return stale


def prune_waiting_hashes(
    waiting_hashes: dict[int, str], waiting_ids: set[int]
) -> set[int]:
    """Drop waiting-hash baselines for any agent not currently WAITING.

    Symmetric to ``prune_detector`` for the RUNNING branch. Without this, a
    hash captured while the agent was previously WAITING-and-attached lingers
    after the agent leaves WAITING (via re-promotion or any other path). When
    the agent returns to WAITING and is re-attached, the first poll compares
    the fresh content against the stale baseline and falsely re-promotes —
    causing endless WAITING↔RUNNING oscillation on typeless agents whose pane
    runs an interactive TUI.
    """
    stale = set(waiting_hashes.keys()) - waiting_ids
    for sid in stale:
        waiting_hashes.pop(sid, None)
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


def _has_desk_marker(aque_dir: Path, agent_id: int) -> bool:
    """True if the desk has an open full-screen attach to this agent.

    The desk writes ``<aque_dir>/attached/<id>`` around its ``tmux
    attach-session`` call (deleted in finally) so the monitor can tell the
    user's own desk attach apart from any *other* tmux client (a ghostty
    window manually attached, the desk running inside an agent's own tmux
    session, etc.). The previous ``session_attached`` count check couldn't
    distinguish those: any external client falsely re-promoted WAITING
    agents to RUNNING, causing a steady-state state flap.
    """
    return (aque_dir / "attached" / str(agent_id)).exists()


def _has_attached_client(server: libtmux.Server, session_name: str) -> bool:
    """True if a tmux client is currently attached to the session.

    Used by the RUNNING-stays-running guard so idle detection doesn't fire
    while the user is driving the pane. The WAITING→RUNNING re-promotion
    uses ``_has_desk_marker`` instead so external clients don't trigger it.
    """
    try:
        session = server.sessions.get(session_name=session_name)
        if session is None:
            return False
        # libtmux 0.17+ removed Session.get() (it raises DeprecatedError); read
        # the attribute directly. session_attached is the *count* of attached
        # clients, not a flag — it is "2"+ when the embedded terminal coexists
        # with another attach. Any count > 0 means a client is driving the pane.
        try:
            return int(session.session_attached) > 0
        except (TypeError, ValueError):
            return False
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


def check_signal_files(signals_dir: Path) -> dict[int, dict[str, str]]:
    """Read and consume signal files. Returns ``{agent_id: payload}``.

    ``payload`` is the parsed JSON (with at least an ``event`` key, plus
    optional ``source`` carrying the originating Claude ``hook_event_name``).
    Malformed or legacy files default to ``{"event": "stop", "source":
    "malformed"}`` — the conservative behaviour preserves the original "treat
    unknown as stop" contract while still letting the monitor log *why*.
    """
    signaled: dict[int, dict[str, str]] = {}
    if not signals_dir.is_dir():
        return signaled
    for f in signals_dir.iterdir():
        if f.suffix != ".json":
            continue
        try:
            agent_id = int(f.stem)
        except ValueError:
            # Malformed filename (e.g. ".json" from an unset AQUE_AGENT_ID).
            f.unlink(missing_ok=True)
            continue
        try:
            payload = json.loads(f.read_text())
            if not isinstance(payload, dict):
                raise ValueError("payload is not an object")
        except (json.JSONDecodeError, OSError, ValueError):
            payload = {"event": "stop", "source": "malformed"}
        payload.setdefault("event", "stop")
        payload.setdefault("source", "legacy")
        signaled[agent_id] = payload
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


def clear_all_signals(signals_dir: Path) -> int:
    """Delete every signal file. Called on monitor startup.

    A signal file written during a monitor-restart gap (the seconds between
    the old monitor dying and the new one polling) survives by virtue of nobody
    consuming it. The first poll of the new monitor would then apply that
    stale signal — and we cannot tell whether the underlying hook event was
    legitimate or a misfire, because we lost the timing context.

    Solution: the new monitor starts from a clean signals dir and trusts the
    persisted state.json as the source of truth. Any subsequent hook event
    fires fresh under the new monitor's watch.

    Returns the number of files removed (for logging).
    """
    if not signals_dir.is_dir():
        return 0
    count = 0
    for f in signals_dir.iterdir():
        if f.suffix == ".json":
            f.unlink(missing_ok=True)
            count += 1
    return count


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


def _poll_once(
    mgr: StateManager,
    server: libtmux.Server,
    detector: IdleDetector,
    config: dict,
    signals_dir: Path,
    aque_dir: Path,
    waiting_hashes: dict[int, str],
) -> None:
    """Execute one monitor poll: prune, signal detection, idle/stall checks, nudges.

    The heartbeat write and time.sleep stay in run_monitor; everything else
    that happens once per poll is in here so tests can call it directly.
    """
    state = mgr.load()
    active_agents = [
        a for a in state.agents if a.state in MONITORED_STATES
    ]

    # Prune detector state for agents that are no longer RUNNING (e.g. after
    # being attached, or deleted entirely). Prevents stable-content timers
    # from carrying across the attach window and causing spurious idle.
    running_ids = {a.id for a in active_agents}
    for stale_id in prune_detector(detector, running_ids):
        dbg("monitor.detector.prune", aque_dir, agent_id=stale_id)

    # Same treatment for waiting_hashes: a hash from a prior WAITING-attached
    # cycle must not survive the agent's trip through RUNNING and back, or
    # the next attach instantly re-promotes against that stale baseline.
    waiting_ids = {a.id for a in state.agents if a.state == AgentState.WAITING}
    for stale_id in prune_waiting_hashes(waiting_hashes, waiting_ids):
        dbg("monitor.waiting_hash.prune", aque_dir, agent_id=stale_id)

    # Apply hook signals first (instant). stop -> WAITING, start -> RUNNING.
    signaled = check_signal_files(signals_dir)
    if signaled:
        by_id = {a.id: a for a in mgr.load().agents}
        for aid, payload in signaled.items():
            agent = by_id.get(aid)
            if agent is None:
                continue
            event = payload.get("event", "stop")
            source = payload.get("source", "unknown")
            if event == "start":
                if agent.state == AgentState.WAITING:
                    dbg("monitor.signal->running", aque_dir, agent_id=aid, source=source)
                    mgr.update_agent_state(aid, AgentState.RUNNING)
            else:  # "stop" (and any unknown event)
                if agent.state == AgentState.RUNNING:
                    dbg("monitor.signal->waiting", aque_dir, agent_id=aid, source=source)
                    mgr.update_agent_state(aid, AgentState.WAITING)
                    detector.remove_agent(aid)
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

        if _has_attached_client(server, agent.tmux_session):
            # User is driving the pane — never auto-flip to WAITING, and
            # reset the idle baseline so a fresh stable window starts on detach.
            detector.remove_agent(agent.id)
            continue

        if detector.is_idle(agent.id):
            dbg("monitor.idle->waiting", aque_dir, agent_id=agent.id)
            mgr.update_agent_state(agent.id, AgentState.WAITING)
            detector.remove_agent(agent.id)

    # WAITING re-promotion: if a client is attached and pane content changed,
    # the user has resumed work — flip the agent back to RUNNING.
    for agent in mgr.load().agents:
        if agent.state != AgentState.WAITING:
            continue
        if not _has_desk_marker(aque_dir, agent.id):
            continue  # only the desk's own attach counts — external clients don't
        content = capture_pane_content(server, agent.tmux_session)
        if content is None:
            continue
        new_hash = hashlib.md5(content.encode()).hexdigest()
        prev = waiting_hashes.get(agent.id)
        waiting_hashes[agent.id] = new_hash
        if prev is not None and new_hash != prev:
            dbg("monitor.waiting->running", aque_dir, agent_id=agent.id)
            mgr.update_agent_state(agent.id, AgentState.RUNNING)

    # End of per-agent loop. Now process auto-responder nudges.
    process_pending_nudges(mgr, server, config)


def run_monitor(aque_dir: Path) -> None:
    config = load_config(aque_dir)
    mgr = StateManager(aque_dir)
    detector = IdleDetector(idle_timeout=config["idle_timeout"], aque_dir=aque_dir)
    interval = config["snapshot_interval"]
    dbg(
        "monitor.start",
        aque_dir,
        idle_timeout=config["idle_timeout"],
        interval=interval,
    )

    pid_file = aque_dir / "monitor.pid"
    pid_file.write_text(str(os.getpid()))

    signals_dir = aque_dir / "signals"
    signals_dir.mkdir(exist_ok=True)

    server = libtmux.Server()

    # Drop every pre-existing signal file. A signal written during the
    # restart gap (no monitor polling) would otherwise be applied on the
    # first poll against a state context that doesn't match — flipping an
    # actively-running agent to WAITING with no way to recover until the
    # next user prompt. State.json is the source of truth on startup.
    cleared = clear_all_signals(signals_dir)
    if cleared:
        dbg("monitor.signals.cleared_on_startup", aque_dir, count=cleared)

    # Same treatment for desk-attach markers: a marker left behind by a
    # killed desk (no finally cleanup) would otherwise let the monitor
    # re-promote on the next poll against a state where nothing is actually
    # attached. State.json is the truth — start with an empty marker dir.
    attached_dir = aque_dir / "attached"
    attached_dir.mkdir(exist_ok=True)
    stale_markers = list(attached_dir.iterdir())
    for p in stale_markers:
        try:
            p.unlink()
        except OSError:
            pass
    if stale_markers:
        dbg("monitor.markers.cleared_on_startup", aque_dir, count=len(stale_markers))

    waiting_hashes: dict[int, str] = {}

    try:
        while True:
            # Heartbeat: bump monitor.pid mtime each poll so the desk can tell a
            # live monitor from a dead/hung one (kill(pid,0) alone can't).
            try:
                pid_file.write_text(str(os.getpid()))
            except OSError:
                pass

            _poll_once(mgr, server, detector, config, signals_dir, aque_dir, waiting_hashes)

            time.sleep(interval)
    finally:
        pid_file.unlink(missing_ok=True)


def _detach_inherited_fds() -> None:
    """Close every fd the daemonized child inherited from its parent.

    A forked daemon otherwise holds the parent's open fds. In production that's
    the desk's terminal; under pytest it's the runner's output pipe — and pytest
    keeps the real stdout on a high fd during capture, so detaching just 0/1/2
    isn't enough. While any inherited write-end stays open the reader never sees
    EOF, so the parent hangs on exit (and orphan daemons leak). Close them all,
    then point 0/1/2 at /dev/null; the monitor opens its own fds as it runs.
    """
    try:
        max_fd = os.sysconf("SC_OPEN_MAX")
    except (ValueError, OSError):
        max_fd = 1024
    max_fd = min(max_fd, 4096)
    os.closerange(3, max_fd)
    devnull = os.open(os.devnull, os.O_RDWR)  # lands on fd 0
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)


def start_monitor_daemon(aque_dir: Path) -> int:
    pid = os.fork()
    if pid == 0:
        os.setsid()
        _detach_inherited_fds()
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
