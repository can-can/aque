Feature: Agent lifecycle
  As a user managing agents in the queue
  I want agents to transition through well-defined states
  So that the queue operates predictably

  # ── State transitions ──────────────────────────────────────────

  Scenario: New agent starts in running state
    When a new agent is launched
    Then the agent should be in "running" state

  Scenario: Running agent transitions to waiting when idle
    Given agent "builder" is in "running" state
    And the agent has been idle for the configured timeout
    When the monitor detects the idle state
    Then agent "builder" should be in "waiting" state

  Scenario: Running agent transitions to exited when tmux session dies
    Given agent "builder" is in "running" state
    And the tmux session no longer exists
    When the monitor polls
    Then agent "builder" should be in "exited" state

  Scenario: Running agent can be put on hold
    Given agent "builder" is in "running" state
    When the user presses "h" with "builder" highlighted
    Then agent "builder" should be in "on_hold" state

  Scenario: On-hold agent can be resumed
    Given agent "builder" is in "on_hold" state
    When the user presses "h" with "builder" highlighted
    Then agent "builder" should be in "running" state

  Scenario: Any agent can be killed from dashboard
    Given agent "builder" exists in any state
    When the user presses "k" with "builder" highlighted
    And the user confirms the kill prompt
    Then agent "builder" should be moved to history
    And the tmux session should be killed

  # ── State / folder / name ordering ─────────────────────────────

  Scenario: Agents are ordered by state, then folder, then by name
    Given the following agents exist:
      | label | state   | dir              |
      | a     | running | /home/work/alpha |
      | b     | waiting | /home/work/zeta  |
      | c     | on_hold | /home/work/alpha |
      | d     | exited  | /home/work/mid   |
      | e     | waiting | /home/work/alpha |
    Then the sorted order should be:
      | label | reason                                            |
      | e     | waiting outranks all; alpha folder before zeta    |
      | b     | waiting; zeta folder after alpha                  |
      | a     | running, after waiting                            |
      | c     | on_hold, after running                            |
      | d     | exited last among visible states                  |
