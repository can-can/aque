def default_terminal_command(agent: dict) -> list[str]:
    """Attach the phone to the agent's tmux session via a grouped session.

    A grouped session (``new-session -t <target>``) shares the target's windows
    but is its own session. We chain ``set-window-option window-size smallest``
    so the shared window follows the smallest attached client (the phone) rather
    than a wider desk client; otherwise a full-screen TUI paints wider than the
    phone displays and overlaps itself. ``smallest`` is evaluated over the
    currently attached clients, so when the phone detaches the window returns to
    the desk's size automatically. ``-A`` attaches if the phone session exists;
    ``-D`` makes that attach exclusive -- any other client already on the phone
    session is detached, so a fresh attach from another device (or a stale or
    reconnecting one) takes over and the previous phone client's stream ends.
    Clients of the target session (the desk) are unaffected.

    Only one phone session exists per agent: ``-A`` reuses ``phone-<id>`` on
    every attach rather than spawning a new one, and ``destroy-unattached on``
    makes that session self-destruct once the phone leaves, so it never lingers
    in ``tmux ls``. It only shares the target's windows, so destroying it never
    touches the agent's own session or its work.

    The bare ``;`` element is a tmux command separator (we exec tmux directly,
    no shell, so it is passed literally and tmux splits commands on it).
    """
    target = agent["tmux_session"]
    group = f"phone-{agent['id']}"
    return [
        "tmux", "new-session", "-A", "-D", "-s", group, "-t", target,
        ";", "set-window-option", "-t", group, "window-size", "smallest",
        ";", "set-option", "-t", group, "destroy-unattached", "on",
    ]
