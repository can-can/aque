from rich.style import Style
from aque.terminal.pty import PtySession
from aque.terminal.widget import render_strip, cell_style


def test_render_strip_text():
    s = PtySession(columns=10, lines=3)
    s.feed(b"hi")
    strip = render_strip(s, y=0, width=10, cursor_visible=False)
    text = "".join(seg.text for seg in strip)
    assert text.startswith("hi")


def test_cursor_cell_is_reverse_for_default_colors():
    s = PtySession(columns=10, lines=3)
    s.feed(b"x")
    # cursor now at (1,0); render row 0 with cursor drawn
    strip = render_strip(s, y=0, width=10, cursor_visible=True)
    assert any(seg.style and seg.style.reverse for seg in strip)


def test_cell_style_explicit_colors_for_cursor():
    style = cell_style(fg="default", bg="default", is_cursor=True)
    assert style.reverse is True
