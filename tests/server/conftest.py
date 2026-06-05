import json

import pytest

TOKEN = "test-token-123"


@pytest.fixture
def server_aque_dir(tmp_path):
    """A temp ~/.aque dir seeded with an empty state file."""
    d = tmp_path / ".aque"
    d.mkdir()
    (d / "state.json").write_text(json.dumps({"agents": [], "monitor_pid": None}))
    return d


@pytest.fixture
def write_state(server_aque_dir):
    """Return a helper that overwrites state.json with the given agent dicts."""
    def _write(agents):
        (server_aque_dir / "state.json").write_text(
            json.dumps({"agents": agents, "monitor_pid": None})
        )
    return _write


from fastapi.testclient import TestClient

from aque.server.app import create_app


@pytest.fixture
def make_client(server_aque_dir, write_state):
    """Build a TestClient for the server over a seeded state file."""
    def _make(agents=None, **kwargs):
        write_state(agents or [])
        app = create_app(server_aque_dir, TOKEN, watch_interval=0.05, **kwargs)
        return TestClient(app)
    return _make
