Feature: Quick Launch
  As a user re-running familiar agents
  I want to relaunch a recent task in one keystroke
  So that I don't retype the new-agent wizard

  Background:
    Given the aque desk is open

  Scenario: Pressing r with no history shows an empty state
    Given the history has no tasks
    When the user presses "r"
    Then the quick launch form should be visible
    And the quick launch form should show "No recent tasks yet"

  Scenario: Pressing r lists recent tasks
    Given the history has a recent "claude" task in "/tmp/api" labeled "claude . api"
    When the user presses "r"
    Then the quick launch form should be visible
    And the quick launch list should contain "claude . api"

  Scenario: Pressing Escape on the quick launch form returns to the dashboard
    Given the history has a recent "claude" task in "/tmp/api" labeled "claude . api"
    When the user presses "r"
    And the user presses Escape
    Then the dashboard should be visible
