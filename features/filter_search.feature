Feature: Filter and search the agent list
  As a user with many agents
  I want to filter by state and search by substring
  So that I can quickly drill into a specific agent without leaving the list

  Background:
    Given the aque desk is open
    And the following agents exist:
      | label   | state    | agent_type |
      | alpha   | running  | claude     |
      | bravo   | waiting  | aider      |
      | charlie | on_hold  |            |
      | delta   | exited   | codex      |

  # ── State filters via number keys ──────────────────────────────

  Scenario: Pressing "2" filters the list to waiting agents
    When the dashboard loads
    And the user presses "2"
    Then the agent list should contain "bravo"
    And the agent list should not contain "alpha"

  Scenario: Pressing the same filter key again clears the filter
    When the dashboard loads
    And the user presses "2"
    And the user presses "2"
    Then the agent list should contain "alpha"
    And the agent list should contain "bravo"

  Scenario: Pressing Escape clears the filter
    When the dashboard loads
    And the user presses "1"
    And the user presses Escape
    Then the agent list should contain "alpha"
    And the agent list should contain "bravo"

  # ── Inline search via "/" ─────────────────────────────────────

  Scenario: Pressing "/" focuses the search input
    When the dashboard loads
    And the user presses "/"
    Then the search input should be visible
    And the search input should have focus

  Scenario: Typing in the search input filters the list
    When the dashboard loads
    And the user opens search and types "brav"
    Then the agent list should contain "bravo"
    And the agent list should not contain "alpha"

  # ── Active filter indicator ───────────────────────────────────

  Scenario: Active filter is highlighted in the status bar
    When the dashboard loads
    And the user presses "1"
    Then the status bar should show "[●"

  # ── Combination ───────────────────────────────────────────────

  Scenario: Filter and search compose — both must match
    When the dashboard loads
    And the user presses "1"
    And the user opens search and types "alph"
    Then the agent list should contain "alpha"
    And the agent list should not contain "bravo"
    And the agent list should not contain "charlie"

  Scenario: Pressing Escape clears both the filter and the search query
    When the dashboard loads
    And the user presses "1"
    And the user opens search and types "alph"
    And the user presses Escape
    Then the agent list should contain "bravo"
    And the agent list should contain "charlie"
