Feature: Session recovery after restart

  Background:
    Given an aque state file with a claude agent whose tmux session is gone
    And the claude agent has a captured session_id

  Scenario: User sees orphans on desk startup
    When I open aque desk
    Then the orphan modal is shown
    And it lists the orphaned claude agent

  Scenario: User forgets an orphan
    When I open aque desk
    And I click Forget on the orphan
    Then the orphan is removed from state.json

  Scenario: User marks an orphan as exited
    When I open aque desk
    And I click "Mark exited" on the orphan
    Then the agent's state is EXITED
    And the agent remains in state.json

  Scenario: Resume disabled when no session_id was captured
    Given an additional claude agent with no captured session_id
    When I open aque desk
    Then the Resume button is disabled for that agent
