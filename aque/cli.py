import os
import shlex
import shutil
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from aque import responder
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
    agent_type: Optional[str] = typer.Option(None, "--type", help="Agent type for session capture (e.g. claude)"),
    pair_responder: bool = typer.Option(False, "--responder", help="Pair the agent with an auto-responder (default: off)."),
    responder_cmd: Optional[str] = typer.Option(None, "--responder-cmd", help="Override the responder command (only meaningful with --responder, shell-quoted)."),
    responder_dir: Optional[str] = typer.Option(None, "--responder-dir", help="Override the responder working directory (only meaningful with --responder)."),
    command: list[str] = typer.Argument(..., help="Agent command and arguments"),
) -> None:
    """Launch an agent in a managed tmux session."""
    if agent_type is not None:
        from aque.plugins import get_plugin
        plugin = get_plugin(agent_type)
        if plugin is None:
            console.print(f"[yellow]Warning: unknown agent type '{agent_type}', falling back to polling[/yellow]")
            agent_type = None

    config = load_config(AQUE_DIR)
    mgr = get_state_manager()
    agent_id = launch_agent(
        command=command,
        working_dir=dir,
        label=label,
        state_manager=mgr,
        prefix=config["session_prefix"],
        agent_type=agent_type,
    )

    if pair_responder:
        responder_config = dict(config)
        if responder_cmd is not None:
            responder_config["responder_command"] = shlex.split(responder_cmd)
        if responder_dir is not None:
            responder_config["responder_dir"] = responder_dir
        partner = mgr.load().get_agent(agent_id)
        responder.create_for(partner, responder_config, mgr, aque_dir=AQUE_DIR)

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
        AgentState.EXITED: "dim",
        AgentState.ON_HOLD: "magenta",
        AgentState.DONE: "red",
    }

    by_partner = {a.partner_id: a for a in state.agents if a.is_responder}

    def render_row(agent, indent_prefix=""):
        color = state_colors.get(agent.state, "white")
        table.add_row(
            str(agent.id),
            f"[{color}]{agent.state.value}[/{color}]",
            f"{indent_prefix}{agent.label}",
            agent.dir,
        )

    partner_ids = {a.id for a in state.agents if not a.is_responder}
    for partner in [a for a in state.agents if not a.is_responder]:
        render_row(partner)
        resp = by_partner.get(partner.id)
        if resp is not None:
            render_row(resp, indent_prefix="↳ ")

    # Orphan responders (partner missing) — render at the bottom.
    for resp in state.agents:
        if resp.is_responder and resp.partner_id not in partner_ids:
            render_row(resp, indent_prefix="↳ (orphan) ")

    console.print(table)


@app.command()
def kill(agent_id: int = typer.Argument(..., help="Agent ID to terminate")) -> None:
    """Terminate an agent and clean up its tmux session."""
    import libtmux
    from aque.history import HistoryManager

    mgr = get_state_manager()
    hmgr = HistoryManager(AQUE_DIR)
    agent = mgr.load().get_agent(agent_id)

    if agent is None:
        console.print(f"[red]Agent #{agent_id} not found.[/red]")
        raise typer.Exit(1)

    server = libtmux.Server()
    try:
        session = server.sessions.get(session_name=agent.tmux_session)
        if session:
            session.kill()
    except Exception:
        pass

    # If killing a partner, also clean up its responder.
    if not agent.is_responder:
        responder.cleanup(agent, mgr, server, aque_dir=AQUE_DIR)

    mgr.done_agent(agent_id, hmgr)
    console.print(f"[red]Agent #{agent_id} done — moved to history.[/red]")


@app.command()
def desk() -> None:
    """Open the desk TUI. Agents come to you."""
    if not shutil.which("tmux"):
        console.print("[red]tmux is not installed. Install it with: brew install tmux[/red]")
        raise typer.Exit(1)
    from aque.desk import DeskApp
    desk_app = DeskApp(aque_dir=AQUE_DIR)
    desk_app.run()
