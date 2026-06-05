from aque.server.auth import token_ok


def test_token_ok_accepts_bearer_header():
    assert token_ok("Bearer secret", None, "secret") is True


def test_token_ok_accepts_query_token():
    assert token_ok(None, "secret", "secret") is True


def test_token_ok_rejects_wrong_token():
    assert token_ok("Bearer nope", "nope", "secret") is False


def test_token_ok_rejects_when_no_credentials():
    assert token_ok(None, None, "secret") is False


def test_token_ok_rejects_empty_expected():
    assert token_ok("Bearer ", "", "") is False
