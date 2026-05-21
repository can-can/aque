Feature: Dashboard
  As a user managing multiple agents
  I want a dashboard that shows agent status and lets me interact with them
  So that I can efficiently manage my agent queue

  Background:
    Given the aque desk is open

  # ── Agent listing ──────────────────────────────────────────────

  Scenario: Agents are sorted by priority
    Given the following agents exist:
      | label   | state   |
      | builder | running |
      | fixer   | waiting |
      | helper  | on_hold |
    When the dashboard loads
    Then the agent list should be ordered:
      | label | state   |
      | fixer | waiting |
      | builder | running |
      | helper  | on_hold |

  Scenario: Done agents are hidden from the dashboard
    Given the following agents exist:
      | label   | state   |
      | builder | running |
      | old     | done    |
    When the dashboard loads
    Then the agent list should contain "builder"
    And the agent list should not contain "old"

  # ── Auto-focus / highlight ─────────────────────────────────────

  Scenario: First item is auto-highlighted on app start
    Given the following agents exist:
      | label   | state   |
      | builder | running |
      | fixer   | waiting |
    When the app mounts
    Then the agent list should have focus
    And the first item should be highlighted

  Scenario: First item is auto-highlighted when returning to dashboard
    Given the following agents exist:
      | label   | state   |
      | fixer   | waiting |
      | builder | running |
    And the user is on the new agent form
    When the user presses Escape
    Then the dashboard should be visible
    And the first item should be highlighted

  Scenario: Highlight resets to top on dashboard return
    Given the following agents exist:
      | label   | state   |
      | fixer   | waiting |
      | builder | running |
    And the user had "builder" highlighted
    When the user returns to the dashboard
    Then the highlighted agent should be "fixer"

  Scenario: Highlight is preserved during periodic refresh
    Given the following agents exist:
      | label   | state   |
      | fixer   | waiting |
      | builder | running |
    And the user has "builder" highlighted on the dashboard
    When the periodic refresh runs
    Then the highlighted agent should still be "builder"

  # ── Status bar ─────────────────────────────────────────────────

  Scenario: Status bar shows agent counts by state
    Given the following agents exist:
      | label | state   |
      | a     | running |
      | b     | running |
      | c     | waiting |
      | d     | on_hold |
    When the dashboard loads
    Then the status bar should show "2 running"
    And the status bar should show "1 waiting"
    And the status bar should show "1 on_hold"

  Scenario: Status bar shows done count from history
    Given 3 agents are in history
    When the dashboard loads
    Then the status bar should show "3 done"

  # ── Agent type display ──────────────────────────────────────────

  Scenario: Typed agent shows type tag in list
    Given the following agents exist:
      | label   | state   | agent_type |
      | builder | running | claude     |
    When the dashboard loads
    Then the agent list should show a "claude" type tag for "builder"

  Scenario: Untyped agent shows no type tag
    Given the following agents exist:
      | label   | state   | agent_type |
      | builder | running |            |
    When the dashboard loads
    Then the agent list should not show a type tag for "builder"

  # ── State-change row cue ──────────────────────────────────────

  Scenario: A row marks itself with a cue after its state changes
    Given the following agents exist:
      | label   | state   |
      | builder | running |
    When the dashboard loads
    And the monitor changes agent "builder" to "waiting"
    And the periodic refresh runs
    Then the agent row for "builder" should carry a change cue

  # ── Vendor type chip color ────────────────────────────────────

  Scenario: Type chip carries the vendor's accent color
    Given the following agents exist:
      | label   | state   | agent_type |
      | builder | running | claude     |
    When the dashboard loads
    Then the agent row for "builder" should be coloured with vendor "claude"

  # ── Empty status bar ──────────────────────────────────────────

  Scenario: Status bar shows "No agents" when state is empty
    When the dashboard loads
    Then the status bar should show "No agents"

  # ── Keyboard shortcuts ─────────────────────────────────────────

  Scenario: Press "n" to open new agent form
    Given the user is on the dashboard
    When the user presses "n"
    Then the new agent form should be visible

  Scenario: Press "k" to kill highlighted agent
    Given agent "builder" is highlighted on the dashboard
    When the user presses "k"
    Then agent "builder" should be moved to history

  Scenario: Press "h" to toggle hold on highlighted agent
    Given agent "builder" is running and highlighted
    When the user presses "h"
    Then agent "builder" should be in "on_hold" state

  Scenario: Press "h" on a held agent to resume it
    Given agent "builder" is on_hold and highlighted
    When the user presses "h"
    Then agent "builder" should be in "running" state

