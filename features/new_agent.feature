Feature: New agent creation
  As a user wanting to launch a new agent
  I want a multi-step form to configure the agent
  So that I can set the working directory, command, and label

  Background:
    Given the aque desk is open
    And the user is on the dashboard

  # ── Form navigation ────────────────────────────────────────────

  Scenario: Opening the new agent form
    When the user presses "n"
    Then the new agent form should be visible
    And step "1/3: Select working directory" should be shown
    And the directory tree should have focus

  Scenario: Selecting a directory advances to command step
    Given the user is on the directory selection step
    And the user has navigated to "/Users/cancan/Projects/myapp"
    When the user presses "s"
    Then step "2/3: Enter command" should be shown
    And the command input should have focus

  Scenario: Entering a command advances to label step
    Given the user is on the command step
    When the user types "claude --model opus" and presses Enter
    Then step "3/3: Label" should be shown
    And the label input should have focus
    And the label input should contain a default label "claude . myapp"

  Scenario: Submitting the label launches the agent
    Given the user is on the label step
    And the label is "my-agent"
    When the user presses Enter
    Then a new tmux session should be created
    And the agent should appear in the state file
    And the user should be attached to the new agent

  # ── Cancellation ───────────────────────────────────────────────

  Scenario: Pressing Escape on directory step cancels the form
    Given the user is on the directory selection step
    When the user presses Escape
    Then the dashboard should be visible
    And no agent should be created

  Scenario: Pressing Escape on command step cancels the form
    Given the user is on the command step
    When the user presses Escape
    Then the dashboard should be visible
    And no agent should be created

  Scenario: Pressing Escape on label step cancels the form
    Given the user is on the label step
    When the user presses Escape
    Then the dashboard should be visible
    And no agent should be created

  # ── Directory tree ─────────────────────────────────────────────

  Scenario: Directory tree hides hidden directories
    Given the directory tree is showing
    And the current directory contains ".git" and "src"
    Then the directory tree should show "src"
    And the directory tree should not show ".git"
