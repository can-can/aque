import os
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from aque.config import load_config
from aque.dir_history import DirHistoryManager
from aque.monitor import start_monitor_daemon, stop_monitor
from aque.run import launch_agent
from aque.state import AgentState, StateManager

app = typer.Typer(help="Aque — a tmux-based agent queue manager.")
console = Console()

AQUE_DIR = Path.home() / ".aque"


@app.callback()
def main(
    aque_dir: Optional[str] = typer.Option(None, "--aque-dir", help="Aque state directory (default: ~/.aque)"),
) -> None:
    global AQUE_DIR
    if aque_dir:
        AQUE_DIR = Path(aque_dir)
        AQUE_DIR.mkdir(parents=True, exist_ok=True)


def get_state_manager() -> StateManager:
    return StateManager(AQUE_DIR)


def ensure_monitor_running() -> None:
    mgr = get_state_manager()
    state = mgr.load()
    if state.monitor_pid:
        try:
            os.kill(state.monitor_pid, 0)
            return
        except ProcessLookupError:
            state.monitor_pid = None
            mgr.save(state)
    start_monitor_daemon(AQUE_DIR)


@app.command()
def run(
    dir: str = typer.Option(..., "--dir", help="Working directory for the agent"),
    label: Optional[str] = typer.Option(None, "--label", help="Human-readable label"),
    command: list[str] = typer.Argument(..., help="Agent command and arguments"),
) -> None:
    """Launch an agent in a managed tmux session."""
    config = load_config(AQUE_DIR)
    mgr = get_state_manager()
    agent_id = launch_agent(
        command=command,
        working_dir=dir,
        label=label,
        state_manager=mgr,
        prefix=config["session_prefix"],
    )
    dir_history_mgr = DirHistoryManager(AQUE_DIR)
    dir_history_mgr.record_use(dir)
    ensure_monitor_running()
    console.print(f"[green]Agent #{agent_id} launched[/green]: {label or command[0]}")


@app.command(name="list")
def list_agents() -> None:
    """Show all managed agents and their states."""
    mgr = get_state_manager()
    state = mgr.load()

    if not state.agents:
        console.print("[dim]No agents running.[/dim]")
        return

    table = Table()
    table.add_column("ID", style="bold")
    table.add_column("STATE")
    table.add_column("LABEL")
    table.add_column("DIR")

    state_colors = {
        AgentState.RUNNING: "green",
        AgentState.WAITING: "yellow",
        AgentState.FOCUSED: "blue",
        AgentState.EXITED: "dim",
        AgentState.ON_HOLD: "magenta",
        AgentState.DONE: "red",
    }

    for agent in state.agents:
        color = state_colors.get(agent.state, "white")
        table.add_row(
            str(agent.id),
            f"[{color}]{agent.state.value}[/{color}]",
            agent.label,
            agent.dir,
        )

    console.print(table)


@app.command()
def kill(agent_id: int = typer.Argument(..., help="Agent ID to terminate")) -> None:
    """Terminate an agent and clean up its tmux session."""
    import libtmux
    from aque.history import HistoryManager

    mgr = get_state_manager()
    hmgr = HistoryManager(AQUE_DIR)
    state = mgr.load()
    agent = next((a for a in state.agents if a.id == agent_id), None)

    if agent is None:
        console.print(f"[red]Agent #{agent_id} not found.[/red]")
        raise typer.Exit(1)

    try:
        server = libtmux.Server()
        session = server.sessions.get(session_name=agent.tmux_session)
        if session:
            session.kill()
    except Exception:
        pass

    mgr.done_agent(agent_id, hmgr)
    console.print(f"[red]Agent #{agent_id} done — moved to history.[/red]")


@app.command()
def desk() -> None:
    """Open the desk TUI. Agents come to you."""
    from aque.desk import DeskApp
    desk_app = DeskApp(aque_dir=AQUE_DIR)
    desk_app.run()
