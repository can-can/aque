import aque.cli as cli_mod
from typer.testing import CliRunner

runner = CliRunner()


def test_serve_prints_pairing_and_starts_app(monkeypatch, tmp_path):
    ran = {}

    def fake_uvicorn_run(app, host, port, **kwargs):
        ran["host"] = host
        ran["port"] = port

    monkeypatch.setattr("uvicorn.run", fake_uvicorn_run)
    monkeypatch.setattr("aque.server.discovery.register", lambda ip, port: None)

    result = runner.invoke(
        cli_mod.app,
        ["--aque-dir", str(tmp_path), "serve", "--port", "9911",
         "--token", "abc123", "--no-discovery"],
    )

    assert result.exit_code == 0, result.output
    assert "abc123" in result.output      # token shown for pairing
    assert ran["port"] == 9911            # server actually launched
