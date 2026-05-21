"""Textual widget rendering a PtySession via render_line (per-row repaint).

Cursor rules (deliberate overrides of pyte defaults, per spec):
  * cursor always drawn — ignore screen.cursor.hidden
  * explicit fg/bg; reverse for default-colored cells
  * repaint both the previously-occupied row and the new cursor row on move
"""

from __future__ import annotations

from functools import lru_cache

from rich.segment import Segment
from rich.style import Style
from textual.geometry import Region, Size
from textual.strip import Strip
from textual.widget import Widget

from aque.terminal.keys import encode_key
from aque.terminal.pty import PtySession

_PYTE_COLORS = {
    "black", "red", "green", "brown", "blue", "magenta", "cyan", "white",
}


def _color(name: str) -> str | None:
    if name in (None, "default"):
        return None
    if name in _PYTE_COLORS:
        return "yellow" if name == "brown" else name
    # pyte gives hex strings (e.g. "ff8800") for 256/true-color.
    return f"#{name}" if len(name) == 6 else name


@lru_cache(maxsize=4096)
def cell_style(fg: str, bg: str, *, bold: bool = False, reverse: bool = False,
               is_cursor: bool = False) -> Style:
    # Memoized: a screen only uses a handful of distinct cell styles, but a full
    # repaint asks for thousands of cells. Building a Rich Style per cell every
    # frame is the dominant cost; caching makes repaints cheap. Style is
    # immutable, so sharing instances across cells is safe.
    if is_cursor:
        # Always-visible cursor cell: explicit black-on-white. We draw the
        # cursor even when DECTCEM hides it (there is no hardware cursor to fall
        # back on), so reverse-of-default isn't reliable — pin concrete colors.
        return Style(color="#000000", bgcolor="#ffffff", bold=bold)
    return Style(color=_color(fg), bgcolor=_color(bg), bold=bold, reverse=reverse)


def render_strip(session: PtySession, y: int, width: int,
                 cursor_visible: bool) -> list[Segment]:
    """Build the Rich segments for buffer row `y`, coalescing same-style runs.

    Memoized `cell_style` returns identical Style instances for identical cells,
    so we group consecutive cells with the same style into one Segment — far
    fewer Segments per row than one-per-cell, which the compositor diffs faster.
    """
    row = session.buffer_line(y)
    cx, cy = session.cursor()
    segments: list[Segment] = []
    run_chars: list[str] = []
    run_style: Style | None = None

    def flush() -> None:
        if run_chars:
            segments.append(Segment("".join(run_chars), run_style))

    for x in range(width):
        char = row.get(x)
        ch = (char.data if char is not None else " ") or " "
        is_cursor = cursor_visible and x == cx and y == cy
        if char is not None:
            style = cell_style(char.fg, char.bg, bold=char.bold,
                               reverse=char.reverse, is_cursor=is_cursor)
        else:
            style = cell_style("default", "default", is_cursor=is_cursor)
        if style is run_style:        # memoized styles compare by identity
            run_chars.append(ch)
        else:
            flush()
            run_style = style
            run_chars = [ch]
    flush()
    return segments


class TerminalView(Widget, can_focus=True):
    DEFAULT_CSS = """
    TerminalView { height: 1fr; width: 1fr; }
    """

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.session: PtySession | None = None
        self._poll_timer = None
        self._last_cursor: tuple[int, int] = (0, 0)
        self._attached_session: str | None = None
        self._pending_session: str | None = None
        # Rendered Strip per buffer row; entries are dropped when pyte marks the
        # row dirty (or on resize), so unchanged rows skip the rebuild entirely.
        self._line_cache: dict[int, Strip] = {}

    # lifecycle
    def attach(self, tmux_session: str) -> None:
        """(Re)attach the embed to a tmux session, sized to the widget.

        If the widget has no real size yet (not laid out), remember the request
        and spawn on the next resize so the PTY is never born 0x0.
        """
        if self.session is not None and self._attached_session == tmux_session:
            return  # already attached to this session — don't re-spawn tmux
        cols = self.size.width
        rows = self.size.height
        if cols < 1 or rows < 1:
            self._pending_session = tmux_session
            return
        self.detach()
        self.session = PtySession(columns=cols, lines=rows)
        self.session.spawn(["tmux", "attach-session", "-t", tmux_session])
        self._attached_session = tmux_session
        self._pending_session = None
        self._poll_timer = self.set_interval(0.03, self._poll)
        self.focus()
        self.refresh()

    def detach(self) -> None:
        if self._poll_timer is not None:
            self._poll_timer.stop()
            self._poll_timer = None
        if self.session is not None:
            self.session.close()
            self.session = None
        self._attached_session = None
        self._pending_session = None
        self._line_cache.clear()

    def on_unmount(self) -> None:
        self.detach()

    def on_resize(self, event) -> None:
        if self.session is not None:
            self.session.resize(lines=max(event.size.height, 1),
                                columns=max(event.size.width, 1))
            self._line_cache.clear()  # geometry changed — every cached row is stale
            self.refresh()
        elif self._pending_session is not None and event.size.height >= 1 and event.size.width >= 1:
            pending = self._pending_session
            self._pending_session = None
            self.attach(pending)

    # io loop
    def _poll(self) -> None:
        if self.session is None:
            return
        # Drain everything available this tick and feed it in one go, so a burst
        # of output repaints once instead of dribbling across many frames. The
        # iteration cap keeps a noisy producer from starving the event loop.
        chunks: list[bytes] = []
        for _ in range(64):
            data = self.session.read()
            if not data:
                break
            chunks.append(data)
        if chunks:
            self.session.feed(b"".join(chunks))
        cx, cy = self.session.cursor()
        dirty = self.session.dirty_lines()
        # Always repaint old + new cursor rows so the cursor never ghosts.
        if (cx, cy) != self._last_cursor:
            dirty = dirty | {self._last_cursor[1], cy}
            self._last_cursor = (cx, cy)
        for y in dirty:
            self._line_cache.pop(y, None)  # row changed — rebuild on next render
            if 0 <= y < self.size.height:
                self.refresh(Region(0, y, self.size.width, 1))
        self.session.clear_dirty()

    # rendering
    def render_line(self, y: int) -> Strip:
        if self.session is None:
            return Strip.blank(self.size.width)
        cached = self._line_cache.get(y)
        if cached is not None:
            return cached
        segments = render_strip(self.session, y, self.size.width,
                                cursor_visible=True)  # always draw cursor
        strip = Strip(segments, self.size.width)
        self._line_cache[y] = strip
        return strip

    def get_content_height(self, container: Size, viewport: Size, width: int) -> int:
        return self.size.height

    # mouse wheel
    def on_mouse_scroll_up(self, event) -> None:
        # Forward wheel to tmux so its scrollback/copy-mode responds, rather
        # than scrolling pyte's own buffer. Uses SGR mouse-wheel button 64
        # (wheel-up). NOTE: exact SGR sequence may need live tuning against
        # tmux mouse mode (e.g. `set -g mouse on`); verified only structurally,
        # NOT against a live tmux session — known unverified item.
        if self.session is not None:
            self.session.write(b"\x1b[<64;1;1M")
            event.stop()

    def on_mouse_scroll_down(self, event) -> None:
        # SGR mouse-wheel button 65 (wheel-down). Same caveat as scroll-up.
        if self.session is not None:
            self.session.write(b"\x1b[<65;1;1M")
            event.stop()

    # input
    def on_key(self, event) -> None:
        if self.session is None:
            return
        data = encode_key(event.key, getattr(event, "character", None))
        if data:
            self.session.write(data)
            event.stop()
            event.prevent_default()
