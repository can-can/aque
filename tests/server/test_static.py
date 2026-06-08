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
    # Pure renderer: no input UI of its own. Instead it exposes the native bridge
    # hooks the app drives (typing / scroll / zoom / keyboard-height).
    assert 'id="term"' in resp.text
    for hook in ("window.aqueInput", "window.aqueScroll",
                 "window.aqueZoom", "window.aqueSetKeyboardHeight"):
        assert hook in resp.text


def test_gestures_module_served(make_client):
    client = make_client()
    resp = client.get("/static/gestures.js")
    assert resp.status_code == 200
    assert "GestureInput" in resp.text
