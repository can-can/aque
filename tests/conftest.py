import json
import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_aque_dir(tmp_path):
    """Temporary ~/.aque directory for testing."""
    aque_dir = tmp_path / ".aque"
    aque_dir.mkdir()
    return aque_dir


@pytest.fixture
def empty_state_file(tmp_aque_dir):
    """Empty state file with no agents."""
    state_path = tmp_aque_dir / "state.json"
    state_path.write_text(json.dumps({"agents": [], "monitor_pid": None}))
    return state_path


@pytest.fixture
def sample_agents():
    """Sample agent data for testing."""
    return [
        {
            "id": 1,
            "tmux_session": "aque-1",
            "label": "claude . my-api",
            "dir": "/tmp/my-api",
            "command": ["claude", "--model", "opus"],
            "state": "running",
            "pid": 12345,
            "created_at": "2026-03-28T10:00:00Z",
            "last_change_at": "2026-03-28T10:00:00Z",
        },
        {
            "id": 2,
            "tmux_session": "aque-2",
            "label": "aider . frontend",
            "dir": "/tmp/frontend",
            "command": ["aider"],
            "state": "waiting",
            "pid": 12346,
            "created_at": "2026-03-28T10:01:00Z",
            "last_change_at": "2026-03-28T10:05:00Z",
        },
    ]
