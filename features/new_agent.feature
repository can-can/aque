Feature: New agent creation
  As a user wanting to launch a new agent
  I want a multi-step form to configure the agent
  So that I can set the working directory, command, and label

  Background:
    Given the aque desk is open
    And the user is on the dashboard

  # ── Form navigation ────────────────────────────────────────────

  Scenario: Opening the new agent form shows the directory picker
    When the user presses "n"
    Then the directory picker should be visible
    And the search input should have focus
    And step "1/3: Select working directory" should be shown

  Scenario: Picker shows pinned directories at the top
    Given the following directories are pinned:
      | path                          |
      | ~/Projects/aque               |
      | ~/Projects/redak              |
    When the user opens the new agent form
    Then the picker should show "~/Projects/aque" in the pinned section
    And "~/Projects/aque" should appear before "~/Projects/redak"

  Scenario: Picker shows recent directories ranked by frequency
    Given the following directory history exists:
      | path                          | count | last_used           |
      | ~/Projects/safebot            | 12    | 2026-03-28T10:00:00 |
      | ~/Projects/ha-config          | 8     | 2026-03-27T15:30:00 |
    When the user opens the new agent form
    Then "~/Projects/safebot" should appear before "~/Projects/ha-config" in the recent section

  Scenario: Deleted directories are not shown
    Given "~/Projects/old-project" is in the directory history
    And "~/Projects/old-project" no longer exists on disk
    When the user opens the new agent form
    Then "~/Projects/old-project" should not appear in the picker

  Scenario: Selecting a directory from the list advances to command step
    Given the user is on the directory picker
    And "~/Projects/aque" is highlighted
    When the user presses Enter
    Then step "2/3: Enter command" should be shown
    And the command input should have focus

  Scenario: Selecting a directory records usage in history
    Given the user is on the directory picker
    When the user selects "~/Projects/aque"
    And completes the agent creation
    Then the usage count for "~/Projects/aque" should be incremented
    And the last_used timestamp should be updated

  # ── Search ─────────────────────────────────────────────────────

  Scenario: Typing filters the list by substring match
    Given the user is on the directory picker
    And the following directory history exists:
      | path                          | count |
      | ~/Projects/safebot            | 12    |
      | ~/Projects/ha-config          | 8     |
      | ~/Projects/aque               | 5     |
    When the user types "safe" in the search input
    Then only "~/Projects/safebot" should be visible in the list

  Scenario: Search scans filesystem when history has few matches
    Given "~/Projects/new-experiment" exists on disk
    And "~/Projects/new-experiment" is not in the directory history
    When the user types "new-exp" in the search input
    Then "~/Projects/new-experiment" should appear in the results

  Scenario: Clearing search restores full pinned and recent list
    Given the user has typed "safe" in the search input
    When the user clears the search input
    Then the full pinned and recent list should be visible

  # ── Pinning ────────────────────────────────────────────────────

  Scenario: Pinning a directory from the recent list
    Given "~/Projects/safebot" is in the recent list
    And "~/Projects/safebot" is highlighted
    When the user presses "p"
    Then "~/Projects/safebot" should move to the pinned section

  Scenario: Unpinning a directory
    Given "~/Projects/aque" is pinned
    And "~/Projects/aque" is highlighted
    When the user presses "p"
    Then "~/Projects/aque" should be removed from the pinned section
    And "~/Projects/aque" should appear in the recent section

  Scenario: Pinned directories always appear above recent directories
    Given "~/Projects/aque" is pinned with usage count 2
    And "~/Projects/safebot" is not pinned with usage count 50
    Then "~/Projects/aque" should appear above "~/Projects/safebot"

  # ── Tree fallback ──────────────────────────────────────────────

  Scenario: Switching to tree browse mode
    Given the user is on the directory picker
    When the user presses "b"
    Then the directory tree should be visible
    And the tree should be rooted at the default_dir

  Scenario: Tree hides hidden directories
    Given the tree browser is showing
    And the current directory contains ".git" and "src"
    Then the directory tree should show "src"
    And the directory tree should not show ".git"

  Scenario: Selecting a directory in tree mode advances to command step
    Given the tree browser is showing
    And the user has navigated to "~/Projects/myapp"
    When the user presses "s"
    Then step "2/3: Enter command" should be shown

  Scenario: Returning from tree to picker
    Given the tree browser is showing
    When the user presses Escape
    Then the directory picker should be visible again
    And the search input should have focus

  # ── Command and label steps (unchanged) ────────────────────────

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

  Scenario: Pressing Escape on directory picker cancels the form
    Given the user is on the directory picker
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

  # ── CLI integration ────────────────────────────────────────────

  Scenario: CLI launch records directory usage
    When the user runs "aque run --dir ~/Projects/myapp -- claude"
    Then the usage count for "~/Projects/myapp" should be incremented in dir_history.json

  # ── First-time experience ──────────────────────────────────────

  Scenario: Empty state shows search input and hint
    Given no dir_history.json exists
    When the user opens the new agent form
    Then the search input should have focus
    And the pinned section should be empty
    And the recent section should be empty
