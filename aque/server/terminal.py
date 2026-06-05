def default_terminal_command(agent: dict) -> list[str]:
    """Placeholder; real grouped-attach command is added in Task 7."""
    return ["tmux", "attach", "-t", agent["tmux_session"]]
