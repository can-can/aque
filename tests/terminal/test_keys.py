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
    assert encode_key("unknown_key") == b""


def test_ctrl_end_and_ctrl_home_have_sequences():
    assert encode_key("ctrl+end") != b""
    assert encode_key("ctrl+home") != b""


def test_shift_tab_and_function_keys():
    assert encode_key("shift+tab") == b"\x1b[Z"
    assert encode_key("f1") == b"\x1bOP"
    assert encode_key("f4") == b"\x1bOS"
    assert encode_key("f5") == b"\x1b[15~"
    assert encode_key("f12") == b"\x1b[24~"


def test_reserved_chords_are_not_encodable():
    assert encode_key("ctrl+shift+j") == b""
    assert encode_key("ctrl+shift+n") == b""
    assert encode_key("ctrl+k") == b""


def test_alt_special_keys_use_csi_modifier():
    # Alt+arrows/home/end/etc carry the modifier in xterm CSI form (mod 3),
    # matching tmux/Ghostty — NOT the wrong double-ESC of the SS3 form.
    assert encode_key("alt+left") == b"\x1b[1;3D"
    assert encode_key("alt+right") == b"\x1b[1;3C"
    assert encode_key("alt+up") == b"\x1b[1;3A"
    assert encode_key("alt+home") == b"\x1b[1;3H"
    assert encode_key("alt+end") == b"\x1b[1;3F"
    assert encode_key("alt+pageup") == b"\x1b[5;3~"
    assert encode_key("alt+delete") == b"\x1b[3;3~"


def test_alt_letters_stay_esc_prefixed():
    assert encode_key("alt+f") == b"\x1bf"
    assert encode_key("alt+b") == b"\x1bb"


def test_ctrl_symbol_keys():
    assert encode_key("ctrl+space") == b"\x00"
    assert encode_key("ctrl+backslash") == b"\x1c"
    assert encode_key("ctrl+underscore") == b"\x1f"
