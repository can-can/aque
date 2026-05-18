"""Auto-responder: pair, nudge, cleanup logic.

Aque-side responsibilities for the auto-responder feature. The responder
agent itself does all reading and replying via its own toolbelt; this
module only handles creation, nudging, and cleanup of the paired agent.
"""
from __future__ import annotations

from aque.state import AgentInfo


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
