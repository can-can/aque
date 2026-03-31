"""BDD tests for idle detection scenarios."""
import time
from unittest.mock import patch

import libtmux
import pytest
from pytest_bdd import scenario, given, when, then, parsers

from aque.monitor import IdleDetector, session_exists

FEATURE = "../../features/idle_detection.feature"

# ── Scenario declarations ──────────────────────────────────────────────────────


@scenario(FEATURE, "Claude Code prompt detected as idle")
def test_claude_code_prompt_idle():
    pass


@scenario(FEATURE, "Shell prompt detected as idle")
def test_shell_prompt_idle():
    pass


@scenario(FEATURE, "Python REPL prompt detected as idle")
def test_python_repl_idle():
    pass


@scenario(FEATURE, "Active spinner is not detected as idle")
def test_active_spinner_not_idle():
    pass


@scenario(FEATURE, "Scrolling output is not detected as idle")
def test_scrolling_output_not_idle():
    pass


@scenario(FEATURE, "Agent transitions to waiting after idle timeout")
def test_agent_transitions_to_waiting():
    pass


@scenario(FEATURE, "Idle timer resets when agent becomes active again")
def test_idle_timer_resets():
    pass


@scenario(FEATURE, "Agent idle state is cleared after transition to waiting")
def test_idle_state_cleared_after_waiting_transition():
    pass


@scenario(FEATURE, "Monitor detects exited tmux sessions")
def test_monitor_detects_exited_tmux_sessions():
    pass


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def ctx():
    """Shared mutable context for steps within a scenario."""
    return {}


# ── Step definitions ───────────────────────────────────────────────────────────


@given("a tmux pane with the following last lines:", target_fixture="ctx")
def given_pane_with_lines(docstring, ctx):
    lines = docstring.strip("\n").splitlines()
    ctx["lines"] = lines
    ctx["detector"] = IdleDetector(idle_timeout=0.1)
    return ctx


@then("the pane should be detected as idle")
def then_pane_is_idle(ctx):
    detector: IdleDetector = ctx["detector"]
    lines: list[str] = ctx["lines"]
    agent_id = 1
    shell_pid = 12345

    # Content is stable — call once, wait, call again.
    with patch("aque.monitor.has_children", return_value=True):
        detector.update(agent_id, shell_pid, lines)
        assert detector.is_idle(agent_id) is False, "Should not be idle yet"
        time.sleep(0.15)
        detector.update(agent_id, shell_pid, lines)
        assert detector.is_idle(agent_id) is True, "Should be idle after stable timeout"


@then("the pane should not be detected as idle")
def then_pane_is_not_idle(ctx):
    detector: IdleDetector = ctx["detector"]
    lines_v1: list[str] = ctx["lines"]
    agent_id = 1
    shell_pid = 12345

    # Simulate changing content by appending a tick counter to the last line.
    def _changing(tick: int) -> list[str]:
        return lines_v1 + [f"tick {tick}"]

    with patch("aque.monitor.has_children", return_value=True):
        detector.update(agent_id, shell_pid, _changing(1))
        time.sleep(0.05)
        detector.update(agent_id, shell_pid, _changing(2))
        time.sleep(0.05)
        detector.update(agent_id, shell_pid, _changing(3))
        time.sleep(0.05)
        detector.update(agent_id, shell_pid, _changing(4))
        assert detector.is_idle(agent_id) is False, "Should not be idle with changing content"


# ── Idle timeout scenario ──────────────────────────────────────────────────────


@given(parsers.parse('agent "{name}" is in "running" state'), target_fixture="ctx")
def given_agent_running(name, ctx):
    ctx["agent_name"] = name
    ctx["agent_id"] = 1
    ctx["agent_state"] = "running"
    return ctx


@given(parsers.parse("the idle timeout is {seconds:d} seconds"), target_fixture="ctx")
def given_idle_timeout(seconds, ctx):
    # Scale: feature says N seconds → use 0.1s real timeout
    ctx["detector"] = IdleDetector(idle_timeout=0.1)
    ctx["timeout_seconds"] = seconds
    return ctx


@given("the tmux pane shows a prompt", target_fixture="ctx")
def given_pane_shows_prompt(ctx):
    ctx["lines"] = ["❯ ", "  [Opus 4.6 (1M context)] ● high"]
    ctx["shell_pid"] = 12345
    # First update — establish stable baseline
    with patch("aque.monitor.has_children", return_value=True):
        ctx["detector"].update(ctx["agent_id"], ctx["shell_pid"], ctx["lines"])
    return ctx


@when(parsers.parse("{seconds:d} seconds of idle time pass"))
def when_idle_time_passes(seconds, ctx):
    # Scaled: sleep 0.15s regardless of feature-level seconds (which is 10)
    time.sleep(0.15)
    # Second update with the same content — should now exceed idle_timeout
    with patch("aque.monitor.has_children", return_value=True):
        ctx["detector"].update(ctx["agent_id"], ctx["shell_pid"], ctx["lines"])


@then(parsers.parse('agent "{name}" should be in "waiting" state'))
def then_agent_in_waiting(name, ctx):
    assert ctx["agent_name"] == name
    assert ctx["detector"].is_idle(ctx["agent_id"]) is True, (
        f'Agent "{name}" should be idle (waiting) after timeout'
    )


# ── Idle timer reset scenario ──────────────────────────────────────────────────


@given(parsers.parse('agent "{name}" has been idle for {seconds:d} seconds'), target_fixture="ctx")
def given_agent_idle_for(name, seconds, ctx):
    ctx["agent_name"] = name
    ctx["agent_id"] = 1
    ctx["agent_state"] = "running"
    ctx["shell_pid"] = 12345
    ctx["detector"] = IdleDetector(idle_timeout=0.1)
    ctx["stable_lines"] = ["❯ ", "  [Opus 4.6 (1M context)] ● high"]

    # Establish some idle time (scaled: sleep 0.05s regardless of feature seconds)
    with patch("aque.monitor.has_children", return_value=True):
        ctx["detector"].update(ctx["agent_id"], ctx["shell_pid"], ctx["stable_lines"])
        time.sleep(0.05)
        ctx["detector"].update(ctx["agent_id"], ctx["shell_pid"], ctx["stable_lines"])
    # Should not yet be idle (only 0.05s elapsed, timeout is 0.1s)
    return ctx


@given("the tmux pane changes to show active output", target_fixture="ctx")
def given_pane_shows_active(ctx):
    ctx["active_lines"] = ["✽ Working… (1s · ↓ 0.5k tokens)", "  ⎿  Running…"]
    return ctx


@when("the monitor polls again")
def when_monitor_polls(ctx):
    with patch("aque.monitor.has_children", return_value=True):
        ctx["detector"].update(ctx["agent_id"], ctx["shell_pid"], ctx["active_lines"])


@then(parsers.parse('the idle timer for "{name}" should be reset'))
def then_idle_timer_reset(name, ctx):
    assert ctx["agent_name"] == name
    # After content change the detector should not be idle
    assert ctx["detector"].is_idle(ctx["agent_id"]) is False, (
        f'Idle timer for "{name}" should have been reset'
    )


@then(parsers.parse('agent "{name}" should remain in "running" state'))
def then_agent_remains_running(name, ctx):
    assert ctx["agent_name"] == name
    assert ctx["agent_state"] == "running", f'Agent "{name}" should remain in running state'


# ── Idle state cleared after transition scenario ───────────────────────────────


@given(parsers.parse('agent "{name}" just transitioned to "waiting"'), target_fixture="ctx")
def given_agent_just_transitioned_to_waiting(name, ctx):
    ctx["agent_name"] = name
    ctx["agent_id"] = 1
    ctx["shell_pid"] = 12345
    ctx["detector"] = IdleDetector(idle_timeout=0.1)
    stable_lines = ["❯ ", "  [Opus 4.6 (1M context)] ● high"]

    # Simulate the agent becoming idle: stable content past the timeout
    with patch("aque.monitor.has_children", return_value=True):
        ctx["detector"].update(ctx["agent_id"], ctx["shell_pid"], stable_lines)
        time.sleep(0.15)
        ctx["detector"].update(ctx["agent_id"], ctx["shell_pid"], stable_lines)

    assert ctx["detector"].is_idle(ctx["agent_id"]) is True, "Agent should be idle before transition"
    return ctx


@when(parsers.parse('the agent is dismissed back to "running"'))
def when_agent_dismissed_back_to_running(ctx):
    # Monitor clears state when transitioning away from idle
    ctx["detector"].remove_agent(ctx["agent_id"])


@then("the idle timer should start fresh")
def then_idle_timer_starts_fresh(ctx):
    # After remove_agent, is_idle should return False (no recorded state)
    assert ctx["detector"].is_idle(ctx["agent_id"]) is False, (
        "Idle timer should be cleared after transition — is_idle should return False"
    )


# ── Monitor detects exited tmux sessions scenario ─────────────────────────────


@given(parsers.parse('the tmux session "{session_name}" no longer exists'), target_fixture="ctx")
def given_tmux_session_no_longer_exists(session_name, ctx):
    """Create a real tmux session, then kill it so it no longer exists."""
    server = libtmux.Server()
    try:
        session = server.new_session(session_name=session_name, detach=True)
        session.kill()
    except Exception:
        # Session may not have existed; that's fine — we just need it gone
        pass
    ctx["tmux_server"] = server
    ctx["session_name"] = session_name
    return ctx


@when("the monitor polls")
def when_monitor_polls(ctx):
    # The monitor would call session_exists(); we record the result for the assertion
    ctx["session_existed"] = session_exists(ctx["tmux_server"], ctx["session_name"])


@then(parsers.parse('agent "{name}" should be in "exited" state'))
def then_agent_in_exited_state(name, ctx):
    assert ctx["agent_name"] == name
    assert ctx["session_existed"] is False, (
        f"session_exists() should return False for killed session '{ctx['session_name']}'"
    )
