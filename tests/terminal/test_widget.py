from rich.style import Style
from aque.terminal.pty import PtySession
from aque.terminal.widget import render_strip, cell_style


def test_render_strip_text():
    s = PtySession(columns=10, lines=3)
    s.feed(b"hi")
    strip = render_strip(s, y=0, width=10, cursor_visible=False)
    text = "".join(seg.text for seg in strip)
    assert text.startswith("hi")


def test_cursor_cell_is_black_on_white():
    s = PtySession(columns=10, lines=3)
    s.feed(b"x")
    # cursor now at (1,0); render row 0 with cursor drawn — the cursor cell is
    # an explicit black-on-white run (always visible, even if DECTCEM hides it).
    strip = render_strip(s, y=0, width=10, cursor_visible=True)
    assert any(
        seg.style and seg.style.bgcolor and seg.style.bgcolor.name in ("#ffffff", "white")
        for seg in strip
    )


def test_cell_style_explicit_colors_for_cursor():
    style = cell_style(fg="default", bg="default", is_cursor=True)
    assert style.color.name in ("#000000", "black")
    assert style.bgcolor.name in ("#ffffff", "white")


def test_render_strip_groups_same_style_runs():
    # Uniform text must coalesce into far fewer Segments than cells (one run for
    # the text, one for the cursor cell, one for the trailing blanks).
    s = PtySession(columns=20, lines=3)
    s.feed(b"hello")
    strip = render_strip(s, y=0, width=20, cursor_visible=True)
    assert "".join(seg.text for seg in strip).startswith("hello")
    assert len(strip) < 20  # grouped, not one Segment per cell


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


def test_cell_style_is_memoized():
    # Same inputs -> same (immutable) Style instance, so full repaints don't
    # rebuild thousands of Style objects per frame.
    from aque.terminal.widget import cell_style
    a = cell_style("red", "default", bold=True)
    b = cell_style("red", "default", bold=True)
    assert a is b


def test_render_line_caches_until_invalidated(monkeypatch):
    from textual.geometry import Size
    from aque.terminal.widget import TerminalView
    from aque.terminal.pty import PtySession

    tv = TerminalView()
    monkeypatch.setattr(type(tv), "size", property(lambda self: Size(10, 3)))
    tv.session = PtySession(columns=10, lines=3)
    tv.session.feed(b"hi")

    s1 = tv.render_line(0)
    s2 = tv.render_line(0)
    assert s1 is s2                       # cached: same Strip instance reused

    tv._line_cache.pop(0, None)           # simulate the row going dirty
    s3 = tv.render_line(0)
    assert s3 is not s1                   # rebuilt after invalidation


def test_on_paste_wraps_bracketed():
    from aque.terminal.widget import TerminalView

    class FakeSession:
        def __init__(self): self.writes = []
        def write(self, data): self.writes.append(data)

    class FakeEvent:
        def __init__(self, text): self.text = text; self.stopped = False
        def stop(self): self.stopped = True

    tv = TerminalView()
    tv.session = FakeSession()
    ev = FakeEvent("ls -la")
    tv.on_paste(ev)
    assert tv.session.writes == [b"\x1b[200~ls -la\x1b[201~"]
    assert ev.stopped


def test_wheel_uses_pointer_coords():
    from aque.terminal.widget import TerminalView

    class FakeSession:
        def __init__(self): self.writes = []
        def write(self, data): self.writes.append(data)

    class FakeEvent:
        def __init__(self, x, y): self.x = x; self.y = y; self.stopped = False
        def stop(self): self.stopped = True

    tv = TerminalView()
    tv.session = FakeSession()
    tv.on_mouse_scroll_up(FakeEvent(4, 2))     # 0-based -> 1-based 5;3
    assert tv.session.writes[-1] == b"\x1b[<64;5;3M"
    tv.on_mouse_scroll_down(FakeEvent(0, 0))
    assert tv.session.writes[-1] == b"\x1b[<65;1;1M"
