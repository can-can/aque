"""Encode Textual key names into vt100/xterm byte sequences for a PTY.

Pure functions, no I/O. `encode_key` takes a Textual `event.key` string and
returns the bytes to write to the terminal's master fd. Unknown keys return
b"" so callers can fall back to the event's `character`.
"""

_NAMED = {
    "enter": b"\r",
    "tab": b"\t",
    "shift+tab": b"\x1b[Z",
    "backspace": b"\x7f",
    "escape": b"\x1b",
    "space": b" ",
    "up": b"\x1bOA",
    "down": b"\x1bOB",
    "right": b"\x1bOC",
    "left": b"\x1bOD",
    "home": b"\x1b[H",
    "end": b"\x1b[F",
    "ctrl+home": b"\x1b[1;5H",
    "ctrl+end": b"\x1b[1;5F",
    "pageup": b"\x1b[5~",
    "pagedown": b"\x1b[6~",
    "delete": b"\x1b[3~",
    "insert": b"\x1b[2~",
    "f1": b"\x1bOP",
    "f2": b"\x1bOQ",
    "f3": b"\x1bOR",
    "f4": b"\x1bOS",
    "f5": b"\x1b[15~",
    "f6": b"\x1b[17~",
    "f7": b"\x1b[18~",
    "f8": b"\x1b[19~",
    "f9": b"\x1b[20~",
    "f10": b"\x1b[21~",
    "f11": b"\x1b[23~",
    "f12": b"\x1b[24~",
}


# Ctrl + non-letter keys that map to C0 control codes (Textual reports the
# symbol keys by these names).
_CTRL_SYMBOL = {
    "ctrl+space": b"\x00",
    "ctrl+@": b"\x00",
    "ctrl+backslash": b"\x1c",
    "ctrl+right_square_bracket": b"\x1d",
    "ctrl+circumflex_accent": b"\x1e",
    "ctrl+underscore": b"\x1f",
}

# Keys that take an xterm CSI modifier parameter: CSI <prefix> ; <mod> <final>.
# Arrows/home/end use prefix "1"; the "~" keys use their numeric code. The Alt
# modifier is 3 (1 + 2), so e.g. Alt+Left -> "\x1b[1;3D" (matches tmux/Ghostty).
_CSI_MODIFIABLE = {
    "up": ("1", "A"), "down": ("1", "B"),
    "right": ("1", "C"), "left": ("1", "D"),
    "home": ("1", "H"), "end": ("1", "F"),
    "pageup": ("5", "~"), "pagedown": ("6", "~"),
    "delete": ("3", "~"), "insert": ("2", "~"),
}


def _ctrl(letter: str) -> bytes:
    # Ctrl+a == 0x01 ... Ctrl+z == 0x1a
    return bytes([ord(letter.lower()) - ord("a") + 1])


def encode_key(key: str, character: str | None = None) -> bytes:
    """Return the bytes for a Textual key name.

    `character` is the event's printable character when available; used as the
    fallback for plain printable input.
    """
    # Reserved desk chords: must not be encoded so they bubble to desk actions
    if key.startswith("ctrl+shift+") or key == "ctrl+k":
        return b""

    if key in _NAMED:
        return _NAMED[key]

    if key in _CTRL_SYMBOL:
        return _CTRL_SYMBOL[key]

    if key.startswith("ctrl+") and len(key) == 6 and key[5].isalpha():
        return _ctrl(key[5])

    if key.startswith("alt+"):
        rest = key[4:]
        # Special keys carry the Alt modifier in xterm CSI form; printable
        # characters use the readline ESC-prefix form.
        if rest in _CSI_MODIFIABLE:
            prefix, final = _CSI_MODIFIABLE[rest]
            return f"\x1b[{prefix};3{final}".encode("ascii")
        inner = encode_key(rest, character=rest if len(rest) == 1 else None)
        return b"\x1b" + inner if inner else b""

    if len(key) == 1:
        return key.encode("utf-8")

    if character is not None and len(character) >= 1:
        return character.encode("utf-8")

    return b""
