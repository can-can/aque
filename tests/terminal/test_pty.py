from aque.terminal.pty import PtySession


def test_feed_plain_text_lands_on_screen():
    s = PtySession(columns=20, lines=5)
    s.feed(b"hello")
    line0 = s.display()[0]
    assert line0.startswith("hello")


def test_cursor_advances():
    s = PtySession(columns=20, lines=5)
    s.feed(b"abc")
    assert s.cursor() == (3, 0)  # (x, y)


def test_newline_moves_down():
    s = PtySession(columns=20, lines=5)
    s.feed(b"a\r\nb")
    assert s.display()[0].startswith("a")
    assert s.display()[1].startswith("b")


def test_resize_changes_dimensions():
    s = PtySession(columns=20, lines=5)
    s.resize(lines=10, columns=40)
    assert len(s.display()) == 10
    assert s.columns == 40


def test_dirty_lines_tracked():
    s = PtySession(columns=20, lines=5)
    s.clear_dirty()
    s.feed(b"x")
    assert 0 in s.dirty_lines()
