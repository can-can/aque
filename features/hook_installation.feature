Feature: Hook installation
  As a user launching agents with a known type
  I want aque to automatically install lifecycle hooks
  So that idle detection is instant without manual configuration

  # ── Plugin discovery ───────────────────────────────────────────

  Scenario: Known agent type is discovered as a plugin
    Given the "claude" plugin is available
    When I look up the plugin for type "claude"
    Then the plugin should be found
    And it should have an is_installed method
    And it should have an install_hook method

  Scenario: Unknown agent type returns no plugin
    When I look up the plugin for type "nonexistent"
    Then the plugin should not be found

  # ── Hook installation ──────────────────────────────────────────

  Scenario: First launch with type installs hook with confirmation
    Given the "claude" hook is not installed
    When I install the "claude" hook
    Then the hook should be configured in the agent's settings
    And the hook command should write to the aque signals directory

  Scenario: Hook installation preserves existing settings
    Given the agent settings file has existing configuration
    When I install the "claude" hook
    Then the existing configuration should be preserved
    And the aque hook should be added

  Scenario: Hook installation is idempotent
    Given the "claude" hook is already installed
    When I install the "claude" hook again
    Then there should still be exactly one aque hook entry

  # ── Launch integration ─────────────────────────────────────────

  Scenario: Launching with type sets the AQUE_AGENT_ID environment variable
    When an agent is launched with type "claude"
    Then the tmux session should have AQUE_AGENT_ID exported
    And the agent should be registered with type "claude"

  Scenario: Launching without type does not export environment variable
    When an agent is launched without a type
    Then no AQUE_AGENT_ID should be exported
    And the agent should be registered with no type

  Scenario: Launching with unknown type falls back to polling
    When an agent is launched with type "nonexistent"
    Then the agent should be registered with no type
