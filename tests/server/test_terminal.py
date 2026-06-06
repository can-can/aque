from aque.server.terminal import default_terminal_command


def test_command_uses_grouped_session_targeting_the_agent():
    cmd = default_terminal_command(
        {"id": 7, "tmux_session": "aque-7"}
    )
    assert cmd[0] == "tmux"
    assert "new-session" in cmd
    # grouped session is named after the agent and targets its session
    assert "phone-7" in cmd
    assert "aque-7" in cmd
    # -t targets the existing agent session to share its windows
    assert cmd[cmd.index("-t") + 1] == "aque-7"


def test_command_forces_window_to_follow_smallest_client():
    # The shared window must follow the phone (smallest client), or a wide desk
    # client makes a TUI paint wider than the phone shows -> garbled overlap.
    cmd = default_terminal_command({"id": 7, "tmux_session": "aque-7"})
    assert "window-size" in cmd
    assert "smallest" in cmd
    # the option is chained after the grouped attach (separated by a tmux ';')
    assert ";" in cmd
    assert cmd[cmd.index("window-size") + 1] == "smallest"
