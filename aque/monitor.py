import os
import signal
import time
from pathlib import Path

import libtmux

from aque.config import load_config
from aque.state import AgentState, StateManager

MONITORED_STATES = {AgentState.RUNNING}

# Patterns that indicate a CLI tool is waiting for user input
_IDLE_PROMPT_MARKERS = [
    "❯",           # Claude Code prompt
    "$",            # generic shell prompt
    ">>>",          # Python REPL
    "...",          # Python continuation
]


def _looks_idle(lines: list[str]) -> bool:
    """Check if the pane looks like it's waiting for user input.

    Scans the last few non-empty lines for prompt markers.
    """
    # Look at last 10 non-empty lines for a prompt
    recent = [l.strip() for l in lines[-10:] if l.strip()]
    if not recent:
        return False
    for line in recent:
        for marker in _IDLE_PROMPT_MARKERS:
            if line.startswith(marker) or line == marker:
                return True
    return False


class IdleDetector:
    def __init__(self, idle_timeout: float):
        self.idle_timeout = idle_timeout
        self._first_idle: dict[int, float] = {}

    def update(self, agent_id: int, lines: list[str]) -> None:
        now = time.monotonic()
        if _looks_idle(lines):
            if agent_id not in self._first_idle:
                self._first_idle[agent_id] = now
        else:
            self._first_idle.pop(agent_id, None)

    def is_idle(self, agent_id: int) -> bool:
        if agent_id not in self._first_idle:
            return False
        elapsed = time.monotonic() - self._first_idle[agent_id]
        return elapsed >= self.idle_timeout

    def remove_agent(self, agent_id: int) -> None:
        self._first_idle.pop(agent_id, None)


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


def run_monitor(aque_dir: Path) -> None:
    config = load_config(aque_dir)
    mgr = StateManager(aque_dir)
    detector = IdleDetector(idle_timeout=config["idle_timeout"])
    interval = config["snapshot_interval"]

    pid_file = aque_dir / "monitor.pid"
    pid_file.write_text(str(os.getpid()))

    server = libtmux.Server()

    try:
        while True:
            state = mgr.load()
            active_agents = [
                a for a in state.agents if a.state in MONITORED_STATES
            ]

            for agent in active_agents:
                if agent.state != AgentState.RUNNING:
                    continue

                if not session_exists(server, agent.tmux_session):
                    mgr.update_agent_state(agent.id, AgentState.EXITED)
                    detector.remove_agent(agent.id)
                    continue

                content = capture_pane_content(server, agent.tmux_session)
                if content is not None:
                    detector.update(agent.id, content.split("\n"))

                if detector.is_idle(agent.id):
                    mgr.update_agent_state(agent.id, AgentState.WAITING)
                    detector.remove_agent(agent.id)

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
