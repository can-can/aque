Feature: Responder panel in preview pane
  As a user looking at an agent
  I want a structured panel showing its responder's state
  So that auto-response is a first-class concept, not a footnote

  Background:
    Given the aque desk is open

  Scenario: Agent with an active responder shows "RESPONDER · AUTO"
    Given agent "fixer" has a paired running responder
    And agent "fixer" is highlighted
    When the preview refreshes
    Then the preview pane should show "RESPONDER · AUTO"
    And the preview pane should show "session:"

  Scenario: Agent with auto_respond off shows "RESPONDER · PAUSED"
    Given agent "fixer" has a paired running responder with auto_respond off
    And agent "fixer" is highlighted
    When the preview refreshes
    Then the preview pane should show "RESPONDER · PAUSED"

  Scenario: Agent with no responder shows the empty state
    Given agent "fixer" is running and highlighted
    When the preview refreshes
    Then the preview pane should show "NO RESPONDER"

  Scenario: Selecting a responder shows the "responding for" view
    Given agent "fixer" has a paired running responder
    And the responder of "fixer" is highlighted
    When the preview refreshes
    Then the preview pane should show "RESPONDING FOR"
    And the preview pane should show "fixer"

  # ── Reply log + rules ─────────────────────────────────────────

  Scenario: Responder panel lists recent AQUE: nudges from the pane
    Given agent "fixer" has a paired running responder
    And the responder pane contains "AQUE: partner X waiting"
    And agent "fixer" is highlighted
    When the preview refreshes
    Then the preview pane should show "recent activity:"
    And the preview pane should show "partner X waiting"

  Scenario: Responder panel lists rules when a rules file exists
    Given agent "fixer" has a paired running responder
    And the responder for "fixer" has rules "auto-approve safe edits|escalate file deletions"
    And agent "fixer" is highlighted
    When the preview refreshes
    Then the preview pane should show "rules:"
    And the preview pane should show "auto-approve safe edits"
    And the preview pane should show "escalate file deletions"
