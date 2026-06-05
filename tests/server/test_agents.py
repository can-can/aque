from pathlib import Path

from aque.server.agents import agents_payload
from aque.state import StateManager


def test_agents_payload_maps_fields_and_drops_responders(server_aque_dir, write_state):
    write_state([
        {
            "id": 1, "tmux_session": "aque-1", "label": "api fix", "dir": "/tmp/api",
            "command": ["claude"], "state": "waiting", "pid": 10,
            "agent_type": "claude", "is_responder": False,
        },
        {
            "id": 2, "tmux_session": "aque-2", "label": "resp", "dir": "/tmp/api",
            "command": ["claude"], "state": "running", "pid": 11,
            "agent_type": None, "is_responder": True, "partner_id": 1,
        },
    ])
    payload = agents_payload(StateManager(server_aque_dir))

    assert len(payload) == 1
    a = payload[0]
    assert a == {
        "id": 1, "state": "waiting", "label": "api fix",
        "dir": "/tmp/api", "agent_type": "claude", "tmux_session": "aque-1",
    }
