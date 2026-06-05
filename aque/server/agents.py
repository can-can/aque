from aque.state import StateManager


def agents_payload(state_manager: StateManager) -> list[dict]:
    """Return the queue as wire dicts, excluding responder agents."""
    state = state_manager.load()
    return [
        {
            "id": a.id,
            "state": a.state.value,
            "label": a.label,
            "dir": a.dir,
            "agent_type": a.agent_type,
            "tmux_session": a.tmux_session,
        }
        for a in state.agents
        if not a.is_responder
    ]
