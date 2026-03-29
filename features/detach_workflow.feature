Feature: Detach workflow
  As a user attaching to agent tmux sessions
  I want detaching to be fast and automatic
  So that I can quickly move between agents without extra menu steps

  Background:
    Given the aque desk is open

  # ── Auto-dismiss on detach ─────────────────────────────────────

  Scenario: Detaching from a running agent auto-dismisses to dashboard
    Given agent "builder" is in "focused" state
    When the user detaches from the tmux session
    Then agent "builder" should be in "running" state
    And the dashboard should be visible
    And no action menu should be shown

  Scenario: Detaching from an exited agent auto-marks it as done
    Given agent "builder" is in "exited" state
    When the user detaches from the tmux session
    Then agent "builder" should be moved to history
    And the dashboard should be visible

  Scenario: Agent state is preserved if changed during attachment
    Given agent "builder" is in "focused" state
    And the monitor changes agent "builder" to "waiting" during the session
    When the user detaches from the tmux session
    Then agent "builder" should remain in "waiting" state
    And the dashboard should be visible

  # ── Dashboard return after detach ──────────────────────────────

  Scenario: Dashboard highlight resets to top waiting agent after detach
    Given the following agents exist:
      | label   | state   |
      | fixer   | waiting |
      | builder | running |
    And the user was attached to "builder"
    When the user detaches from the tmux session
    Then the highlighted agent should be "fixer"

  Scenario: Monitor is restarted on dashboard return if needed
    Given the monitor daemon has died
    And the user was attached to an agent
    When the user detaches and returns to the dashboard
    Then the monitor daemon should be running
