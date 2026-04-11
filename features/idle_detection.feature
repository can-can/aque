Feature: Idle detection
  As the aque monitoring system
  I want to detect when agents are idle (waiting for user input)
  So that agents can be transitioned to "waiting" state for the queue

  # ── Prompt-based detection ─────────────────────────────────────

  Scenario: Claude Code prompt detected as idle
    Given a tmux pane with the following last lines:
      """
      ───────────────────────────────────────
      ❯
      ───────────────────────────────────────
        [Opus 4.6 (1M context)] ● high
      """
    Then the pane should be detected as idle

  Scenario: Shell prompt detected as idle
    Given a tmux pane with the following last lines:
      """
      user@host:~/project$
      """
    Then the pane should be detected as idle

  Scenario: Python REPL prompt detected as idle
    Given a tmux pane with the following last lines:
      """
      >>>
      """
    Then the pane should be detected as idle

  Scenario: Active spinner is not detected as idle
    Given a tmux pane with the following last lines:
      """
      ✽ Working… (41s · ↓ 1.0k tokens)
        ⎿  Running…
      """
    Then the pane should not be detected as idle

  Scenario: Scrolling output is not detected as idle
    Given a tmux pane with the following last lines:
      """
      Line 1 of output
      Line 2 of output
      Line 3 of output
      """
    Then the pane should not be detected as idle

  # ── Idle timeout ───────────────────────────────────────────────

  Scenario: Agent transitions to waiting after idle timeout
    Given agent "builder" is in "running" state
    And the idle timeout is 10 seconds
    And the tmux pane shows a prompt
    When 10 seconds of idle time pass
    Then agent "builder" should be in "waiting" state

  Scenario: Idle timer resets when agent becomes active again
    Given agent "builder" has been idle for 5 seconds
    And the tmux pane changes to show active output
    When the monitor polls again
    Then the idle timer for "builder" should be reset
    And agent "builder" should remain in "running" state

  # ── Monitor detects session death ─────────────────────────────

  Scenario: Monitor detects exited tmux sessions
    Given agent "builder" is in "running" state
    And the tmux session "aque-builder-1" no longer exists
    When the monitor polls
    Then agent "builder" should be in "exited" state

  Scenario: Agent idle state is cleared after transition to waiting
    Given agent "builder" just transitioned to "waiting"
    When the agent is dismissed back to "running"
    Then the idle timer should start fresh

  # ── Signal-based detection (hook-based agents) ────────────────

  Scenario: Signal file triggers immediate waiting transition
    Given agent "builder" is running with type "claude"
    And a signal file exists for agent "builder"
    When the monitor checks signal files
    Then agent "builder" should be in "waiting" state
    And the signal file should be consumed

  Scenario: Signal file detection skips agents without a type
    Given agent "builder" is running without a type
    And a signal file exists for agent "builder"
    When the monitor checks signal files
    Then agent "builder" should be in "waiting" state
    And the signal file should be consumed

  Scenario: Stale signal files are cleaned up on monitor startup
    Given agent "builder" no longer exists in state
    And a stale signal file exists for agent id 99
    When the monitor starts up
    Then the stale signal file for agent id 99 should be removed

  Scenario: Agent without type falls back to content-hash polling
    Given agent "builder" is running without a type
    And no signal file exists for agent "builder"
    And the tmux pane shows a prompt
    When the idle timeout elapses
    Then agent "builder" should be detected as idle via polling

