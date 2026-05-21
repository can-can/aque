Feature: Auto-responder
  As a user managing multiple agents in the queue
  I want a paired responder agent to nudge waiting agents on my behalf
  So that sessions unstick themselves without my attention

  # ── Pairing creation ───────────────────────────────────────────

  Scenario: New agent auto-creates a paired responder
    When a new agent "builder" is launched
    Then a responder agent paired to "builder" should exist
    And the responder should have is_responder=true
    And the responder's partner_id should equal "builder"'s id

  Scenario: --no-responder skips pairing
    When a new agent "builder" is launched with --no-responder
    Then no responder agent paired to "builder" should exist

  Scenario: Responders do not get their own responders
    Given agent "builder" exists with a paired responder "resp(builder)"
    Then no responder agent paired to "resp(builder)" should exist

  Scenario: Global responder_enabled=false skips creation for all launches
    Given config has responder_enabled set to false
    When a new agent "builder" is launched
    Then no responder agent paired to "builder" should exist

  # ── Nudge flow ─────────────────────────────────────────────────

  Scenario: Partner going waiting nudges its responder after idle gap
    Given agent "builder" has a paired responder "resp(builder)"
    And the responder_idle_gap is 5 seconds
    When agent "builder" transitions to "waiting"
    And 5 seconds pass with "builder" still in "waiting"
    Then the responder "resp(builder)" should receive exactly one nudge
    And "builder"'s last_nudge_at should be updated

  Scenario: No nudge before idle gap elapses
    Given agent "builder" has a paired responder "resp(builder)"
    And the responder_idle_gap is 30 seconds
    When agent "builder" transitions to "waiting"
    And 5 seconds pass with "builder" still in "waiting"
    Then the responder "resp(builder)" should receive no nudge

  Scenario: Re-nudge after another idle gap without a reply
    Given agent "builder" has a paired responder "resp(builder)"
    And the responder_idle_gap is 5 seconds
    And "builder" has been nudged 5 seconds ago and is still "waiting"
    When the monitor polls
    Then the responder "resp(builder)" should receive another nudge

  Scenario: Partner unsticking before responder replies stops re-nudges
    Given agent "builder" has been nudged and is in "waiting"
    When agent "builder" transitions back to "running"
    Then no additional nudge should fire on the next monitor poll

  # ── Kill-switch ────────────────────────────────────────────────

  Scenario: auto_respond=false suppresses nudges
    Given agent "builder" has a paired responder "resp(builder)"
    And "builder"'s auto_respond flag is false
    When agent "builder" transitions to "waiting"
    And the responder_idle_gap elapses
    Then the responder "resp(builder)" should receive no nudge

  Scenario: Dashboard "a" key toggles auto_respond on selected partner
    Given agent "builder" is highlighted on the dashboard
    And "builder"'s auto_respond flag is true
    When the user presses "a"
    Then "builder"'s auto_respond flag should be false

  Scenario: Dashboard "a" key is a no-op on a responder selection
    Given responder "resp(builder)" is highlighted on the dashboard
    When the user presses "a"
    Then no auto_respond flag should change

  # ── Visibility ─────────────────────────────────────────────────

  Scenario: Responders are hidden from the default dashboard list
    Given agent "builder" has a paired responder "resp(builder)"
    When the dashboard renders the agent list
    Then "builder" should appear in the list
    And "resp(builder)" should not appear in the list

  Scenario: Pressing R toggles responder visibility
    Given agent "builder" has a paired responder "resp(builder)"
    When the user presses "R" on the dashboard
    Then "resp(builder)" should appear in the list indented under "builder"

  Scenario: Auto-attach countdown skips responders
    Given responder "resp(builder)" is the highest-priority waiting agent
    When the auto-attach picker selects a target
    Then "resp(builder)" should not be selected

  # ── Cleanup ────────────────────────────────────────────────────

  Scenario: Killing the partner cleans up its responder
    Given agent "builder" has a paired responder "resp(builder)"
    When the user presses "k" with "builder" highlighted
    Then "builder" should be moved to history
    And "resp(builder)"'s tmux session should be killed
    And "resp(builder)" should be removed from state

  Scenario: Responder exits unexpectedly does not stop the partner
    Given agent "builder" has a paired responder "resp(builder)"
    When "resp(builder)"'s tmux session is killed externally
    And the monitor polls
    Then "resp(builder)" should be in "exited" state
    And agent "builder" should remain in its previous state
