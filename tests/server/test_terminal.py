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
