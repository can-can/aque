"""A small yes/no confirmation dialog.

Guards destructive actions (e.g. killing an agent) so a stray keypress can't act
without an explicit confirmation. Returns ``True`` (confirmed) or ``False``
(cancelled) to the caller via ``dismiss(result)``.

Safe by default: the Cancel button is focused, so a stray Enter cancels. Keys:
``y`` confirms, ``n``/``Esc`` cancel; the buttons are also clickable.
"""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class ConfirmModal(ModalScreen[bool]):
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("n", "cancel", "Cancel"),
        Binding("y", "confirm", "Confirm"),
    ]

    DEFAULT_CSS = """
    ConfirmModal {
        align: center middle;
    }
    ConfirmModal #confirm-box {
        width: auto;
        max-width: 60;
        height: auto;
        background: $panel;
        border: thick $error;
        padding: 1 2;
    }
    ConfirmModal #confirm-msg {
        width: 100%;
        text-align: center;
        text-style: bold;
    }
    ConfirmModal #confirm-sub {
        width: 100%;
        text-align: center;
        color: $text-muted;
        margin-bottom: 1;
    }
    ConfirmModal #confirm-buttons {
        width: auto;
        height: auto;
        align-horizontal: center;
    }
    ConfirmModal #confirm-buttons Button {
        margin: 0 1;
    }
    """

    def __init__(self, prompt: str, subtext: str = "",
                 confirm_label: str = "Confirm") -> None:
        super().__init__()
        self._prompt = prompt
        self._subtext = subtext
        self._confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Static(self._prompt, id="confirm-msg")
            if self._subtext:
                yield Static(self._subtext, id="confirm-sub")
            with Horizontal(id="confirm-buttons"):
                yield Button(self._confirm_label, variant="error", id="confirm-yes")
                yield Button("Cancel", variant="primary", id="confirm-no")

    def on_mount(self) -> None:
        # Focus Cancel so a stray Enter is harmless on a destructive prompt.
        self.query_one("#confirm-no", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm-yes")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)
