def default_terminal_command(agent: dict) -> list[str]:
    """Attach the phone to the agent's tmux session via a grouped session.

    A grouped session (``new-session -t <target>``) shares the target's
    windows but has its own size, so the phone's screen dimensions don't
    shrink the user's desk view. ``-A`` attaches if the phone session
    already exists instead of erroring.
    """
    target = agent["tmux_session"]
    group = f"phone-{agent['id']}"
    return ["tmux", "new-session", "-A", "-s", group, "-t", target]
