from pathlib import Path

from aque.config import load_config, DEFAULT_CONFIG


def test_shortcuts_priority_chords(tmp_path):
    # Only priority chords are configured (they must work while the embed is
    # focused). Plain-letter desk actions live in BINDINGS, gated by
    # check_action — they are NOT in the shortcuts config. No F-keys.
    s = load_config(tmp_path)["shortcuts"]
    assert s["quit"] == "ctrl+shift+q"
    assert s["attach_fullscreen"] == "ctrl+shift+f"
    assert s["next_agent"] == "ctrl+shift+j"
    assert s["prev_agent"] == "ctrl+shift+k"
    # plain-letter actions are not chord-configured anymore
    for gone in ("new_agent", "kill_agent", "hold_agent", "toggle_auto",
                 "switch_focus", "switch_agent"):
        assert gone not in s
    # no F-keys anywhere
    assert all(not v.startswith("f") or v.startswith("ctrl") for v in s.values())


class TestConfig:
    def test_default_config_values(self):
        assert DEFAULT_CONFIG["idle_timeout"] == 15
        assert DEFAULT_CONFIG["snapshot_interval"] == 2
        assert DEFAULT_CONFIG["action_keys"]["dismiss"] == "d"
        assert DEFAULT_CONFIG["action_keys"]["done"] == "k"
        assert DEFAULT_CONFIG["action_keys"]["skip"] == "s"
        assert DEFAULT_CONFIG["queue_order"] == "fifo"

    def test_load_config_no_file(self, tmp_aque_dir):
        config = load_config(tmp_aque_dir)
        assert config == DEFAULT_CONFIG

    def test_load_config_partial_override(self, tmp_aque_dir):
        config_path = tmp_aque_dir / "config.yaml"
        config_path.write_text("idle_timeout: 20\n")
        config = load_config(tmp_aque_dir)
        assert config["idle_timeout"] == 20
        assert config["snapshot_interval"] == 2  # default preserved

    def test_load_config_nested_override(self, tmp_aque_dir):
        config_path = tmp_aque_dir / "config.yaml"
        config_path.write_text("action_keys:\n  dismiss: x\n")
        config = load_config(tmp_aque_dir)
        assert config["action_keys"]["dismiss"] == "x"
        assert config["action_keys"]["done"] == "k"  # default preserved

    def test_default_dir_in_config(self):
        assert "default_dir" in DEFAULT_CONFIG

    def test_default_dir_override(self, tmp_aque_dir):
        config_path = tmp_aque_dir / "config.yaml"
        config_path.write_text("default_dir: /tmp/custom\n")
        config = load_config(tmp_aque_dir)
        assert config["default_dir"] == "/tmp/custom"

    def test_responder_defaults(self):
        assert DEFAULT_CONFIG["responder_enabled"] is True
        assert DEFAULT_CONFIG["responder_command"] == ["claude"]
        assert DEFAULT_CONFIG["responder_idle_gap"] == 30
        assert DEFAULT_CONFIG["responder_dir"] is None

    def test_responder_command_override(self, tmp_aque_dir):
        config_path = tmp_aque_dir / "config.yaml"
        config_path.write_text(
            "responder_command:\n  - claude\n  - --model\n  - haiku\n"
        )
        config = load_config(tmp_aque_dir)
        assert config["responder_command"] == ["claude", "--model", "haiku"]

    def test_responder_idle_gap_override(self, tmp_aque_dir):
        config_path = tmp_aque_dir / "config.yaml"
        config_path.write_text("responder_idle_gap: 10\n")
        config = load_config(tmp_aque_dir)
        assert config["responder_idle_gap"] == 10

    def test_responder_enabled_false(self, tmp_aque_dir):
        config_path = tmp_aque_dir / "config.yaml"
        config_path.write_text("responder_enabled: false\n")
        config = load_config(tmp_aque_dir)
        assert config["responder_enabled"] is False
