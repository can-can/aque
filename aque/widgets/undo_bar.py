"""UndoBar — bottom-docked transient notification with an inline undo cue.

Shown for ~5 seconds after a destructive action (kill, done). The user can
press ``u`` while it's up to restore the snapshot. Self-dismissing — no
manual close required.
"""
from textual.widgets import Static


class UndoBar(Static):
    """A bottom-docked, auto-dismissing undo notification."""

    DEFAULT_CSS = """
    UndoBar {
        dock: bottom;
        height: 1;
        padding: 0 2;
        background: $surface-darken-1;
        color: $text;
        text-align: center;
        layer: notification;
    }
    """

    def __init__(self, message: str) -> None:
        super().__init__(
            f"[bold yellow]u[/bold yellow] [dim]{message} · press to undo[/dim]",
            id="undo-bar",
        )
