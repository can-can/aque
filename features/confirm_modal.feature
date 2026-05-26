Feature: Confirmation modal for destructive actions
  As a user about to do something destructive (e.g. kill an agent)
  I want a clear yes/no prompt that's safe by default
  So that a stray Enter can't accidentally trigger the action

  Background:
    Given a confirm modal is pushed with prompt "Kill agent?"

  Scenario: Pressing y confirms the destructive action
    When the user presses "y"
    Then the confirm modal should dismiss with result True

  Scenario: Pressing n cancels the destructive action
    When the user presses "n"
    Then the confirm modal should dismiss with result False

  Scenario: Pressing Escape cancels the destructive action
    When the user presses Escape
    Then the confirm modal should dismiss with result False

  Scenario: Cancel button is focused by default so a stray Enter is safe
    Then the focused button id should be "confirm-no"
