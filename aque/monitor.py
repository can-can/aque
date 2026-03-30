import enum
import hashlib
import os
import signal
import subprocess
import time
from pathlib import Path

import libtmux

from aque.config import load_config
from aque.state import AgentState, StateManager

MONITORED_STATES = {AgentState.RUNNING}


class ProcessTree(enum.Enum):
    NO_CHILDREN = "no_children"
    CHILDREN_ONLY = "children_only"
    GRANDCHILDREN = "grandchildren"


def check_process_tree(shell_pid: int) -> ProcessTree:
    """Check the process tree depth under a shell PID.

    Returns NO_CHILDREN if the shell has no children (agent exited),
    CHILDREN_ONLY if children exist but none have their own children,
    GRANDCHILDREN if any child has children (agent running subprocesses).
    """
    try:
        result = subprocess.run(
            ["pgrep", "-P", str(shell_pid)],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return ProcessTree.NO_CHILDREN

        children = [pid.strip() for pid in result.stdout.strip().split("\n") if pid.strip()]
        if not children:
            return ProcessTree.NO_CHILDREN

        for child_pid in children:
            gc_result = subprocess.run(
                ["pgrep", "-P", child_pid],
                capture_output=True, text=True, timeout=5,
            )
            if gc_result.returncode == 0 and gc_result.stdout.strip():
                return ProcessTree.GRANDCHILDREN

        return ProcessTree.CHILDREN_ONLY
    except Exception:
        return ProcessTree.CHILDREN_ONLY

_IDLE_PROMPT_PATTERNS = [
    "❯",       # Claude Code
    "$ ",       # shell prompt (trailing space)
    ">>> ",     # Python REPL
]


def _last_line_is_prompt(lines: list[str]) -> bool:
    """Check if the last non-empty line looks like a prompt waiting for input."""
    for line in reversed(lines):
        stripped = line.strip()
        if not stripped:
            continue
        for pattern in _IDLE_PROMPT_PATTERNS:
            if stripped.startswith(pattern) or stripped == pattern.rstrip():
                return True
        return False
    return False


class IdleDetector:
    def __init__(self, idle_timeout: float):
        self.idle_timeout = idle_timeout
        self._content_hash: dict[int, str] = {}
        self._stable_since: dict[int, float] = {}
        self._is_idle: dict[int, bool] = {}

    def update(self, agent_id: int, shell_pid: int, lines: list[str]) -> None:
        now = time.monotonic()

        tree = check_process_tree(shell_pid)

        # Fast path: agent has subprocesses — definitely busy
        if tree == ProcessTree.GRANDCHILDREN:
            self._reset(agent_id)
            return

        # Fast path: agent exited — definitely idle
        if tree == ProcessTree.NO_CHILDREN:
            self._is_idle[agent_id] = True
            return

        # Ambiguous: agent alive, no grandchildren
        # Check content stability
        content = "\n".join(lines)
        content_hash = hashlib.md5(content.encode()).hexdigest()
        prev_hash = self._content_hash.get(agent_id)
        self._content_hash[agent_id] = content_hash

        if content_hash != prev_hash:
            # Content changed — reset stability timer
            self._stable_since[agent_id] = now
            self._is_idle[agent_id] = False
            return

        # Content is stable — check if stable long enough AND prompt visible
        stable_since = self._stable_since.get(agent_id, now)
        if agent_id not in self._stable_since:
            self._stable_since[agent_id] = now

        elapsed = now - stable_since
        if elapsed >= self.idle_timeout and _last_line_is_prompt(lines):
            self._is_idle[agent_id] = True
        else:
            self._is_idle[agent_id] = False

    def is_idle(self, agent_id: int) -> bool:
        return self._is_idle.get(agent_id, False)

    def remove_agent(self, agent_id: int) -> None:
        self._content_hash.pop(agent_id, None)
        self._stable_since.pop(agent_id, None)
        self._is_idle.pop(agent_id, None)

    def _reset(self, agent_id: int) -> None:
        self._stable_since.pop(agent_id, None)
        self._is_idle[agent_id] = False


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
                    detector.update(agent.id, agent.pid, content.split("\n"))

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
