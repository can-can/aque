Feature: Undo a destructive action
  As a user who sometimes presses "k" too quickly
  I want a short window to undo a kill or done action
  So that I can recover from a mistake without restarting the workflow

  Background:
    Given the aque desk is open

  # ── Undo bar appearance ─────────────────────────────────────────

  Scenario: Undo bar appears after killing an agent
    Given agent "fixer" is running and highlighted
    When the user presses "k"
    And the user presses "y"
    Then the undo bar should be visible
    And the undo bar should mention "fixer"

  # ── Undo restores the agent ─────────────────────────────────────

  Scenario: Pressing "u" restores a killed agent
    Given agent "fixer" is running and highlighted
    When the user presses "k"
    And the user presses "y"
    And the user presses "u"
    Then the undo bar should be dismissed
    And the active agents should include "fixer"

  Scenario: After undo, the history count returns to its prior value
    Given 0 agents are in history
    And agent "fixer" is running and highlighted
    When the user presses "k"
    And the user presses "y"
    Then the history should contain 1 entry
    When the user presses "u"
    Then the history should contain 0 entries

  Scenario: Pressing "u" with nothing to undo is a no-op
    Given 0 agents are in history
    And agent "fixer" is running and highlighted
    When the user presses "u"
    Then the active agents should include "fixer"
    And the history should contain 0 entries

  # ── Auto-dismiss + replace ──────────────────────────────────────

  Scenario: Undo bar auto-dismisses when the timer fires
    Given agent "fixer" is running and highlighted
    When the user presses "k"
    And the user presses "y"
    Then the undo bar should be visible
    When the undo timeout elapses
    Then the undo bar should be dismissed

  Scenario: A second destructive action replaces the previous undo entry
    Given the desk has shown an undo entry "Killed fixer"
    When the desk shows a new undo entry "Killed polisher"
    Then the undo bar should mention "polisher"
    And the undo bar should not mention "fixer"
