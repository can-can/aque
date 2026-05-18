"""Auto-responder: pair, nudge, cleanup logic.

Aque-side responsibilities for the auto-responder feature. The responder
agent itself does all reading and replying via its own toolbelt; this
module only handles creation, nudging, and cleanup of the paired agent.
"""
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

import libtmux

from aque.run import launch_agent
from aque.state import AgentInfo, AgentState, StateManager


def system_prompt(partner: AgentInfo) -> str:
    """Return the initial system-message text typed into the responder."""
    return (
        f"You are an auto-responder paired with tmux session "
        f"{partner.tmux_session} (id {partner.id}). When you receive "
        f"an 'AQUE:' nudge line, use\n"
        f"\n"
        f"  tmux capture-pane -p -t {partner.tmux_session}\n"
        f"\n"
        f"to read your partner's screen, decide what reply (if any) is "
        f"appropriate, then send it with\n"
        f"\n"
        f"  tmux send-keys -t {partner.tmux_session} \"<text>\" Enter\n"
        f"\n"
        f"Be conservative: if the situation is unclear or destructive, "
        f"do nothing and wait. Do not start unrelated work."
    )


def find_for(partner_id: int, agents: list[AgentInfo]) -> AgentInfo | None:
    """Return the responder paired with `partner_id`, or None."""
    for a in agents:
        if a.is_responder and a.partner_id == partner_id:
            return a
    return None


def create_for(
    partner: AgentInfo,
    config: dict,
    state_manager: StateManager,
    *,
    aque_dir: Path,
) -> int:
    """Spawn a responder tmux session paired with `partner`.

    Working dir defaults to `<aque_dir>/responders/<partner_id>/`. The
    default path is wiped-and-recreated to guarantee a clean slate on id
    reuse. An explicit `config['responder_dir']` override is left as-is —
    callers own that path.

    Returns the new responder's agent id.
    """
    if config.get("responder_dir"):
        working_dir = Path(config["responder_dir"])
    else:
        working_dir = Path(aque_dir) / "responders" / str(partner.id)
        if working_dir.exists():
            shutil.rmtree(working_dir)
        working_dir.mkdir(parents=True, exist_ok=True)

    label = f"resp({partner.id})"
    command = list(config["responder_command"])

    return launch_agent(
        command=command,
        working_dir=str(working_dir),
        label=label,
        state_manager=state_manager,
        prefix=config.get("session_prefix", "aque"),
        is_responder=True,
        partner_id=partner.id,
    )


def nudge(
    partner: AgentInfo,
    responder: AgentInfo,
    server: libtmux.Server,
    *,
    state_manager: StateManager,
) -> bool:
    """Type a one-line nudge into the responder's pane.

    No-op (returns False) when:
    - partner.auto_respond is False
    - responder is in FOCUSED state
    - responder's tmux session is missing

    On a successful nudge, updates partner.last_nudge_at and returns True.
    """
    if not partner.auto_respond:
        return False
    if responder.state == AgentState.FOCUSED:
        return False

    try:
        session = server.sessions.get(session_name=responder.tmux_session)
    except Exception:
        session = None
    if session is None:
        return False

    line = (
        f"AQUE: partner {partner.tmux_session} (id={partner.id}) is waiting. "
        f"Inspect with `tmux capture-pane` and reply."
    )
    try:
        session.active_pane.send_keys(line, enter=True)
    except Exception:
        return False

    # Persist last_nudge_at on the partner.
    now = datetime.now(timezone.utc).isoformat()
    with state_manager._locked():
        state = state_manager.load()
        for a in state.agents:
            if a.id == partner.id:
                a.last_nudge_at = now
        state_manager.save(state)

    return True


def cleanup(
    partner: AgentInfo,
    state_manager: StateManager,
    server: libtmux.Server,
    *,
    aque_dir: Path,
) -> None:
    """Remove the responder paired with `partner`, if any.

    - Kills the responder's tmux session (tolerates missing sessions).
    - Removes the responder's AgentInfo from state.
    - Removes the responder's working dir under ~/.aque/responders/<partner_id>/.
    """
    state = state_manager.load()
    responder = find_for(partner.id, state.agents)
    if responder is None:
        return

    try:
        session = server.sessions.get(session_name=responder.tmux_session)
        if session is not None:
            session.kill()
    except Exception:
        pass

    state_manager.remove_agent(responder.id)

    responder_dir = Path(aque_dir) / "responders" / str(partner.id)
    if responder_dir.exists():
        shutil.rmtree(responder_dir, ignore_errors=True)
