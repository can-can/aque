Feature: Auto-attach countdown
  As a user managing an agent queue
  I want the desk to automatically attach to the next waiting agent
  So that I don't have to manually select and enter each waiting agent

  Background:
    Given the aque desk is open

  # ── Countdown trigger ──────────────────────────────────────────

  Scenario: Countdown modal appears when returning to dashboard with a waiting agent
    Given agent "fixer" is in "waiting" state
    When the user returns to the dashboard
    Then a countdown modal should appear
    And the modal should show "Attaching to fixer in 3s"

  Scenario: Countdown modal appears when an agent transitions to waiting on the dashboard
    Given agent "builder" is in "running" state
    And the user is on the dashboard
    When the monitor changes agent "builder" to "waiting"
    And the periodic refresh runs
    Then a countdown modal should appear
    And the modal should show "Attaching to builder"

  Scenario: No countdown when there are no waiting agents
    Given all agents are in "running" state
    When the user returns to the dashboard
    Then no countdown modal should appear

  # ── Countdown behavior ─────────────────────────────────────────

  Scenario: Countdown decrements each second
    Given the countdown modal is showing for agent "fixer"
    When 1 second passes
    Then the modal should show "in 2s"
    When 1 second passes
    Then the modal should show "in 1s"

  Scenario: Auto-attach triggers after countdown reaches zero
    Given the countdown modal is showing for agent "fixer"
    When 3 seconds pass
    Then the user should be attached to agent "fixer"
    And agent "fixer" should be in "focused" state

  Scenario: Pressing Escape cancels the countdown
    Given the countdown modal is showing for agent "fixer"
    When the user presses Escape
    Then the countdown modal should be dismissed
    And the user should remain on the dashboard
    And agent "fixer" should still be in "waiting" state

  # ── Edge cases ─────────────────────────────────────────────────

  Scenario: Only one countdown can be active at a time
    Given the countdown modal is showing for agent "fixer"
    When the periodic refresh detects another waiting agent "helper"
    Then no second countdown modal should appear
    And the existing countdown should continue

  Scenario: Countdown targets the top-priority waiting agent
    Given the following agents exist:
      | label   | state   | last_change_at          |
      | newer   | waiting | 2026-03-29T05:00:00+00  |
      | older   | waiting | 2026-03-29T04:00:00+00  |
    When the countdown modal appears
    Then the modal should show "Attaching to older"

  Scenario: Countdown does not trigger when skip_attach is set
    Given the desk is opened with skip_attach=True
    And agent "fixer" is in "waiting" state
    When the user returns to the dashboard
    Then no countdown modal should appear

  Scenario: Dashboard refreshes continue during countdown
    Given the countdown modal is showing for agent "fixer"
    When the periodic refresh runs
    Then the agent list should be updated
    And the status bar should be updated
