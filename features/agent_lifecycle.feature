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

  Scenario: Waiting agent transitions to focused on attach
    Given agent "builder" is in "waiting" state
    When the user attaches to agent "builder"
    Then agent "builder" should be in "focused" state

  Scenario: Focused agent transitions to running on detach
    Given agent "builder" is in "focused" state
    When the user detaches from the tmux session
    Then agent "builder" should be in "running" state

  Scenario: Exited agent transitions to done on detach
    Given agent "builder" is in "exited" state
    And the user is attached to agent "builder"
    When the user detaches from the tmux session
    Then agent "builder" should be moved to history

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
    Then agent "builder" should be moved to history
    And the tmux session should be killed

  # ── State priority ordering ────────────────────────────────────

  Scenario: Agents are ordered by state priority then by change time
    Given the following agents exist:
      | label | state   | last_change_at         |
      | a     | running | 2026-03-29T04:00:00+00 |
      | b     | waiting | 2026-03-29T04:30:00+00 |
      | c     | waiting | 2026-03-29T04:00:00+00 |
      | d     | on_hold | 2026-03-29T04:00:00+00 |
    Then the sorted order should be:
      | label | reason                         |
      | c     | waiting, earliest change       |
      | b     | waiting, later change          |
      | a     | running, lower priority        |
      | d     | on_hold, lowest priority       |
