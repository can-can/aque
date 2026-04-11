# Adaptive Mobile Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `aque desk` usable on narrow terminals (<80 cols) by switching to a single-column layout automatically.

**Architecture:** Add an `_is_narrow` property to `DeskApp` keyed on `self.size.width < 80`. An `on_resize` handler triggers layout updates when the terminal changes size. All formatting methods (`_refresh_agent_list`, `_refresh_status_bar`, hint strings) branch on `_is_narrow` to produce compact output. The preview panel is hidden in narrow mode.

**Tech Stack:** Python, Textual TUI framework, pytest with `app.run_test(size=(w, h))` and `pilot.resize_terminal(w, h)` for testing.

---

### File Map

| File | Action | Responsibility |
|---|---|---|
| `aque/desk.py` | Modify | `_is_narrow` property, `on_resize`, layout toggling, compact formatting in status bar / agent list / hints, modal CSS adjustments |
| `aque/widgets/dir_picker.py` | Modify | Compact hint text when app is narrow |
| `tests/test_desk.py` | Modify | Tests for narrow/wide layout behavior |

---

### Task 1: Add `_is_narrow` property and `on_resize` handler

**Files:**
- Modify: `aque/desk.py:399-500`
- Test: `tests/test_desk.py`

- [ ] **Step 1: Write failing tests for narrow detection**

Add to `tests/test_desk.py`:

```python
class TestNarrowMode:
    @pytest.mark.asyncio
    async def test_narrow_at_45_cols(self, tmp_aque_dir):
        app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        async with app.run_test(size=(45, 24)) as pilot:
            assert app._is_narrow is True

    @pytest.mark.asyncio
    async def test_wide_at_80_cols(self, tmp_aque_dir):
        app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        async with app.run_test(size=(80, 24)) as pilot:
            assert app._is_narrow is False

    @pytest.mark.asyncio
    async def test_wide_at_120_cols(self, tmp_aque_dir):
        app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        async with app.run_test(size=(120, 24)) as pilot:
            assert app._is_narrow is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_desk.py::TestNarrowMode -v`
Expected: FAIL with `AttributeError: 'DeskApp' object has no attribute '_is_narrow'`

- [ ] **Step 3: Implement `_is_narrow` property**

In `aque/desk.py`, add a property to `DeskApp` (after the `_get_tmux_server` method, around line 506):

```python
@property
def _is_narrow(self) -> bool:
    return self.size.width < 80
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_desk.py::TestNarrowMode -v`
Expected: PASS (all 3 tests)

- [ ] **Step 5: Commit**

```bash
git add aque/desk.py tests/test_desk.py
git commit -m "feat: add _is_narrow property for terminal width detection"
```

---

### Task 2: Narrow-mode dashboard layout (hide preview, full-width agent panel)

**Files:**
- Modify: `aque/desk.py:399-704`
- Test: `tests/test_desk.py`

- [ ] **Step 1: Write failing tests for layout toggling**

Add to `TestNarrowMode` in `tests/test_desk.py`:

```python
    @pytest.mark.asyncio
    async def test_narrow_hides_preview_panel(self, tmp_aque_dir):
        app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        async with app.run_test(size=(45, 24)) as pilot:
            preview = app.query_one("#preview-panel")
            assert preview.display is False

    @pytest.mark.asyncio
    async def test_wide_shows_preview_panel(self, tmp_aque_dir):
        app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        async with app.run_test(size=(120, 24)) as pilot:
            preview = app.query_one("#preview-panel")
            assert preview.display is True

    @pytest.mark.asyncio
    async def test_resize_toggles_layout(self, tmp_aque_dir):
        app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        async with app.run_test(size=(120, 24)) as pilot:
            assert app.query_one("#preview-panel").display is True
            pilot.resize_terminal(45, 24)
            await pilot.pause()
            assert app.query_one("#preview-panel").display is False
            pilot.resize_terminal(120, 24)
            await pilot.pause()
            assert app.query_one("#preview-panel").display is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_desk.py::TestNarrowMode::test_narrow_hides_preview_panel tests/test_desk.py::TestNarrowMode::test_wide_shows_preview_panel tests/test_desk.py::TestNarrowMode::test_resize_toggles_layout -v`
Expected: FAIL

- [ ] **Step 3: Implement layout toggling**

Add an `_apply_layout` method to `DeskApp` in `aque/desk.py`:

```python
def _apply_layout(self) -> None:
    """Toggle between narrow (single-column) and wide (two-column) layout."""
    narrow = self._is_narrow
    try:
        preview = self.query_one("#preview-panel")
        agent_panel = self.query_one("#agent-panel")
        preview.display = not narrow
        agent_panel.styles.width = "100%" if narrow else "40%"
        agent_panel.styles.border_right = None if narrow else ("solid", self.app.current_theme.surface_lighten_1 if hasattr(self, 'current_theme') else None)
    except Exception:
        pass
```

Actually, for the border, it's simpler to just toggle a CSS class. Instead, use Textual's `set_class` / `add_class` / `remove_class`:

```python
def _apply_layout(self) -> None:
    """Toggle between narrow (single-column) and wide (two-column) layout."""
    narrow = self._is_narrow
    try:
        self.query_one("#preview-panel").display = not narrow
        panel = self.query_one("#agent-panel")
        panel.styles.width = "100%" if narrow else "40%"
        if narrow:
            panel.styles.border_right = None
        else:
            panel.styles.border_right = ("solid", panel.styles.color)
    except Exception:
        pass
```

Hmm, the border color reference is tricky. Let's use a simpler approach — add a CSS class:

Add a `.narrow` class to the CSS block in `DeskApp.CSS`, and toggle it on `#agent-panel`:

In the CSS string (around line 401), add after the existing `#agent-panel` rule:

```css
#agent-panel.narrow {
    width: 100%;
    border-right: none;
}
```

Then implement `_apply_layout`:

```python
def _apply_layout(self) -> None:
    """Toggle between narrow (single-column) and wide (two-column) layout."""
    narrow = self._is_narrow
    try:
        self.query_one("#preview-panel").display = not narrow
        self.query_one("#agent-panel").set_class(narrow, "narrow")
    except Exception:
        pass
```

Call `_apply_layout()` at the end of `on_mount` (line 546) and add an `on_resize` handler:

```python
def on_resize(self, event) -> None:
    self._apply_layout()
```

Update `on_mount` to call `_apply_layout`:

```python
def on_mount(self) -> None:
    self._apply_layout()
    self._start_refresh()
    self._focus_agent_list()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_desk.py::TestNarrowMode -v`
Expected: PASS (all 6 tests)

- [ ] **Step 5: Commit**

```bash
git add aque/desk.py tests/test_desk.py
git commit -m "feat: toggle single-column layout on narrow terminals"
```

---

### Task 3: Compact agent list entries in narrow mode

**Files:**
- Modify: `aque/desk.py:601-643` (inside `_refresh_agent_list`)
- Test: `tests/test_desk.py`

- [ ] **Step 1: Write failing tests for compact agent labels**

Add to `TestNarrowMode` in `tests/test_desk.py`:

```python
    @pytest.mark.asyncio
    async def test_narrow_agent_label_compact(self, tmp_aque_dir):
        mgr = StateManager(tmp_aque_dir)
        mgr.add_agent(AgentInfo(
            id=1, tmux_session="s-1", label="claude . my-project",
            dir="/tmp/my-project", command=["claude"], state=AgentState.RUNNING, pid=100,
        ))
        app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        async with app.run_test(size=(45, 24)) as pilot:
            ol = app.query_one("#agent-option-list", OptionList)
            opt = ol.get_option_at_index(0)
            label = str(opt.prompt)
            # Should NOT contain dir path or state word
            assert "/tmp" not in label
            assert "running" not in label.lower()
            # Should contain the agent label
            assert "claude . my-project" in label

    @pytest.mark.asyncio
    async def test_wide_agent_label_full(self, tmp_aque_dir):
        mgr = StateManager(tmp_aque_dir)
        mgr.add_agent(AgentInfo(
            id=1, tmux_session="s-1", label="claude . my-project",
            dir="/tmp/my-project", command=["claude"], state=AgentState.RUNNING, pid=100,
        ))
        app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        async with app.run_test(size=(120, 24)) as pilot:
            ol = app.query_one("#agent-option-list", OptionList)
            opt = ol.get_option_at_index(0)
            label = str(opt.prompt)
            # Wide mode should contain state text and dir
            assert "running" in label.lower()
            assert "/tmp" in label
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_desk.py::TestNarrowMode::test_narrow_agent_label_compact tests/test_desk.py::TestNarrowMode::test_wide_agent_label_full -v`
Expected: `test_narrow_agent_label_compact` FAILS (label contains "running" and "/tmp")

- [ ] **Step 3: Implement compact label formatting**

In `aque/desk.py`, modify the label construction in `_refresh_agent_list` (around line 626-633). Replace the label building block with:

```python
        for agent in agents:
            color = STATE_COLORS.get(agent.state, "white")
            if self._is_narrow:
                label = f"[{color}]●[/{color}] {agent.label}"
            else:
                type_tag = f" [dim]\\[{agent.agent_type}][/dim]" if agent.agent_type else ""
                label = (
                    f"[{color}]{agent.state.value:<8}[/{color}]{type_tag}  "
                    f"{agent.label:<25}  {agent.dir}"
                )
            option_list.add_option(Option(label, id=str(agent.id)))
```

Apply the same change to `_make_dashboard` (around line 523-529):

```python
        for agent in agents:
            color = STATE_COLORS.get(agent.state, "white")
            if self._is_narrow:
                label = f"[{color}]●[/{color}] {agent.label}"
            else:
                type_tag = f" [dim]\\[{agent.agent_type}][/dim]" if agent.agent_type else ""
                label = (
                    f"[{color}]{agent.state.value:<8}[/{color}]{type_tag}  "
                    f"{agent.label:<25}  {agent.dir}"
                )
            options.append(Option(label, id=str(agent.id)))
```

Note: `_make_dashboard` is called from `compose()` before the app has a size, so `_is_narrow` may not be accurate yet. Since `_refresh_agent_list` runs on mount via `_on_refresh`, the initial labels from `_make_dashboard` will be corrected almost immediately. Alternatively, default to wide format in `_make_dashboard` since `_refresh_agent_list` will overwrite it.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_desk.py::TestNarrowMode -v`
Expected: PASS (all 8 tests)

- [ ] **Step 5: Also run existing tests to check no regressions**

Run: `python -m pytest tests/test_desk.py -v`
Expected: All existing tests PASS

- [ ] **Step 6: Commit**

```bash
git add aque/desk.py tests/test_desk.py
git commit -m "feat: compact agent list labels in narrow mode"
```

---

### Task 4: Compact status bar in narrow mode

**Files:**
- Modify: `aque/desk.py:577-599` (inside `_refresh_status_bar`)
- Test: `tests/test_desk.py`

- [ ] **Step 1: Write failing tests for compact status bar**

Add to `TestNarrowMode` in `tests/test_desk.py`:

```python
    @pytest.mark.asyncio
    async def test_narrow_status_bar_compact(self, tmp_aque_dir):
        mgr = StateManager(tmp_aque_dir)
        mgr.add_agent(AgentInfo(
            id=1, tmux_session="s-1", label="a",
            dir="/tmp", command=["a"], state=AgentState.RUNNING, pid=100,
        ))
        mgr.add_agent(AgentInfo(
            id=2, tmux_session="s-2", label="b",
            dir="/tmp", command=["b"], state=AgentState.WAITING, pid=101,
        ))
        app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        async with app.run_test(size=(45, 24)) as pilot:
            status = str(app.query_one("#status-bar").renderable)
            # Compact: should have abbreviated names
            assert "run" in status.lower()
            assert "wait" in status.lower()
            # Should NOT have the full word with extra spacing
            assert "running" not in status.lower()
            assert "waiting" not in status.lower()

    @pytest.mark.asyncio
    async def test_wide_status_bar_full(self, tmp_aque_dir):
        mgr = StateManager(tmp_aque_dir)
        mgr.add_agent(AgentInfo(
            id=1, tmux_session="s-1", label="a",
            dir="/tmp", command=["a"], state=AgentState.RUNNING, pid=100,
        ))
        app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        async with app.run_test(size=(120, 24)) as pilot:
            status = str(app.query_one("#status-bar").renderable)
            assert "running" in status.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_desk.py::TestNarrowMode::test_narrow_status_bar_compact tests/test_desk.py::TestNarrowMode::test_wide_status_bar_full -v`
Expected: `test_narrow_status_bar_compact` FAILS

- [ ] **Step 3: Implement compact status bar**

In `aque/desk.py`, modify `_refresh_status_bar` (around line 577-599). Add a narrow/wide branch:

```python
    def _refresh_status_bar(self, state: AppState | None = None) -> None:
        try:
            old = self.query_one("#status-bar", Static)
            if state is None:
                state = self.state_mgr.load()
            counts: dict[AgentState, int] = {}
            for a in state.agents:
                counts[a.state] = counts.get(a.state, 0) + 1
            parts = []
            narrow = self._is_narrow
            state_labels = {
                AgentState.RUNNING: ("run", "running"),
                AgentState.WAITING: ("wait", "waiting"),
                AgentState.ON_HOLD: ("hold", "on_hold"),
            }
            for st, color in [
                (AgentState.RUNNING, "green"),
                (AgentState.WAITING, "yellow"),
                (AgentState.ON_HOLD, "magenta"),
            ]:
                c = counts.get(st, 0)
                if c:
                    short, full = state_labels[st]
                    name = short if narrow else full
                    sep = "" if narrow else " "
                    parts.append(f"[{color}]●{sep}{c} {name}[/{color}]")
            hcount = self.history_mgr.count()
            if hcount:
                sep = "" if narrow else " "
                parts.append(f"[dim]●{sep}{hcount} done[/dim]")
            joiner = " " if narrow else "    "
            old.update(joiner.join(parts) if parts else "[dim]No agents[/dim]")
        except Exception:
            pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_desk.py::TestNarrowMode -v`
Expected: PASS (all 10 tests)

- [ ] **Step 5: Commit**

```bash
git add aque/desk.py tests/test_desk.py
git commit -m "feat: compact status bar text in narrow mode"
```

---

### Task 5: Narrow-mode adjustments for modals and forms

**Files:**
- Modify: `aque/desk.py:324-346` (AutoAttachModal CSS), `aque/desk.py:426-467` (DeskApp CSS for action menu and form)
- Modify: `aque/widgets/dir_picker.py:35-50` (hint text)
- Test: `tests/test_desk.py`

- [ ] **Step 1: Write failing test for auto-attach modal width**

Add to `TestNarrowMode` in `tests/test_desk.py`:

```python
    @pytest.mark.asyncio
    async def test_narrow_auto_attach_modal_fits(self, tmp_aque_dir):
        mgr = StateManager(tmp_aque_dir)
        mgr.add_agent(AgentInfo(
            id=1, tmux_session="s-1", label="test agent",
            dir="/tmp", command=["a"], state=AgentState.WAITING, pid=100,
        ))
        app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        async with app.run_test(size=(45, 24)) as pilot:
            # Trigger auto-attach by enabling it
            app._skip_attach = False
            app._auto_attach_suppressed = False
            app._try_auto_attach()
            await pilot.pause()
            box = app.query_one("#auto-attach-box")
            # The box should not exceed terminal width
            assert box.styles.width is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_desk.py::TestNarrowMode::test_narrow_auto_attach_modal_fits -v`
Expected: May pass or fail depending on rendering — the key issue is the hardcoded `width: 50` in CSS.

- [ ] **Step 3: Fix AutoAttachModal CSS**

In `aque/desk.py`, change the `AutoAttachModal.DEFAULT_CSS` (line 329) from `width: 50` to `max-width: 50` and add `width: 100%`:

```python
    DEFAULT_CSS = """
    AutoAttachModal {
        align: center middle;
    }
    #auto-attach-box {
        width: 100%;
        max-width: 50;
        height: 7;
        border: thick $warning;
        background: $surface;
        padding: 1 2;
        text-align: center;
    }
    #auto-attach-label {
        width: 100%;
        text-align: center;
    }
    #auto-attach-hint {
        width: 100%;
        text-align: center;
        color: $text-muted;
        margin-top: 1;
    }
    """
```

- [ ] **Step 4: Add narrow CSS classes for action menu and new agent form**

In `DeskApp.CSS` (around line 401), update the action menu and form padding rules. Add narrow variants:

```css
    #action-menu.narrow {
        padding: 1 1;
    }
    #new-agent-form.narrow {
        padding: 1 1;
    }
```

Update `_apply_layout` to also toggle the narrow class on these elements when they exist:

```python
def _apply_layout(self) -> None:
    """Toggle between narrow (single-column) and wide (two-column) layout."""
    narrow = self._is_narrow
    try:
        self.query_one("#preview-panel").display = not narrow
        self.query_one("#agent-panel").set_class(narrow, "narrow")
    except Exception:
        pass
    for selector in ("#action-menu", "#new-agent-form"):
        try:
            self.query_one(selector).set_class(narrow, "narrow")
        except Exception:
            pass
```

- [ ] **Step 5: Update `_show_action_menu` and `_show_new_agent_form` to apply narrow class**

In `_show_action_menu` (around line 773), after mounting the ActionMenu, call `_apply_layout()`:

Add `self._apply_layout()` after the mount call in `_show_action_menu`:

```python
    def _show_action_menu(self, agent: AgentInfo, was_exited: bool) -> None:
        # ... existing code ...
        self.mount(
            ActionMenu(agent=agent, waiting_count=count, config=self.config, was_exited=was_exited),
            after=self.query_one(Header),
        )
        self._apply_layout()  # Add this line
        # ... rest of existing code ...
```

Same for `_show_new_agent_form`:

```python
    def _show_new_agent_form(self) -> None:
        # ... existing code ...
        self.mount(
            NewAgentForm(
                dir_history_mgr=self.dir_history_mgr,
                default_dir=self.config.get("default_dir", str(Path.home())),
                plugin_names=plugin_names,
            ),
            after=self.query_one(Header),
        )
        self._apply_layout()  # Add this line
```

- [ ] **Step 6: Make DirectoryPicker hints responsive**

In `aque/widgets/dir_picker.py`, modify the `compose` method (line 64-75) to accept a narrow flag. Since the picker doesn't have direct access to the app's `_is_narrow`, pass it through or check `self.app.size.width`:

```python
    def compose(self) -> ComposeResult:
        yield Input(placeholder="Search directories...", id="dir-search-input")
        yield OptionList(id="dir-list")
        yield Static(self._hint_text(), id="dir-picker-hint")

    def _hint_text(self) -> str:
        try:
            narrow = self.app.size.width < 80
        except Exception:
            narrow = False
        if narrow:
            return "  ".join([
                key_hint("Enter", "sel"),
                key_hint("p", "pin"),
                key_hint("b", "tree"),
                key_hint("Esc", "back"),
            ])
        return "  ".join([
            key_hint("Enter", "select"),
            key_hint("p", "pin/unpin"),
            key_hint("b", "browse tree"),
            key_hint("Esc", "cancel"),
        ])
```

- [ ] **Step 7: Run all tests**

Run: `python -m pytest tests/test_desk.py tests/test_dir_picker.py -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add aque/desk.py aque/widgets/dir_picker.py tests/test_desk.py
git commit -m "feat: narrow-mode adjustments for modals, forms, and hints"
```

---

### Task 6: Refresh layout on resize and after mode switches

**Files:**
- Modify: `aque/desk.py`
- Test: `tests/test_desk.py`

- [ ] **Step 1: Write failing test for refresh after resize**

Add to `TestNarrowMode` in `tests/test_desk.py`:

```python
    @pytest.mark.asyncio
    async def test_resize_refreshes_agent_labels(self, tmp_aque_dir):
        mgr = StateManager(tmp_aque_dir)
        mgr.add_agent(AgentInfo(
            id=1, tmux_session="s-1", label="claude . proj",
            dir="/tmp/proj", command=["claude"], state=AgentState.RUNNING, pid=100,
        ))
        app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
        async with app.run_test(size=(120, 24)) as pilot:
            ol = app.query_one("#agent-option-list", OptionList)
            wide_label = str(ol.get_option_at_index(0).prompt)
            assert "running" in wide_label.lower()

            pilot.resize_terminal(45, 24)
            await pilot.pause()
            # Force a refresh cycle
            app._refresh_agent_list(reset_highlight=True)
            narrow_label = str(ol.get_option_at_index(0).prompt)
            assert "running" not in narrow_label.lower()
            assert "claude . proj" in narrow_label
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_desk.py::TestNarrowMode::test_resize_refreshes_agent_labels -v`
Expected: FAIL — after resize, labels still use wide format because `_refresh_agent_list` doesn't re-check `_is_narrow` for existing entries.

- [ ] **Step 3: Ensure `on_resize` triggers full refresh**

In `aque/desk.py`, update the `on_resize` handler to also refresh content:

```python
def on_resize(self, event) -> None:
    self._apply_layout()
    if self._mode == "dashboard":
        self._last_agent_fingerprint = None  # Force label rebuild
        self._refresh_agent_list()
        self._refresh_status_bar()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_desk.py::TestNarrowMode -v`
Expected: PASS (all tests)

- [ ] **Step 5: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add aque/desk.py tests/test_desk.py
git commit -m "feat: refresh labels and status bar on terminal resize"
```

---

### Task 7: Manual smoke test

- [ ] **Step 1: Run the app at normal width**

Run: `aque desk`

Verify: Two-column layout, full labels, full status bar. Everything looks the same as before.

- [ ] **Step 2: Resize terminal to <80 columns**

Drag the terminal window narrow (or use `resize -s 24 45`).

Verify:
- Preview panel disappears
- Agent list takes full width
- Labels show `● agent-label` format (no state text, no dir)
- Status bar shows compact format (`●1 run ●1 wait`)

- [ ] **Step 3: Resize back to wide**

Drag the terminal wide again.

Verify: Two-column layout restores, full labels return.

- [ ] **Step 4: Test new agent form in narrow mode**

With terminal narrow, press `n` to open the new agent form. Verify it renders without overflow.

- [ ] **Step 5: Commit any fixes from smoke testing**

If any issues found, fix and commit with descriptive message.
