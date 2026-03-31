import re
import shlex
import shutil
from pathlib import Path

import libtmux

from aque.state import AgentInfo, AgentState, StateManager


def _sanitize_session_name(name: str) -> str:
    """Make a string safe for use as a tmux session name."""
    name = re.sub(r"[^a-zA-Z0-9_-]", "-", name)
    name = re.sub(r"-+", "-", name).strip("-")
    return name[:50]


def launch_agent(
    command: list[str],
    working_dir: str,
    label: str | None,
    state_manager: StateManager,
    prefix: str = "aque",
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

    cmd_str = shlex.join(command)
    session = server.new_session(
        session_name=session_name,
        start_directory=working_dir,
        window_command=cmd_str,
        detach=True,
    )

    session.set_option("remain-on-exit", "on")

    pane = session.active_pane

    agent = AgentInfo(
        id=agent_id,
        tmux_session=session_name,
        label=label,
        dir=working_dir,
        command=command,
        state=AgentState.RUNNING,
        pid=int(pane.pane_pid),
    )
    state_manager.add_agent(agent)

    return agent_id
