"""Textual widget rendering a PtySession via render_line (per-row repaint).

Cursor rules (deliberate overrides of pyte defaults, per spec):
  * cursor always drawn — ignore screen.cursor.hidden
  * explicit fg/bg; reverse for default-colored cells
  * repaint both the previously-occupied row and the new cursor row on move
"""

from __future__ import annotations

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


def cell_style(fg: str, bg: str, *, bold: bool = False, reverse: bool = False,
               is_cursor: bool = False) -> Style:
    f = _color(fg)
    b = _color(bg)
    if is_cursor and f is None and b is None:
        # Default-colored cell under the cursor: use reverse so it's visible
        # against any theme without inventing concrete colors.
        return Style(reverse=True)
    if is_cursor:
        # Concrete colors: swap to make the cursor explicit.
        return Style(color=b or "black", bgcolor=f or "white", bold=bold)
    return Style(color=f, bgcolor=b, bold=bold, reverse=reverse)


def render_strip(session: PtySession, y: int, width: int,
                 cursor_visible: bool) -> list[Segment]:
    """Build the Rich segments for buffer row `y`."""
    row = session.buffer_line(y)
    cx, cy = session.cursor()
    segments: list[Segment] = []
    for x in range(width):
        char = row.get(x)
        ch = char.data if char is not None else " "
        if char is not None:
            style = cell_style(char.fg, char.bg, bold=char.bold,
                               reverse=char.reverse,
                               is_cursor=(cursor_visible and x == cx and y == cy))
        else:
            style = cell_style("default", "default",
                               is_cursor=(cursor_visible and x == cx and y == cy))
        segments.append(Segment(ch or " ", style))
    return segments


class TerminalView(Widget, can_focus=True):
    DEFAULT_CSS = "TerminalView { height: 1fr; width: 1fr; }"

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.session: PtySession | None = None
        self._poll_timer = None
        self._last_cursor: tuple[int, int] = (0, 0)
        self._attached_session: str | None = None

    # lifecycle
    def attach(self, tmux_session: str) -> None:
        """(Re)attach the embed to a tmux session, sized to the widget."""
        if self.session is not None and self._attached_session == tmux_session:
            return  # already attached to this session — don't re-spawn tmux
        self.detach()
        cols = max(self.size.width, 1)
        rows = max(self.size.height, 1)
        self.session = PtySession(columns=cols, lines=rows)
        self.session.spawn(["tmux", "attach-session", "-t", tmux_session])
        self._attached_session = tmux_session
        self._poll_timer = self.set_interval(0.03, self._poll)
        self.refresh()

    def detach(self) -> None:
        if self._poll_timer is not None:
            self._poll_timer.stop()
            self._poll_timer = None
        if self.session is not None:
            self.session.close()
            self.session = None
        self._attached_session = None

    def on_unmount(self) -> None:
        self.detach()

    def on_resize(self, event) -> None:
        if self.session is not None:
            self.session.resize(lines=max(event.size.height, 1),
                                columns=max(event.size.width, 1))
            self.refresh()

    # io loop
    def _poll(self) -> None:
        if self.session is None:
            return
        data = self.session.read()
        if data:
            self.session.feed(data)
        cx, cy = self.session.cursor()
        dirty = self.session.dirty_lines()
        # Always repaint old + new cursor rows so the cursor never ghosts.
        if (cx, cy) != self._last_cursor:
            dirty = dirty | {self._last_cursor[1], cy}
            self._last_cursor = (cx, cy)
        for y in dirty:
            if 0 <= y < self.size.height:
                self.refresh(Region(0, y, self.size.width, 1))
        self.session.clear_dirty()

    # rendering
    def render_line(self, y: int) -> Strip:
        if self.session is None:
            return Strip.blank(self.size.width)
        segments = render_strip(self.session, y, self.size.width,
                                cursor_visible=True)  # always draw cursor
        return Strip(segments, self.size.width)

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
