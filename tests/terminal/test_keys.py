from aque.terminal.keys import encode_key


def test_printable_passthrough():
    assert encode_key("a") == b"a"
    assert encode_key("Z") == b"Z"


def test_enter_and_tab_and_backspace():
    assert encode_key("enter") == b"\r"
    assert encode_key("tab") == b"\t"
    assert encode_key("backspace") == b"\x7f"
    assert encode_key("escape") == b"\x1b"


def test_arrows():
    assert encode_key("up") == b"\x1bOA"
    assert encode_key("down") == b"\x1bOB"
    assert encode_key("right") == b"\x1bOC"
    assert encode_key("left") == b"\x1bOD"


def test_ctrl_letters():
    assert encode_key("ctrl+c") == b"\x03"
    assert encode_key("ctrl+a") == b"\x01"


def test_alt_is_esc_prefixed():
    assert encode_key("alt+b") == b"\x1bb"
    assert encode_key("alt+f") == b"\x1bf"


def test_unknown_returns_empty():
    assert encode_key("f5") == b""
