import json

from aque.server.pairing import generate_token, pairing_payload, render_qr


def test_generate_token_is_nonempty_and_unique():
    a, b = generate_token(), generate_token()
    assert a and isinstance(a, str)
    assert a != b


def test_pairing_payload_round_trips_as_json():
    payload = pairing_payload("192.168.1.5", 8722, "tok")
    parsed = json.loads(json.dumps(payload))
    assert parsed == {"host": "192.168.1.5", "port": 8722, "token": "tok"}


def test_render_qr_returns_multiline_ascii():
    out = render_qr("hello")
    assert isinstance(out, str)
    assert "\n" in out
