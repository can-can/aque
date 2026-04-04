import re
import shlex
import shutil
from pathlib import Path

import libtmux
from libtmux.pane import Pane
from libtmux.test.retry import retry_until

from aque.state import AgentInfo, AgentState, StateManager

SHELL_PROMPT_RE = re.compile(r"[\$#%>➜❯→⟩›]\s*$")


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
    _wait_for_shell(pane)
    cmd_str = shlex.join(command)
    pane.send_keys(cmd_str, enter=True)

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
