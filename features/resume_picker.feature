Feature: Resume picker for create-time session continuity
  As a user creating an agent in a directory with prior sessions
  I want to choose between starting fresh or resuming a past conversation
  So that I can pick up where I left off without rebuilding context

  Background:
    Given the resume picker is opened with the following sessions:
      | uuid     | first_prompt   | mtime                     | size_bytes |
      | sess-001 | help with auth | 2026-03-20T10:00:00+00:00 | 4096       |
      | sess-002 | fix imports    | 2026-03-21T11:30:00+00:00 | 8192       |

  Scenario: "Start fresh" is pre-selected when the picker opens
    Then the picker's highlighted option id should be "fresh"

  Scenario: Each session row shows age, size, and the first prompt
    Then the picker should list an option mentioning "help with auth"
    And the picker should list an option mentioning "KB"
    And the picker should list an option mentioning "ago"

  Scenario: Selecting "Start fresh" dismisses with a fresh result
    When the picker selects the option with id "fresh"
    Then the picker should dismiss with action "fresh" and session_id None

  Scenario: Selecting a session dismisses with its session_id
    When the picker selects the option with id "resume:sess-001"
    Then the picker should dismiss with action "resume" and session_id "sess-001"

  Scenario: Pressing Escape dismisses with no result
    When the user presses Escape on the picker
    Then the picker should dismiss with no result
