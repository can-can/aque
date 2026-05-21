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


def test_scroll_forwards_to_session():
    from aque.terminal.widget import TerminalView

    class FakeSession:
        def __init__(self): self.writes = []
        def write(self, data): self.writes.append(data)

    class FakeEvent:
        def __init__(self): self.stopped = False
        def stop(self): self.stopped = True

    tv = TerminalView()
    tv.session = FakeSession()
    up = FakeEvent(); tv.on_mouse_scroll_up(up)
    down = FakeEvent(); tv.on_mouse_scroll_down(down)
    assert len(tv.session.writes) == 2
    assert up.stopped and down.stopped


def test_attach_defers_when_zero_size(monkeypatch):
    from textual.geometry import Size
    from aque.terminal.widget import TerminalView

    tv = TerminalView()
    spawned = []
    # Force a zero-size widget (not laid out yet).
    monkeypatch.setattr(type(tv), "size", property(lambda self: Size(0, 0)))

    class FakeSession:
        def __init__(self, columns, lines): pass
        def spawn(self, argv): spawned.append(argv)

    monkeypatch.setattr("aque.terminal.widget.PtySession", FakeSession)
    tv.attach("aque-1")
    assert spawned == []                      # did NOT spawn into a 0x0 pty
    assert tv._pending_session == "aque-1"    # remembered for next layout
