# Adaptive Mobile Layout for AQ

## Problem

AQ's TUI assumes a wide terminal (~120 columns). When used via SSH from a phone (e.g., iPhone Pro Max getting ~45 cols portrait), the two-column dashboard is unusable: panels are too narrow, labels wrap/truncate, key hints overflow, and the preview pane is unreadable.

## Solution

Detect terminal width and switch to a single-column layout on narrow terminals. Wide terminals get today's unchanged experience.

## Breakpoint

- **Narrow mode:** terminal width < 80 columns
- **Wide mode:** terminal width >= 80 columns
- Responds to terminal resize events in real-time (Textual handles resize via `on_resize`)

## Dashboard — Narrow Mode

### Layout
- Single-column, full-width agent list. No preview panel.
- The `#preview-panel` is hidden (`display: False`).
- The `#agent-panel` takes `width: 100%` with no right border.

### Agent List Entries
Current wide format:
```
running   [claude]  claude . my-project  ~/Projects/my-project
```

Narrow format — single line, state dot + label only:
```
● claude . my-project
```

- The dot color indicates state (green=running, yellow=waiting, magenta=hold, etc.) using existing `STATE_COLORS`.
- Directory path and type tag are dropped.
- No padding on state text (the dot replaces the word).

### Status Bar
Current wide format:
```
● 2 running    ● 1 waiting    ● 3 done
```

Narrow format — compact:
```
●2 run ●1 wait ●3 done
```

Abbreviated state names, no extra spacing.

### Navigation
- Arrow keys navigate the list (unchanged).
- **Enter attaches directly** — no preview step. Same behavior as wide mode's `on_option_list_option_selected`.
- All other keybindings (n, k, h, q) work identically.

### Footer / Key Hints
Shortened format:
```
[n]New [k]Kill [q]Quit
```
Instead of the wider spaced format.

## Dashboard — Wide Mode (>=80 cols)

Completely unchanged. Two-column layout (40%/60%), full agent labels with state text + type tag + dir, full status bar text, full key hints.

## Other Views — Narrow Adjustments

### AutoAttachModal
- Current: `width: 50` (hardcoded character count).
- Narrow: `width: 100%` so it fills available space instead of overflowing.
- Content text unchanged — it already wraps.

### Action Menu
- Current: `padding: 2 4`.
- Narrow: `padding: 1 1` to save horizontal space.
- Option text unchanged — it's already short enough.

### New Agent Form
- Current: `padding: 2 4`.
- Narrow: `padding: 1 1`.
- Step indicator text: truncate dir/cmd display if they exceed available width.
- Key hints: use the same shortened format as the dashboard footer.

### DirectoryPicker
- Current hint: `[Enter] select  [p] pin/unpin  [b] browse tree  [Esc] cancel`
- Narrow hint: `[↵]sel [p]pin [b]tree [⎋]back`
- Path display: already uses `~` shorthand, no further change needed.

## Implementation Approach

### Width Detection
Add an `_is_narrow` property to `DeskApp` that checks `self.size.width < 80`. Textual's `App.size` provides the current terminal dimensions. Use `on_resize` to trigger layout updates when the terminal is resized.

### Conditional Rendering
The layout switching is done by:
1. Toggling `display` on `#preview-panel`
2. Adjusting `width` on `#agent-panel`
3. Using `_is_narrow` to choose between wide/narrow text formatting in `_refresh_agent_list`, `_refresh_status_bar`, and hint strings

### Files Modified
- `aque/desk.py` — main layout logic, CSS, status bar, agent list formatting, modal sizing
- `aque/widgets/dir_picker.py` — hint text formatting

### No New Files
No new files, classes, or abstractions needed. This is conditional formatting within existing components.

## What Does NOT Change
- All keybindings and their behavior
- State management (`state.py`)
- Agent launching, attaching, killing, holding
- Configuration (`config.py`)
- Monitor/daemon logic
- CLI interface
- All functionality — this is purely a display/layout change
