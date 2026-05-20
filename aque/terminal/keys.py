"""Encode Textual key names into vt100/xterm byte sequences for a PTY.

Pure functions, no I/O. `encode_key` takes a Textual `event.key` string and
returns the bytes to write to the terminal's master fd. Unknown keys return
b"" so callers can fall back to the event's `character`.
"""

_NAMED = {
    "enter": b"\r",
    "tab": b"\t",
    "backspace": b"\x7f",
    "escape": b"\x1b",
    "space": b" ",
    "up": b"\x1bOA",
    "down": b"\x1bOB",
    "right": b"\x1bOC",
    "left": b"\x1bOD",
    "home": b"\x1b[H",
    "end": b"\x1b[F",
    "pageup": b"\x1b[5~",
    "pagedown": b"\x1b[6~",
    "delete": b"\x1b[3~",
    "insert": b"\x1b[2~",
}


def _ctrl(letter: str) -> bytes:
    # Ctrl+a == 0x01 ... Ctrl+z == 0x1a
    return bytes([ord(letter.lower()) - ord("a") + 1])


def encode_key(key: str, character: str | None = None) -> bytes:
    """Return the bytes for a Textual key name.

    `character` is the event's printable character when available; used as the
    fallback for plain printable input.
    """
    if key in _NAMED:
        return _NAMED[key]

    if key.startswith("ctrl+") and len(key) == 6 and key[5].isalpha():
        return _ctrl(key[5])

    if key.startswith("alt+"):
        rest = key[4:]
        inner = encode_key(rest, character=rest if len(rest) == 1 else None)
        return b"\x1b" + inner if inner else b""

    if len(key) == 1:
        return key.encode("utf-8")

    if character is not None and len(character) >= 1:
        return character.encode("utf-8")

    return b""
