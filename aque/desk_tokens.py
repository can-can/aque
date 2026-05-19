"""Design tokens for the aque desk TUI.

Maps the web prototype's oklch palette onto Textual/Rich named colors so the
desk reads with the same visual hierarchy in a terminal: a colored state dot,
a vendor-coloured type chip, and a soft "auto/manual" chip on the right.
"""
from aque.state import AgentState


STATE_COLORS: dict[AgentState, str] = {
    AgentState.RUNNING: "green",
    AgentState.WAITING: "yellow",
    AgentState.FOCUSED: "blue",
    AgentState.EXITED: "dim",
    AgentState.ON_HOLD: "magenta",
    AgentState.DONE: "red",
}


# Vendor accent colours. The design defines these as oklch values in a
# light-bg context; we map each to a truecolor hex value that reads on
# both light and dark terminals.
#
#   claude   — amber (warmth)
#   codex    — slate blue (cool, neutral)
#   aider    — teal (a more saturated cyan-green)
#   gemini   — indigo (Google's indigo-violet)
#   opencode — emerald (open-source green)
#
# Rich accepts ``#rrggbb`` strings interchangeably with named colours.
TYPE_COLORS: dict[str, str] = {
    "claude":   "#D69E2E",
    "codex":    "#5A7A9E",
    "aider":    "#319795",
    "gemini":   "#7C3AED",
    "opencode": "#48BB78",
}


def type_chip_markup(agent_type: str | None) -> str:
    """Rich markup for a vendor type chip — e.g. ``[yellow][claude][/yellow]``.

    Empty string when the agent has no type (polling-only). The brackets are
    escaped so Rich treats them as literal characters, not markup tags.
    """
    if not agent_type:
        return ""
    color = TYPE_COLORS.get(agent_type, "white")
    return f"[{color}]\\[{agent_type}][/{color}]"


def auto_chip_markup(auto_respond: bool, has_responder: bool) -> str:
    """Rich markup for the auto/manual chip at the right edge of a row.

    Renders as ``auto`` (green) when on, ``manual`` (dim) when off, and an
    empty string when there is no responder so the chip is not implying a
    toggle the user can't act on.
    """
    if not has_responder:
        return ""
    if auto_respond:
        return "[green]auto[/green]"
    return "[dim]manual[/dim]"
