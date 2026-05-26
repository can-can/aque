"""HelpModal — keyboard shortcut reference shown by pressing ``?``.

A modal screen listing every binding by category. Esc closes. Each row is
``key  ·  description`` so the user can match what they see in the footer
hints to a full reference card without leaving the desk.
"""
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static


HELP_ROWS = [
    ("Navigation", [
        ("↑ ↓",   "navigate list"),
        ("Enter", "attach to selected"),
        ("Space", "peek without attaching"),
        ("/",     "filter list inline"),
    ]),
    ("Filters", [
        ("1",   "filter running"),
        ("2",   "filter waiting"),
        ("3",   "filter on_hold"),
        ("4",   "filter exited"),
        ("Esc", "clear filter / close pill"),
    ]),
    ("Actions", [
        ("n",      "new agent"),
        ("k",      "kill selected"),
        ("h",      "hold / resume"),
        ("a",      "toggle auto-response"),
        ("Ctrl+↵",  "responder embed"),
        ("u",      "undo last action"),
        ("⌘K", "command palette"),
        ("?",      "this help"),
        ("q",      "quit"),
    ]),
]


class HelpModal(ModalScreen[None]):
    """Keyboard shortcut overlay."""

    DEFAULT_CSS = """
    HelpModal {
        align: center middle;
    }
    HelpModal #help-box {
        width: 60;
        max-width: 90%;
        height: auto;
        background: $surface;
        border: round $primary;
        padding: 1 2;
    }
    HelpModal .help-section {
        text-style: bold;
        color: $accent;
        margin-top: 1;
    }
    HelpModal .help-row {
        color: $text;
    }
    HelpModal .help-foot {
        color: $text-muted;
        margin-top: 1;
        text-align: center;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("question_mark", "dismiss", "Close"),
    ]

    def compose(self) -> ComposeResult:
        box = Vertical(id="help-box")
        box._add_child(Static("[b]Keyboard shortcuts[/b]", id="help-title"))
        for section, rows in HELP_ROWS:
            box._add_child(Static(section, classes="help-section"))
            for key, desc in rows:
                box._add_child(Static(
                    f"  [bold]{key:<8}[/bold]  [dim]{desc}[/dim]",
                    classes="help-row",
                ))
        box._add_child(Static("Esc to close", classes="help-foot"))
        yield box
