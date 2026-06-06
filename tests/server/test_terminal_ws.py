import pytest
from starlette.websockets import WebSocketDisconnect

from .conftest import TOKEN

AGENT = {
    "id": 1, "tmux_session": "aque-1", "label": "one", "dir": "/tmp/a",
    "command": ["claude"], "state": "running", "pid": 10, "is_responder": False,
}


def test_terminal_rejects_bad_token(make_client):
    client = make_client([AGENT], command_for_agent=lambda a: ["cat"])
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/agents/1/terminal?token=wrong") as ws:
            ws.receive_bytes()


def test_terminal_unknown_agent_closes(make_client):
    client = make_client([AGENT], command_for_agent=lambda a: ["cat"])
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/agents/999/terminal?token={TOKEN}") as ws:
            ws.receive_bytes()


def test_terminal_pumps_bytes_both_ways(make_client):
    client = make_client([AGENT], command_for_agent=lambda a: ["cat"])
    with client.websocket_connect(f"/agents/1/terminal?token={TOKEN}") as ws:
        ws.send_bytes(b"ping\n")
        got = b""
        while b"ping" not in got:
            got += ws.receive_bytes()
        assert b"ping" in got


def test_terminal_ignores_malformed_resize(make_client):
    client = make_client([AGENT], command_for_agent=lambda a: ["cat"])
    with client.websocket_connect(f"/agents/1/terminal?token={TOKEN}") as ws:
        ws.send_text("this is not json")  # must NOT kill the connection
        ws.send_bytes(b"ping\n")
        got = b""
        while b"ping" not in got:
            got += ws.receive_bytes()
        assert b"ping" in got


def test_terminal_spawns_at_initial_resize(make_client):
    # The server must wait for the client's resize, then spawn the terminal at
    # that size (so a TUI's first paint isn't garbled by a later resize).
    import json
    client = make_client([AGENT], command_for_agent=lambda a: ["stty", "size"])
    with client.websocket_connect(f"/agents/1/terminal?token={TOKEN}") as ws:
        ws.send_text(json.dumps({"type": "resize", "cols": 51, "rows": 33}))
        got = b""
        while b"\n" not in got:
            got += ws.receive_bytes()
        assert b"33 51" in got  # the spawned `stty size` saw 33 rows x 51 cols
