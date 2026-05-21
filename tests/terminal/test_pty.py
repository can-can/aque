import os
import time

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


def test_close_reaps_child():
    s = PtySession(columns=20, lines=5)
    s.spawn(["sleep", "5"])
    pid = s._pid
    assert pid is not None
    s.close()
    time.sleep(0.1)
    try:
        result = os.waitpid(pid, os.WNOHANG)
        assert result == (0, 0), f"child not reaped, got {result}"
    except ChildProcessError:
        pass  # already reaped — acceptable


def test_feed_private_dsr_does_not_crash():
    """tmux emits a private Device Status Report (CSI ? 996 n) that pyte 0.8.2's
    base report_device_status can't handle; feeding it must not raise, and the
    terminal must keep working afterwards."""
    s = PtySession(columns=20, lines=5)
    s.feed(b"\x1b[?996n")          # private DSR — previously crashed
    s.feed(b"hello")
    assert s.display()[0].startswith("hello")


def test_feed_swallows_arbitrary_bad_sequences():
    s = PtySession(columns=20, lines=5)
    # Garbage / partial escape sequences must never propagate an exception.
    s.feed(b"\x1b[?1049h\x1b[?12l\x1b[?25h\x1b[6 q\x1b[>4;2m")
    s.feed(b"ok")
    assert "ok" in s.display()[0]
