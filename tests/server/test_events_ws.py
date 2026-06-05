from .conftest import TOKEN

AGENT1 = {
    "id": 1, "tmux_session": "aque-1", "label": "one", "dir": "/tmp/a",
    "command": ["claude"], "state": "running", "pid": 10, "is_responder": False,
}
AGENT2 = {
    "id": 2, "tmux_session": "aque-2", "label": "two", "dir": "/tmp/b",
    "command": ["claude"], "state": "waiting", "pid": 11, "is_responder": False,
}


def test_events_rejects_bad_token(make_client):
    client = make_client([AGENT1])
    import pytest
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/events?token=wrong") as ws:
            ws.receive_json()


def test_events_sends_initial_then_updates(make_client, write_state):
    client = make_client([AGENT1])
    with client.websocket_connect(f"/events?token={TOKEN}") as ws:
        first = ws.receive_json()
        assert first["type"] == "agents"
        assert [a["id"] for a in first["agents"]] == [1]

        write_state([AGENT1, AGENT2])
        update = ws.receive_json()
        assert {a["id"] for a in update["agents"]} == {1, 2}
