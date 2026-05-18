"""Auto-responder: pair, nudge, cleanup logic.

Aque-side responsibilities for the auto-responder feature. The responder
agent itself does all reading and replying via its own toolbelt; this
module only handles creation, nudging, and cleanup of the paired agent.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from aque.run import launch_agent
from aque.state import AgentInfo, StateManager


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

    Working dir defaults to `<aque_dir>/responders/<partner_id>/` unless
    `config['responder_dir']` overrides it. Existing dirs are wiped to
    guarantee a clean slate on id reuse.

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
