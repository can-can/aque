def test_root_serves_terminal_test_page(make_client):
    client = make_client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert "xterm" in resp.text.lower()
