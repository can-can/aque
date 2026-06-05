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
