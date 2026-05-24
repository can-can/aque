"""Design tokens for the aque desk TUI.

Maps the web prototype's light-background palette onto Rich truecolor hex so the
desk reads with the same visual hierarchy in a terminal: a colored state dot, a
filled vendor "pill", a bold name, and a soft "auto/manual" chip on the right.
All colours are tuned for legibility on the cream Screen background set in
``DeskApp.CSS``.
"""
from aque.state import AgentState


# State-dot colours, tuned to read on the cream background.
STATE_COLORS: dict[AgentState, str] = {
    AgentState.RUNNING: "#16A34A",   # green-600
    AgentState.WAITING: "#CA8A04",   # amber-600 (named "yellow" washes out on cream)
    AgentState.EXITED: "#9CA3AF",    # gray-400
    AgentState.ON_HOLD: "#9333EA",   # purple-600
    AgentState.DONE: "#DC2626",      # red-600
}


# Vendor accent colours — used as the pill's *text* colour. Tuned dark enough
# to read on the matching light fill below (and kept as the single source of
# truth the vendor-colour BDD step asserts against).
#
#   claude — amber
TYPE_COLORS: dict[str, str] = {
    "claude": "#B45309",
}


# Light tint backgrounds for each vendor pill, paired with TYPE_COLORS text.
TYPE_FILLS: dict[str, str] = {
    "claude": "#FBE6D4",
}


# Mode chip colours (text on fill). Terminals can't draw a rounded border, so
# a soft filled block stands in for the design's outlined badge.
AUTO_CHIP = ("#15803D", "#CDEFD8")    # green text on light green
MANUAL_CHIP = ("#6B7280", "#E5E7EB")  # gray text on light gray


def type_chip_markup(agent_type: str | None) -> str:
    """Rich markup for a filled vendor pill — e.g. ``[#B45309 on #FBE6D4] claude [/]``.

    Empty string when the agent has no type (polling-only). The vendor's accent
    is the text colour; a light tint of it is the fill, approximating the
    design's rounded badge with a padded coloured block.
    """
    if not agent_type:
        return ""
    fg = TYPE_COLORS.get(agent_type, "#475569")
    bg = TYPE_FILLS.get(agent_type, "#E2E8F0")
    return f"[{fg} on {bg}] {agent_type} [/]"


def auto_chip_markup(auto_respond: bool) -> str:
    """Rich markup for the auto/manual chip at the right edge of every row.

    Renders as a soft ``auto`` (green) or ``manual`` (gray) filled block.
    """
    fg, bg = AUTO_CHIP if auto_respond else MANUAL_CHIP
    label = "auto" if auto_respond else "manual"
    return f"[{fg} on {bg}] {label} [/]"
