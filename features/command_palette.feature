Feature: Command palette
  As a user with many agents and commands
  I want a fuzzy-finder that surfaces both
  So that I can jump anywhere without leaving the keyboard

  Background:
    Given the aque desk is open
    And the following agents exist:
      | label   | state   |
      | alpha   | running |
      | bravo   | waiting |
      | charlie | on_hold |

  Scenario: Pressing ctrl+k opens the palette
    When the dashboard loads
    And the user presses "ctrl+k"
    Then the command palette should be visible

  Scenario: Palette lists each agent as an attach item
    When the dashboard loads
    And the user presses "ctrl+k"
    Then the palette should contain an item labelled "Attach alpha"
    And the palette should contain an item labelled "Attach bravo"
    And the palette should not contain an item labelled "Peek bravo"

  Scenario: Typing filters the palette
    When the dashboard loads
    And the user presses "ctrl+k"
    And the palette receives the query "brav"
    Then the palette should contain an item labelled "Attach bravo"
    And the palette should not contain an item labelled "Attach alpha"

  Scenario: Selecting an attach item closes the palette and attaches
    When the dashboard loads
    And the user presses "ctrl+k"
    And the palette dispatches "Attach bravo"
    Then the command palette should be dismissed
    And the attach should target "bravo"

  Scenario: Pressing Escape closes the palette without acting
    When the dashboard loads
    And the user presses "ctrl+k"
    And the user presses Escape
    Then the command palette should be dismissed
