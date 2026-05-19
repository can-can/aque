Feature: Triage pill for waiting agents
  As a user managing an agent queue
  I want a calm, non-blocking notification when an agent needs me
  So that I can peek, attach, or snooze without losing the list context

  Background:
    Given the aque desk is open

  # ── Triage trigger ──────────────────────────────────────────────

  Scenario: Triage pill appears when returning to dashboard with a waiting agent
    Given agent "fixer" is in "waiting" state
    When the user returns to the dashboard
    Then a triage pill should appear
    And the triage pill should mention "fixer"

  Scenario: Triage pill appears when an agent transitions to waiting on the dashboard
    Given agent "builder" is in "running" state
    And the user is on the dashboard
    When the monitor changes agent "builder" to "waiting"
    And the periodic refresh runs
    Then a triage pill should appear
    And the triage pill should mention "builder"

  Scenario: No triage pill when there are no waiting agents
    Given all agents are in "running" state
    When the user returns to the dashboard
    Then no triage pill should appear

  # ── Triage actions ──────────────────────────────────────────────

  Scenario: Pressing Enter attaches to the triaged agent
    Given the triage pill is showing for agent "fixer"
    When the user presses Enter
    Then the user should be attached to agent "fixer"

  Scenario: Pressing Space peeks the triaged agent without attaching
    Given the triage pill is showing for agent "fixer"
    When the user presses Space
    Then the triage pill should be dismissed
    And agent "fixer" should still be in "waiting" state
    And the highlighted agent should be "fixer"

  Scenario: Pressing "s" snoozes the triaged agent
    Given the triage pill is showing for agent "fixer"
    When the user presses "s"
    Then the triage pill should be dismissed
    And the periodic refresh runs
    And no triage pill should appear

  Scenario: Pressing Escape snoozes the triaged agent
    Given the triage pill is showing for agent "fixer"
    When the user presses Escape
    Then the triage pill should be dismissed
    And the periodic refresh runs
    And no triage pill should appear

  # ── Selection / queue ───────────────────────────────────────────

  Scenario: Triage targets the top-priority waiting agent
    Given the following agents exist:
      | label   | state   | last_change_at          |
      | newer   | waiting | 2026-03-29T05:00:00+00  |
      | older   | waiting | 2026-03-29T04:00:00+00  |
    When the user returns to the dashboard
    Then the triage pill should mention "older"

  Scenario: Triage does not trigger when skip_attach is set
    Given the desk is opened with skip_attach=True
    And agent "fixer" is in "waiting" state
    When the user returns to the dashboard
    Then no triage pill should appear

  # ── Snooze decay ────────────────────────────────────────────────

  Scenario: Snooze decays when the agent transitions to waiting again
    Given the triage pill is showing for agent "fixer"
    When the user presses "s"
    And the monitor changes agent "fixer" to "running"
    And the monitor changes agent "fixer" to "waiting"
    And the periodic refresh runs
    Then a triage pill should appear
    And the triage pill should mention "fixer"
