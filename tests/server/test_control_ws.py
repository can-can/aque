import pytest
from starlette.websockets import WebSocketDisconnect

from .conftest import TOKEN

AGENT = {
    "id": 1, "tmux_session": "aque-1", "label": "one", "dir": "/tmp/a",
    "command": ["claude"], "state": "running", "pid": 10, "is_responder": False,
}


def _recorder():
    """A send_keys_for_agent stub that records (agent_id, key) calls."""
    calls = []
    return calls, (lambda agent, key: calls.append((agent["id"], key)))


def test_control_rejects_bad_token(make_client):
    _, send = _recorder()
    client = make_client([AGENT], send_keys_for_agent=send)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/agents/1/control?token=wrong") as ws:
            ws.receive_json()


def test_control_unknown_agent_closes(make_client):
    _, send = _recorder()
    client = make_client([AGENT], send_keys_for_agent=send)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/agents/999/control?token={TOKEN}") as ws:
            ws.receive_json()


def test_control_sends_allowed_key(make_client):
    calls, send = _recorder()
    client = make_client([AGENT], send_keys_for_agent=send)
    with client.websocket_connect(f"/agents/1/control?token={TOKEN}") as ws:
        ws.send_json({"type": "key", "key": "Up"})
        ack = ws.receive_json()
    assert ack == {"type": "ok", "key": "Up"}
    assert calls == [(1, "Up")]


def test_control_rejects_unknown_key(make_client):
    calls, send = _recorder()
    client = make_client([AGENT], send_keys_for_agent=send)
    with client.websocket_connect(f"/agents/1/control?token={TOKEN}") as ws:
        ws.send_json({"type": "key", "key": "rm -rf /"})
        ack = ws.receive_json()
    assert ack["type"] == "error"
    assert calls == []


def test_control_ignores_non_key_message(make_client):
    calls, send = _recorder()
    client = make_client([AGENT], send_keys_for_agent=send)
    with client.websocket_connect(f"/agents/1/control?token={TOKEN}") as ws:
        ws.send_json({"type": "noise"})       # must NOT close or send
        ws.send_json({"type": "key", "key": "Enter"})
        ack = ws.receive_json()
    assert ack == {"type": "ok", "key": "Enter"}
    assert calls == [(1, "Enter")]


def test_control_and_terminal_coexist(make_client):
    calls, send = _recorder()
    client = make_client(
        [AGENT], command_for_agent=lambda a: ["cat"], send_keys_for_agent=send
    )
    with client.websocket_connect(f"/agents/1/terminal?token={TOKEN}") as term:
        term.send_bytes(b"ping\n")
        got = b""
        while b"ping" not in got:
            got += term.receive_bytes()
        with client.websocket_connect(f"/agents/1/control?token={TOKEN}") as ctrl:
            ctrl.send_json({"type": "key", "key": "C-u"})
            assert ctrl.receive_json() == {"type": "ok", "key": "C-u"}
    assert calls == [(1, "C-u")]


def test_control_rejects_missing_key(make_client):
    calls, send = _recorder()
    client = make_client([AGENT], send_keys_for_agent=send)
    with client.websocket_connect(f"/agents/1/control?token={TOKEN}") as ws:
        ws.send_json({"type": "key"})            # no "key" field
        ack = ws.receive_json()
    assert ack["type"] == "error"
    assert calls == []


def test_control_reports_send_failure(make_client):
    def boom(agent, key):
        raise RuntimeError("tmux gone")
    client = make_client([AGENT], send_keys_for_agent=boom)
    with client.websocket_connect(f"/agents/1/control?token={TOKEN}") as ws:
        ws.send_json({"type": "key", "key": "Up"})
        ack = ws.receive_json()
        assert ack["type"] == "error" and ack["reason"] == "send failed"
        ws.send_json({"type": "key", "key": "Down"})   # socket still alive
        ack2 = ws.receive_json()
        assert ack2["type"] == "error" and ack2["reason"] == "send failed"


def test_default_send_keys_targets_phone_session(monkeypatch):
    import aque.server.control as ctl
    captured = {}
    monkeypatch.setattr(ctl.subprocess, "run",
                        lambda argv, **k: captured.setdefault("argv", argv))
    ctl.default_send_keys({"id": 7}, "Enter")
    assert captured["argv"] == ["tmux", "send-keys", "-t", "phone-7", "Enter"]
