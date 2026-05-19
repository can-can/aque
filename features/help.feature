Feature: Keyboard shortcut help overlay
  As a user new to the desk
  I want a quick reference for every binding
  So that I don't have to memorise the footer hints

  Background:
    Given the aque desk is open

  Scenario: Pressing "?" opens the help overlay
    When the user presses "?"
    Then the help modal should be visible

  Scenario: Help modal lists the core actions
    When the user presses "?"
    Then the help modal should mention "new agent"
    And the help modal should mention "command palette"
    And the help modal should mention "undo last action"

  Scenario: Pressing Escape closes the help overlay
    Given the help modal is open
    When the user presses Escape
    Then the help modal should be dismissed

  Scenario: Pressing "?" again closes the help overlay
    Given the help modal is open
    When the user presses "?"
    Then the help modal should be dismissed
