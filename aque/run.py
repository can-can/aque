import re
import shlex
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import libtmux
from libtmux.pane import Pane
from libtmux.test.retry import retry_until

from aque.state import AgentInfo, AgentState, StateManager

SHELL_PROMPT_RE = re.compile(r"[\$#%>➜❯→⟩›]\s*$")
_background_threads: list[threading.Thread] = []


def _sanitize_session_name(name: str) -> str:
    """Make a string safe for use as a tmux session name."""
    name = re.sub(r"[^a-zA-Z0-9_-]", "-", name)
    name = re.sub(r"-+", "-", name).strip("-")
    return name[:50]


def _wait_for_shell(pane: Pane, timeout: float = 5.0) -> None:
    """Block until a shell prompt appears in the pane."""
    def _check() -> bool:
        for line in reversed(pane.capture_pane()):
            stripped = line.strip()
            if stripped:
                return bool(SHELL_PROMPT_RE.search(stripped))
        return False

    retry_until(_check, seconds=timeout, raises=False)


def launch_agent(
    command: list[str],
    working_dir: str,
    label: str | None,
    state_manager: StateManager,
    prefix: str = "aque",
    background: bool = False,
    agent_type: str | None = None,
    is_responder: bool = False,
    partner_id: int | None = None,
    session_id: str | None = None,
) -> int:
    if label is None:
        dir_basename = Path(working_dir).name
        label = f"{command[0]} . {dir_basename}"

    agent_id = state_manager.next_id()
    sanitized_label = _sanitize_session_name(label)
    session_name = f"{prefix}-{sanitized_label}-{agent_id}"

    if not shutil.which("tmux"):
        raise RuntimeError(
            "tmux is not installed. Install it with: brew install tmux"
        )

    server = libtmux.Server()

    # Kill stale session with the same name if it exists
    existing = server.sessions.get(session_name=session_name, default=None)
    if existing:
        existing.kill()

    session = server.new_session(
        session_name=session_name,
        start_directory=working_dir,
        detach=True,
    )

    session.set_option("remain-on-exit", "on")

    pane = session.active_pane

    cmd_str = shlex.join(command)

    agent = AgentInfo(
        id=agent_id,
        tmux_session=session_name,
        label=label,
        dir=working_dir,
        command=command,
        state=AgentState.RUNNING,
        pid=int(pane.pane_pid),
        agent_type=agent_type,
        is_responder=is_responder,
        partner_id=partner_id,
        session_id=session_id,
    )
    state_manager.add_agent(agent)

    # Ensure signals directory exists for hook-based detection
    if agent_type is not None:
        signals_dir = state_manager.aque_dir / "signals"
        signals_dir.mkdir(exist_ok=True)

    def _finalize() -> None:
        try:
            _wait_for_shell(pane)
            if agent_type is not None:
                pane.send_keys(f"export AQUE_AGENT_ID={agent_id}", enter=True)
            pane.send_keys(cmd_str, enter=True)
        except Exception:
            pass

    if background:
        thread = threading.Thread(target=_finalize, daemon=True)
        thread.start()
        _background_threads.append(thread)
    else:
        _finalize()

    return agent_id


def relaunch_agent(
    agent_id: int,
    command: list[str],
    state_manager: StateManager,
    *,
    preserve_session_id: bool = True,
    prefix: str = "aque",
) -> None:
    """Re-launch an existing agent in place, reusing its ID.

    Creates a fresh tmux session and updates the AgentInfo's tmux_session,
    pid, command, state (=RUNNING), and last_change_at. Used by the orphan
    modal's Resume and Relaunch actions so the displayed agent ID stays
    stable across the operation.

    If preserve_session_id is False, clears session_id (caller is expected
    to have rewritten the command for a fresh conversation, e.g. via
    ClaudeCapturer.preassign).
    """
    agent = state_manager.load().get_agent(agent_id)
    if agent is None:
        raise KeyError(agent_id)

    if not shutil.which("tmux"):
        raise RuntimeError("tmux is not installed. Install it with: brew install tmux")

    sanitized_label = _sanitize_session_name(agent.label)
    session_name = f"{prefix}-{sanitized_label}-{agent_id}-r{int(time.monotonic())}"

    server = libtmux.Server()
    existing = server.sessions.get(session_name=session_name, default=None)
    if existing:
        existing.kill()

    session = server.new_session(
        session_name=session_name,
        start_directory=agent.dir,
        detach=True,
    )
    session.set_option("remain-on-exit", "on")
    pane = session.active_pane

    # Persist the new tmux state before sending keys so other readers see it.
    state = state_manager.load()
    for a in state.agents:
        if a.id == agent_id:
            a.tmux_session = session_name
            a.command = command
            a.state = AgentState.RUNNING
            a.pid = int(pane.pane_pid)
            a.last_change_at = datetime.now(timezone.utc).isoformat()
            if not preserve_session_id:
                a.session_id = None
            break
    state_manager.save(state)

    cmd_str = shlex.join(command)

    def _finalize() -> None:
        try:
            _wait_for_shell(pane)
            if agent.agent_type is not None:
                pane.send_keys(f"export AQUE_AGENT_ID={agent_id}", enter=True)
            pane.send_keys(cmd_str, enter=True)
        except Exception:
            pass

    thread = threading.Thread(target=_finalize, daemon=True)
    thread.start()
    _background_threads.append(thread)
