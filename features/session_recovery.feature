Feature: Session recovery after restart
  As a user reopening aque after a machine reboot or tmux crash
  I want to see agents whose tmux sessions are gone and decide what to do per agent
  So that my running work can be resumed, restarted, marked exited, or discarded

  Background:
    Given a captured claude orphan with id 1 in the state file
    And the desk is launched

  Scenario: Orphan modal appears on startup
    Then the orphan modal is shown
    And the modal lists agent 1

  Scenario: Forget removes the orphan from state.json
    When I click Forget on agent 1
    Then agent 1 is removed from state.json
    And the orphan modal is dismissed

  Scenario: Mark exited flips state to EXITED and keeps the record
    When I click "Mark exited" on agent 1
    Then agent 1 is in state EXITED
    And agent 1 remains in state.json
    And the orphan modal is dismissed

  Scenario: Resume rebuilds the partner's responder
    Given agent 1 has a paired responder in the state file
    When I click Resume on agent 1
    Then relaunch_agent is called with preserve_session_id=True for agent 1
    And the dead responder for agent 1 is cleaned up
    And a fresh responder for agent 1 is created

  Scenario: Relaunch rebuilds the responder with a fresh conversation
    Given agent 1 has a paired responder in the state file
    When I click Relaunch on agent 1
    Then relaunch_agent is called with preserve_session_id=False for agent 1
    And a fresh responder for agent 1 is created

  Scenario: Resume does not create a responder for a solo agent
    When I click Resume on agent 1
    Then relaunch_agent is called with preserve_session_id=True for agent 1
    And no fresh responder for agent 1 is created

  Scenario: Forget on a partner cleans up the paired responder
    When I click Forget on agent 1
    Then responder.cleanup is called for agent 1
    And agent 1 is removed from state.json

  Scenario: Action failure keeps the orphan in the modal with an inline error
    Given relaunch_agent is configured to fail with "dir missing"
    When I click Relaunch on agent 1
    Then the orphan modal is still shown
    And the modal lists agent 1
    And the row for agent 1 shows an inline error

  Scenario: Resume button is disabled when no session_id was captured
    Given a claude orphan with id 2 and no captured session_id
    Then the Resume button for agent 2 is disabled
