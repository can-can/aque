from .conftest import TOKEN

AGENTS = [
    {
        "id": 1, "tmux_session": "aque-1", "label": "api fix", "dir": "/tmp/api",
        "command": ["claude"], "state": "waiting", "pid": 10,
        "agent_type": "claude", "is_responder": False,
    },
]


def test_healthz_is_open(make_client):
    client = make_client()
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_agents_requires_token(make_client):
    client = make_client(AGENTS)
    assert client.get("/agents").status_code == 401


def test_agents_with_token_returns_queue(make_client):
    client = make_client(AGENTS)
    resp = client.get("/agents", headers={"Authorization": f"Bearer {TOKEN}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["agents"][0]["id"] == 1
    assert body["agents"][0]["state"] == "waiting"
