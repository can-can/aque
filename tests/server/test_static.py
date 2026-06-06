def test_root_serves_terminal_test_page(make_client):
    client = make_client()
    resp = client.get("/")
    assert resp.status_code == 200
    assert "xterm" in resp.text.lower()


def test_terminal_page_served(make_client):
    client = make_client()
    resp = client.get("/terminal")
    assert resp.status_code == 200
    assert "xterm" in resp.text.lower()
    assert "addon-fit" in resp.text.lower()  # fit addon = fills the phone width
