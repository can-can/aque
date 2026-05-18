"""Tests for the aque CLI auto-responder wiring."""
from unittest.mock import patch

from typer.testing import CliRunner

from aque.cli import app


runner = CliRunner()


class TestRunResponderWiring:
    @patch("aque.cli.responder.create_for")
    @patch("aque.cli.launch_agent")
    @patch("aque.cli.ensure_monitor_running")
    def test_run_creates_responder_by_default(
        self, _mon, mock_launch, mock_create, tmp_aque_dir
    ):
        mock_launch.return_value = 1
        result = runner.invoke(
            app, ["--aque-dir", str(tmp_aque_dir), "run", "--dir", "/tmp", "claude"]
        )
        assert result.exit_code == 0, result.output
        assert mock_create.call_count == 1

    @patch("aque.cli.responder.create_for")
    @patch("aque.cli.launch_agent")
    @patch("aque.cli.ensure_monitor_running")
    def test_no_responder_flag_skips_pairing(
        self, _mon, mock_launch, mock_create, tmp_aque_dir
    ):
        mock_launch.return_value = 1
        result = runner.invoke(
            app,
            [
                "--aque-dir", str(tmp_aque_dir),
                "run", "--dir", "/tmp", "--no-responder", "claude",
            ],
        )
        assert result.exit_code == 0, result.output
        mock_create.assert_not_called()

    @patch("aque.cli.responder.create_for")
    @patch("aque.cli.launch_agent")
    @patch("aque.cli.ensure_monitor_running")
    def test_responder_cmd_override(
        self, _mon, mock_launch, mock_create, tmp_aque_dir
    ):
        mock_launch.return_value = 1
        result = runner.invoke(
            app,
            [
                "--aque-dir", str(tmp_aque_dir),
                "run", "--dir", "/tmp",
                "--responder-cmd", "claude --model haiku",
                "claude",
            ],
        )
        assert result.exit_code == 0, result.output
        passed_config = mock_create.call_args.args[1]
        assert passed_config["responder_command"] == ["claude", "--model", "haiku"]

    @patch("aque.cli.responder.create_for")
    @patch("aque.cli.launch_agent")
    @patch("aque.cli.ensure_monitor_running")
    def test_responder_disabled_in_config(
        self, _mon, mock_launch, mock_create, tmp_aque_dir
    ):
        (tmp_aque_dir / "config.yaml").write_text("responder_enabled: false\n")
        mock_launch.return_value = 1
        result = runner.invoke(
            app, ["--aque-dir", str(tmp_aque_dir), "run", "--dir", "/tmp", "claude"]
        )
        assert result.exit_code == 0, result.output
        mock_create.assert_not_called()


class TestListIndent:
    def test_list_shows_responder_indented_under_partner(self, tmp_aque_dir):
        from aque.state import AgentInfo, AgentState, StateManager

        mgr = StateManager(tmp_aque_dir)
        mgr.add_agent(AgentInfo(
            id=1, tmux_session="aque-1", label="main",
            dir="/tmp", command=["claude"], state=AgentState.RUNNING, pid=100,
        ))
        mgr.add_agent(AgentInfo(
            id=2, tmux_session="aque-2", label="resp(1)",
            dir="/tmp", command=["claude"], state=AgentState.RUNNING, pid=101,
            is_responder=True, partner_id=1,
        ))
        result = runner.invoke(app, ["--aque-dir", str(tmp_aque_dir), "list"])
        assert result.exit_code == 0
        assert "↳ resp(1)" in result.output
