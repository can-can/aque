from pathlib import Path

from aque.config import load_config, DEFAULT_CONFIG


class TestConfig:
    def test_default_config_values(self):
        assert DEFAULT_CONFIG["idle_timeout"] == 10
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
