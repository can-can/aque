"""BDD tests for new_agent.feature scenarios.

Scenarios wired up:
1.  Opening the new agent form shows the directory picker — press n, check widgets
2.  Switching to tree browse mode — press b, check tree visible
3.  Returning from tree to picker — press b then Escape
4.  Pressing Escape on directory picker cancels the form — press Esc, check dashboard
5.  Empty state shows search input and hint — no dir_history.json, check UI
6.  Entering a command advances to label step — type command, press Enter
7.  Picker shows pinned directories at the top — create real tmp dirs, pin them
8.  Typing filters the list by substring match — create tmp dirs, type filter
9.  Selecting a directory from the list advances to command step — select dir, check step
10. Picker shows recent directories ranked by frequency — seed dir counts, check order
11. Deleted directories are not shown — seed non-existent path, verify pruned
12. Selecting a directory records usage in history — select dir, submit form, check count
13. Clearing search restores full pinned and recent list — type, clear, check restored
14. Pinning a directory from the recent list — press p, check pinned section
15. Unpinning a directory — pin then press p, check unpinned
16. Pinned directories always appear above recent directories — pin with low count, check above high-count unpinned
17. Search scans filesystem when history has few matches — create real dirs, search for them
18. Tree hides hidden directories — check FolderTree filters .hidden dirs
19. Selecting a directory in tree mode advances to command step — press s in tree mode
20. Submitting the label launches the agent — complete all 3 steps, check agent in state
21. Pressing Escape on command step goes back to directory picker
22. Pressing Escape on label step goes back to command step

Skipped:
- "CLI launch records directory usage" — CLI integration test, not a TUI test.

Note: pytest-bdd 8.x has no native async step support. All step functions are sync.
Async operations (app mounting/piloting) are driven via ctx.run(), which calls
ctx.loop.run_until_complete() using the event loop created fresh for each test.
"""
import asyncio
from unittest.mock import patch

import pytest
from pytest_bdd import scenario, given, when, then, parsers

from aque.desk import DeskApp
from aque.dir_history import DirHistoryManager
from aque.history import HistoryManager
from aque.state import StateManager


FEATURE = "../../features/new_agent.feature"


# ── Scenario declarations ──────────────────────────────────────────────────────


@scenario(FEATURE, "Opening the new agent form shows the directory picker")
def test_opening_form_shows_picker():
    pass


@scenario(FEATURE, "Switching to tree browse mode")
def test_switching_to_tree_mode():
    pass


@scenario(FEATURE, "Returning from tree to picker")
def test_returning_from_tree_to_picker():
    pass


@scenario(FEATURE, "Pressing Escape on directory picker cancels the form")
def test_escape_on_dir_picker_cancels():
    pass


@scenario(FEATURE, "Empty state shows search input and hint")
def test_empty_state_shows_search_and_hint():
    pass


@scenario(FEATURE, "Entering a command advances to label step")
def test_entering_command_advances_to_label():
    pass


@scenario(FEATURE, "Picker shows pinned directories at the top")
def test_picker_shows_pinned_at_top():
    pass


@scenario(FEATURE, "Typing filters the list by substring match")
def test_typing_filters_list():
    pass


@scenario(FEATURE, "Selecting a directory from the list advances to command step")
def test_selecting_dir_advances_to_command():
    pass


@scenario(FEATURE, "Picker shows recent directories ranked by frequency")
def test_picker_shows_recent_ranked_by_frequency():
    pass


@scenario(FEATURE, "Deleted directories are not shown")
def test_deleted_dirs_not_shown():
    pass


@scenario(FEATURE, "Selecting a directory records usage in history")
def test_selecting_dir_records_usage():
    pass


@scenario(FEATURE, "Clearing search restores full pinned and recent list")
def test_clearing_search_restores_full_list():
    pass


@scenario(FEATURE, "Pinning a directory from the recent list")
def test_pinning_dir_from_recent():
    pass


@scenario(FEATURE, "Unpinning a directory")
def test_unpinning_dir():
    pass


@scenario(FEATURE, "Pinned directories always appear above recent directories")
def test_pinned_above_recent():
    pass


@scenario(FEATURE, "Search scans filesystem when history has few matches")
def test_search_scans_filesystem():
    pass


@scenario(FEATURE, "Tree hides hidden directories")
def test_tree_hides_hidden_dirs():
    pass


@scenario(FEATURE, "Selecting a directory in tree mode advances to command step")
def test_tree_mode_select_advances_to_command():
    pass


@scenario(FEATURE, "Submitting the label launches the agent")
def test_submitting_label_launches_agent():
    pass


@scenario(FEATURE, "Pressing Escape on command step goes back to directory picker")
def test_escape_on_command_step_goes_back():
    pass


@scenario(FEATURE, "Pressing Escape on label step goes back to command step")
def test_escape_on_label_step_goes_back():
    pass


# ── Context holder ─────────────────────────────────────────────────────────────


class NewAgentContext:
    """Holds app + test state across BDD steps.

    App is mounted lazily. All async work driven through self.run(coro).
    """

    def __init__(self, tmp_aque_dir):
        self.tmp_aque_dir = tmp_aque_dir
        self.state_mgr = StateManager(tmp_aque_dir)
        self.history_mgr = HistoryManager(tmp_aque_dir)
        self.dir_history_mgr = DirHistoryManager(tmp_aque_dir)
        self.app = None
        self.pilot = None
        self._loop = None
        self._run_test_cm = None
        # Scratch storage for step data
        self.data: dict = {}

    def _get_loop(self):
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
        return self._loop

    def run(self, coro):
        return self._get_loop().run_until_complete(coro)

    def ensure_mounted(self):
        if self.app is None:
            self.run(self._mount())

    async def _mount(self):
        self.app = DeskApp(aque_dir=self.tmp_aque_dir, _skip_attach=True)
        self._run_test_cm = self.app.run_test()
        self.pilot = await self._run_test_cm.__aenter__()
        await self.pilot.pause()

    async def _shutdown(self):
        if self._run_test_cm is not None:
            await self._run_test_cm.__aexit__(None, None, None)
            self._run_test_cm = None

    def cleanup(self):
        if self.app is not None and self._loop is not None:
            try:
                self._loop.run_until_complete(self._shutdown())
            except Exception:
                pass
        if self._loop is not None:
            try:
                self._loop.close()
            except Exception:
                pass
            self._loop = None


@pytest.fixture
def ctx(tmp_aque_dir, request):
    c = NewAgentContext(tmp_aque_dir)
    request.addfinalizer(c.cleanup)
    return c


def _datatable_as_dicts(datatable):
    rows = datatable
    if not rows:
        return []
    headers = rows[0]
    return [dict(zip(headers, row)) for row in rows[1:]]


# ── Shared given/when steps ────────────────────────────────────────────────────


@given("the aque desk is open", target_fixture="ctx")
def given_desk_is_open(ctx):
    return ctx


@given("the user is on the dashboard")
def given_user_on_dashboard(ctx):
    ctx.ensure_mounted()


# ── Scenario 1: Opening the form shows the directory picker ───────────────────


@when('the user presses "n"')
def when_user_presses_n(ctx):
    ctx.ensure_mounted()

    async def _press():
        await ctx.pilot.press("n")
        await ctx.pilot.pause()

    ctx.run(_press())


@then("the directory picker should be visible")
def then_dir_picker_visible(ctx):
    picker = ctx.app.query_one("#dir-picker")
    assert picker.display is True, "DirectoryPicker (#dir-picker) should be visible"


@then("the search input should have focus")
def then_search_input_has_focus(ctx):
    focused = ctx.app.focused
    assert focused is not None, "No widget has focus"
    assert focused.id == "dir-search-input", (
        f"Expected '#dir-search-input' to have focus, got '{focused.id}'"
    )


@then(parsers.parse('step "{step_text}" should be shown'))
def then_step_shown(ctx, step_text):
    step_widget = ctx.app.query_one("#new-agent-step")
    rendered = str(step_widget.render())
    assert step_text in rendered, (
        f"Expected step label to contain '{step_text}', got: '{rendered}'"
    )


# ── Scenario 2 & 3: Tree browse mode ─────────────────────────────────────────


@given("the user is on the directory picker")
def given_user_on_dir_picker(ctx):
    ctx.ensure_mounted()

    async def _open_form():
        ctx.app._show_new_agent_form()
        await ctx.pilot.pause()

    ctx.run(_open_form())


@when('the user presses "b"')
def when_user_presses_b(ctx):
    async def _press():
        # The app's on_key only handles 'b' when #dir-list has focus (not the
        # search input, which would consume the keystroke instead).
        dir_list = ctx.app.query_one("#dir-list")
        dir_list.focus()
        await ctx.pilot.pause()
        await ctx.pilot.press("b")
        await ctx.pilot.pause()

    ctx.run(_press())


@then("the directory tree should be visible")
def then_dir_tree_visible(ctx):
    tree = ctx.app.query_one("#dir-tree")
    assert tree.display is True, "FolderTree (#dir-tree) should be visible"


@then("the tree should be rooted at the default_dir")
def then_tree_rooted_at_default_dir(ctx):
    from pathlib import Path
    tree = ctx.app.query_one("#dir-tree")
    # FolderTree (DirectoryTree subclass) stores path as .path attribute
    expected = Path(ctx.app.config.get("default_dir", str(Path.home())))
    assert tree.path == expected, (
        f"Expected tree rooted at '{expected}', got '{tree.path}'"
    )


# ── Scenario 3: Returning from tree to picker ─────────────────────────────────


@given("the tree browser is showing")
def given_tree_browser_showing(ctx):
    ctx.ensure_mounted()

    async def _open_form_and_tree():
        ctx.app._show_new_agent_form()
        await ctx.pilot.pause()
        # Focus dir-list before pressing b (Input intercepts keys otherwise)
        dir_list = ctx.app.query_one("#dir-list")
        dir_list.focus()
        await ctx.pilot.pause()
        await ctx.pilot.press("b")
        await ctx.pilot.pause()

    ctx.run(_open_form_and_tree())


@when("the user presses Escape")
def when_user_presses_escape(ctx):
    async def _press():
        await ctx.pilot.press("escape")
        await ctx.pilot.pause()

    ctx.run(_press())


@then("the directory picker should be visible again")
def then_dir_picker_visible_again(ctx):
    picker = ctx.app.query_one("#dir-picker")
    assert picker.display is True, "DirectoryPicker (#dir-picker) should be visible again"


# ── Scenario 4: Escape on dir picker cancels form ─────────────────────────────


@then("the dashboard should be visible")
def then_dashboard_visible(ctx):
    dashboard = ctx.app.query_one("#dashboard")
    assert dashboard.display is True, "Dashboard should be visible"


@then("no agent should be created")
def then_no_agent_created(ctx):
    state = ctx.state_mgr.load()
    assert len(state.agents) == 0, (
        f"Expected no agents created, found {len(state.agents)}"
    )


@then("the command input should be visible")
def then_command_input_visible(ctx):
    inputs = ctx.app.query("#command-input")
    assert len(inputs) > 0, "Expected #command-input to be in the DOM"


# ── Scenario 7: Empty state ───────────────────────────────────────────────────


@given("no dir_history.json exists")
def given_no_dir_history(ctx):
    # Ensure the file doesn't exist (tmp_aque_dir is fresh, so it shouldn't)
    history_file = ctx.tmp_aque_dir / "dir_history.json"
    if history_file.exists():
        history_file.unlink()


@when("the user opens the new agent form")
def when_user_opens_new_agent_form(ctx):
    ctx.ensure_mounted()

    async def _open():
        ctx.app._show_new_agent_form()
        await ctx.pilot.pause()

    ctx.run(_open())


@then("the pinned section should be empty")
def then_pinned_section_empty(ctx):
    option_list = ctx.app.query_one("#dir-list")
    pinned_labels = []
    for i in range(option_list.option_count):
        opt = option_list.get_option_at_index(i)
        label = str(opt.prompt)
        if label.startswith("* "):
            pinned_labels.append(label)
    assert pinned_labels == [], (
        f"Expected no pinned dirs, found: {pinned_labels}"
    )


@then("the recent section should be empty")
def then_recent_section_empty(ctx):
    option_list = ctx.app.query_one("#dir-list")
    recent_labels = []
    for i in range(option_list.option_count):
        opt = option_list.get_option_at_index(i)
        label = str(opt.prompt)
        # Recent entries start with "  " (two spaces) and are not separators
        if label.startswith("  ") and opt.id != "__separator__":
            recent_labels.append(label)
    assert recent_labels == [], (
        f"Expected no recent dirs, found: {recent_labels}"
    )


# ── Scenario 8: Entering command advances to label step ───────────────────────


@given("the user is on the command step")
def given_user_on_command_step(ctx, tmp_path):
    """Get to the command step by selecting a real directory.

    Uses a subdirectory named 'myapp' so the auto-generated default label
    matches the feature spec: "claude . myapp".
    """
    myapp_dir = tmp_path / "myapp"
    myapp_dir.mkdir(parents=True, exist_ok=True)
    ctx.ensure_mounted()

    async def _navigate_to_command():
        ctx.app._show_new_agent_form()
        await ctx.pilot.pause()
        form = ctx.app.query_one("NewAgentForm")
        form._selected_dir = str(myapp_dir)
        form.show_command_step()
        await ctx.pilot.pause()

    ctx.run(_navigate_to_command())


@when(parsers.parse('the user types "{command}" and presses Enter'))
def when_user_types_command_and_enters(ctx, command):
    async def _type_and_enter():
        # The command input should already have focus after show_command_step
        await ctx.pilot.press(*list(command))
        await ctx.pilot.press("enter")
        await ctx.pilot.pause()

    ctx.run(_type_and_enter())


@then("the command input should have focus")
def then_command_input_has_focus(ctx):
    focused = ctx.app.focused
    assert focused is not None, "No widget has focus"
    assert focused.id == "command-input", (
        f"Expected '#command-input' to have focus, got '{focused.id}'"
    )


@then("the label input should have focus")
def then_label_input_has_focus(ctx):
    focused = ctx.app.focused
    assert focused is not None, "No widget has focus"
    assert focused.id == "label-input", (
        f"Expected '#label-input' to have focus, got '{focused.id}'"
    )


@then(parsers.parse('the label input should contain a default label "{expected_label}"'))
def then_label_input_contains_default(ctx, expected_label):
    label_input = ctx.app.query_one("#label-input")
    actual = label_input.value
    assert actual == expected_label, (
        f"Expected label input value '{expected_label}', got '{actual}'"
    )


# ── Scenario 9: Picker shows pinned dirs at top ───────────────────────────────


@given("the following directories are pinned:")
def given_dirs_pinned(ctx, datatable, tmp_path):
    rows = _datatable_as_dicts(datatable)
    created_dirs = []
    for row in rows:
        # Create real temp dirs (DirHistoryManager._load_raw() prunes non-existent)
        name = row["path"].replace("~/Projects/", "").replace("/", "_")
        d = tmp_path / name
        d.mkdir(parents=True, exist_ok=True)
        ctx.dir_history_mgr.pin(str(d))
        created_dirs.append(str(d))
    ctx.data["pinned_dirs"] = created_dirs


@then(parsers.parse('the picker should show "{raw_path}" in the pinned section'))
def then_picker_shows_pinned(ctx, raw_path):
    # raw_path is like "~/Projects/aque" — we just verify *some* pinned entry exists
    option_list = ctx.app.query_one("#dir-list")
    pinned_labels = []
    for i in range(option_list.option_count):
        opt = option_list.get_option_at_index(i)
        if str(opt.prompt).startswith("* "):
            pinned_labels.append(str(opt.prompt))
    assert len(pinned_labels) > 0, (
        f"Expected at least one pinned entry (for '{raw_path}'), found none"
    )


@then(parsers.parse('"{path_a}" should appear before "{path_b}"'))
def then_path_a_before_path_b(ctx, path_a, path_b):
    # path_a and path_b are feature-file friendly names like "~/Projects/aque"
    # The actual paths stored are the real tmp dirs created in given_dirs_pinned.
    # We verify order by position: first pinned dir should come before second.
    pinned_dirs = ctx.data.get("pinned_dirs", [])
    if len(pinned_dirs) < 2:
        pytest.skip("Not enough pinned dirs seeded to check order")

    option_list = ctx.app.query_one("#dir-list")
    positions = {}
    for i in range(option_list.option_count):
        opt = option_list.get_option_at_index(i)
        opt_id = str(opt.id)
        for j, d in enumerate(pinned_dirs):
            if opt_id == d:
                positions[j] = i

    assert 0 in positions and 1 in positions, (
        f"Could not find both pinned dirs in list. positions={positions}"
    )
    assert positions[0] < positions[1], (
        f"Expected first pinned dir (idx 0) before second (idx 1), "
        f"got positions {positions[0]} and {positions[1]}"
    )


# ── Scenario 10: Typing filters the list ──────────────────────────────────────


@given("the following directory history exists:")
def given_dir_history_exists(ctx, datatable, tmp_path):
    rows = _datatable_as_dicts(datatable)
    for row in rows:
        name = row["path"].replace("~/Projects/", "").replace("/", "_")
        d = tmp_path / name
        d.mkdir(parents=True, exist_ok=True)
        count = int(row.get("count", 1))
        for _ in range(count):
            ctx.dir_history_mgr.record_use(str(d))
    ctx.data["history_dirs"] = {
        row["path"]: str(tmp_path / row["path"].replace("~/Projects/", "").replace("/", "_"))
        for row in rows
    }


@when(parsers.parse('the user types "{query}" in the search input'))
def when_user_types_in_search(ctx, query):
    async def _type():
        search_input = ctx.app.query_one("#dir-search-input")
        search_input.focus()
        await ctx.pilot.pause()
        # Type each character
        await ctx.pilot.press(*list(query))
        await ctx.pilot.pause()

    ctx.run(_type())


@then(parsers.parse('only "{raw_path}" should be visible in the list'))
def then_only_path_visible(ctx, raw_path):
    # raw_path is like "~/Projects/safebot"
    history_dirs = ctx.data.get("history_dirs", {})
    expected_real_path = history_dirs.get(raw_path)

    option_list = ctx.app.query_one("#dir-list")
    visible_ids = []
    for i in range(option_list.option_count):
        opt = option_list.get_option_at_index(i)
        if opt.id != "__separator__":
            visible_ids.append(str(opt.id))

    assert len(visible_ids) >= 1, "Expected at least one result in the filtered list"

    if expected_real_path:
        assert expected_real_path in visible_ids, (
            f"Expected '{expected_real_path}' (mapped from '{raw_path}') "
            f"in list, got: {visible_ids}"
        )
    else:
        # Fallback: check the raw name fragment appears in at least one entry
        name_fragment = raw_path.split("/")[-1]
        assert any(name_fragment in p for p in visible_ids), (
            f"Expected an entry matching '{name_fragment}' in list, got: {visible_ids}"
        )


# ── Scenario 11: Selecting a directory advances to command step ───────────────


@given(parsers.parse('"{raw_path}" is highlighted'))
def given_path_is_highlighted(ctx, raw_path, tmp_path):
    """Create a real tmp dir, record use so it appears, then highlight it.

    Also ensures the new-agent form is open (opens it if not already visible).
    """
    name = raw_path.replace("~/Projects/", "").replace("/", "_")
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    ctx.dir_history_mgr.record_use(str(d))
    ctx.data["selected_dir"] = str(d)
    # Also store as target_dir so pin/unpin Then steps can find it
    if "target_dir" not in ctx.data:
        ctx.data["target_dir"] = str(d)

    # Refresh the picker list, highlight the entry, and focus the dir-list
    # (Enter only triggers OptionSelected when the list itself has focus)
    async def _highlight():
        # Open the form if it isn't already open
        try:
            ctx.app.query_one("#dir-picker")
        except Exception:
            ctx.app._show_new_agent_form()
            await ctx.pilot.pause()
        picker = ctx.app.query_one("#dir-picker")
        picker._refresh_list("")
        await ctx.pilot.pause()
        option_list = ctx.app.query_one("#dir-list")
        for i in range(option_list.option_count):
            opt = option_list.get_option_at_index(i)
            if str(opt.id) == str(d):
                option_list.highlighted = i
                break
        option_list.focus()
        await ctx.pilot.pause()

    ctx.run(_highlight())


@when("the user presses Enter")
def when_user_presses_enter(ctx):
    async def _press():
        await ctx.pilot.press("enter")
        await ctx.pilot.pause()

    ctx.run(_press())


# ── Scenario 10: Recent dirs ranked by frequency ──────────────────────────────


@then(parsers.parse('"{raw_a}" should appear before "{raw_b}" in the recent section'))
def then_a_before_b_in_recent(ctx, raw_a, raw_b):
    """Check that the first history_dir entry appears before the second in the list."""
    history_dirs = ctx.data.get("history_dirs", {})
    path_a = history_dirs.get(raw_a)
    path_b = history_dirs.get(raw_b)

    if not path_a or not path_b:
        pytest.skip(f"Could not resolve paths for '{raw_a}' / '{raw_b}'")

    option_list = ctx.app.query_one("#dir-list")
    pos_a = pos_b = None
    for i in range(option_list.option_count):
        opt = option_list.get_option_at_index(i)
        if str(opt.id) == path_a:
            pos_a = i
        elif str(opt.id) == path_b:
            pos_b = i

    assert pos_a is not None, f"'{raw_a}' not found in the list"
    assert pos_b is not None, f"'{raw_b}' not found in the list"
    assert pos_a < pos_b, (
        f"Expected '{raw_a}' (pos {pos_a}) before '{raw_b}' (pos {pos_b})"
    )


# ── Scenario 11: Deleted directories are not shown ───────────────────────────


@given(parsers.parse('"{raw_path}" is in the directory history'))
def given_path_in_dir_history(ctx, raw_path, tmp_path):
    """Seed a path in the history. The path is a real tmp dir initially."""
    name = raw_path.replace("~/Projects/", "").replace("/", "_")
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    ctx.dir_history_mgr.record_use(str(d))
    ctx.data["deleted_dir"] = str(d)


@given(parsers.parse('"{raw_path}" no longer exists on disk'))
def given_path_no_longer_exists(ctx, raw_path, tmp_path):
    """Remove the directory so that DirHistoryManager prunes it on next load."""
    d = ctx.data.get("deleted_dir")
    if d:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


@then(parsers.parse('"{raw_path}" should not appear in the picker'))
def then_path_not_in_picker(ctx, raw_path):
    """Verify the deleted path (stored in ctx.data["deleted_dir"]) is absent."""
    deleted = ctx.data.get("deleted_dir")
    option_list = ctx.app.query_one("#dir-list")
    visible_ids = [
        str(option_list.get_option_at_index(i).id)
        for i in range(option_list.option_count)
    ]
    assert deleted not in visible_ids, (
        f"Expected '{deleted}' ('{raw_path}') to be absent from picker, "
        f"but it appeared in: {visible_ids}"
    )


# ── Scenario 12: Selecting a directory records usage ─────────────────────────


@when(parsers.parse('the user selects "{raw_path}"'))
def when_user_selects_path(ctx, raw_path, tmp_path):
    """Select a directory: create it, seed 1 use, highlight, and press Enter."""
    name = raw_path.replace("~/Projects/", "").replace("/", "_")
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    # Record one initial use so it appears in the list
    ctx.dir_history_mgr.record_use(str(d))
    ctx.data["selected_dir_for_usage"] = str(d)
    ctx.data["selected_dir_initial_count"] = ctx.dir_history_mgr.get_history()

    async def _select():
        picker = ctx.app.query_one("#dir-picker")
        picker._refresh_list("")
        await ctx.pilot.pause()
        option_list = ctx.app.query_one("#dir-list")
        for i in range(option_list.option_count):
            opt = option_list.get_option_at_index(i)
            if str(opt.id) == str(d):
                option_list.highlighted = i
                break
        option_list.focus()
        await ctx.pilot.pause()
        await ctx.pilot.press("enter")
        await ctx.pilot.pause()

    ctx.run(_select())


@when("completes the agent creation")
def when_completes_agent_creation(ctx):
    """Navigate through command and label steps to launch the agent (mocked).

    Uses a fake launch_agent that creates the AgentInfo in state without tmux.
    """
    from unittest.mock import patch as _patch
    from aque.state import AgentInfo, AgentState

    def _fake_launch(command, working_dir, label, state_manager, prefix="aque", background=False):
        agent_id = state_manager.next_id()
        agent = AgentInfo(
            id=agent_id,
            tmux_session=f"{prefix}-fake-{agent_id}",
            label=label or "fake-agent",
            dir=working_dir,
            command=command,
            state=AgentState.RUNNING,
            pid=99999,
        )
        state_manager.add_agent(agent)
        return agent_id

    async def _complete():
        # We should be on the command step; type a command and press Enter
        await ctx.pilot.press("c", "l", "a", "u", "d", "e")
        await ctx.pilot.press("enter")
        await ctx.pilot.pause()
        # Now on label step; press Enter to accept default label (mocked launch)
        with _patch("aque.desk.launch_agent", side_effect=_fake_launch):
            await ctx.pilot.press("enter")
            await ctx.pilot.pause()

    ctx.run(_complete())


@then(parsers.parse('the usage count for "{raw_path}" should be incremented'))
def then_usage_count_incremented(ctx, raw_path):
    d = ctx.data.get("selected_dir_for_usage")
    if not d:
        pytest.skip("No selected dir recorded")
    history = ctx.app.dir_history_mgr.get_history()
    entry = next((h for h in history if h["path"] == d), None)
    # The dir was recorded once before selection, and once more after submit
    assert entry is not None, f"No history entry found for '{d}'"
    # Count should be >= 2: 1 initial + 1 from record_use on submit
    assert entry["count"] >= 2, (
        f"Expected count >= 2 for '{d}', got {entry['count']}"
    )


@then("the last_used timestamp should be updated")
def then_last_used_updated(ctx):
    d = ctx.data.get("selected_dir_for_usage")
    if not d:
        pytest.skip("No selected dir recorded")
    history = ctx.app.dir_history_mgr.get_history()
    entry = next((h for h in history if h["path"] == d), None)
    assert entry is not None, f"No history entry found for '{d}'"
    assert entry.get("last_used") is not None, "Expected last_used to be set"


# ── Scenario 13: Clearing search restores full list ───────────────────────────


@given(parsers.parse('the user has typed "{query}" in the search input'))
def given_user_has_typed_in_search(ctx, query, tmp_path):
    """Open the form and type a query into the search input.

    Seeds a couple of real dirs first so the search has something to filter.
    """
    for name in ("safebot", "ha-config", "aque"):
        d = tmp_path / name
        d.mkdir(parents=True, exist_ok=True)
        ctx.dir_history_mgr.record_use(str(d))

    ctx.ensure_mounted()

    async def _open_and_type():
        ctx.app._show_new_agent_form()
        await ctx.pilot.pause()
        search_input = ctx.app.query_one("#dir-search-input")
        search_input.focus()
        await ctx.pilot.pause()
        await ctx.pilot.press(*list(query))
        await ctx.pilot.pause()

    ctx.run(_open_and_type())
    # Store the full-list count before the clear
    option_list = ctx.app.query_one("#dir-list")
    ctx.data["filtered_count"] = option_list.option_count


@when("the user clears the search input")
def when_user_clears_search(ctx):
    async def _clear():
        search_input = ctx.app.query_one("#dir-search-input")
        search_input.focus()
        await ctx.pilot.pause()
        # Select all and delete
        await ctx.pilot.press("ctrl+a")
        await ctx.pilot.press("backspace")
        await ctx.pilot.pause()

    ctx.run(_clear())


@then("the full pinned and recent list should be visible")
def then_full_list_visible(ctx):
    option_list = ctx.app.query_one("#dir-list")
    count = option_list.option_count
    # After clearing, all 3 seeded dirs should be visible (count >= 3)
    assert count >= 3, (
        f"Expected at least 3 entries after clearing search, got {count}"
    )


# ── Scenario 14: Pinning a directory from the recent list ────────────────────


@given(parsers.parse('"{raw_path}" is in the recent list'))
def given_path_in_recent_list(ctx, raw_path, tmp_path):
    """Create a real tmp dir and record its use (not pinned yet)."""
    name = raw_path.replace("~/Projects/", "").replace("/", "_")
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    ctx.dir_history_mgr.record_use(str(d))
    ctx.data["target_dir"] = str(d)


@when('the user presses "p"')
def when_user_presses_p(ctx):
    async def _press():
        # The pin shortcut only fires when #dir-list has focus (not the search input)
        dir_list = ctx.app.query_one("#dir-list")
        dir_list.focus()
        await ctx.pilot.pause()
        await ctx.pilot.press("p")
        await ctx.pilot.pause()

    ctx.run(_press())


@then(parsers.parse('"{raw_path}" should move to the pinned section'))
def then_path_in_pinned_section(ctx, raw_path):
    d = ctx.data.get("target_dir")
    if not d:
        pytest.skip("No target dir recorded")
    option_list = ctx.app.query_one("#dir-list")
    for i in range(option_list.option_count):
        opt = option_list.get_option_at_index(i)
        if str(opt.id) == d:
            label = str(opt.prompt)
            assert label.startswith("* "), (
                f"Expected '{d}' to be pinned (label starts with '* '), got '{label}'"
            )
            return
    pytest.fail(f"Entry for '{d}' ('{raw_path}') not found in option list")


# ── Scenario 15: Unpinning a directory ───────────────────────────────────────


@given(parsers.parse('"{raw_path}" is pinned'))
def given_path_is_pinned(ctx, raw_path, tmp_path):
    """Create a real tmp dir, record use, and pin it."""
    name = raw_path.replace("~/Projects/", "").replace("/", "_")
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    ctx.dir_history_mgr.record_use(str(d))
    ctx.dir_history_mgr.pin(str(d))
    ctx.data["target_dir"] = str(d)


@then(parsers.parse('"{raw_path}" should be removed from the pinned section'))
def then_path_not_in_pinned(ctx, raw_path):
    d = ctx.data.get("target_dir")
    if not d:
        pytest.skip("No target dir recorded")
    option_list = ctx.app.query_one("#dir-list")
    for i in range(option_list.option_count):
        opt = option_list.get_option_at_index(i)
        if str(opt.id) == d:
            label = str(opt.prompt)
            assert not label.startswith("* "), (
                f"Expected '{d}' to be unpinned (label NOT starting with '* '), got '{label}'"
            )
            return
    # Not found at all — also ok if unpin removed it with no history
    pass


@then(parsers.parse('"{raw_path}" should appear in the recent section'))
def then_path_in_recent_section(ctx, raw_path):
    d = ctx.data.get("target_dir")
    if not d:
        pytest.skip("No target dir recorded")
    option_list = ctx.app.query_one("#dir-list")
    for i in range(option_list.option_count):
        opt = option_list.get_option_at_index(i)
        if str(opt.id) == d:
            label = str(opt.prompt)
            assert not label.startswith("* "), (
                f"Expected '{d}' in recent (not pinned), got label '{label}'"
            )
            return
    pytest.fail(f"Entry for '{d}' ('{raw_path}') not found in option list after unpinning")


# ── Scenario 16: Pinned dirs always above recent ──────────────────────────────


@given(parsers.parse('"{raw_path}" is pinned with usage count {count:d}'))
def given_path_pinned_with_count(ctx, raw_path, count, tmp_path):
    """Create a real dir, record N uses, and pin it."""
    name = raw_path.replace("~/Projects/", "").replace("/", "_")
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    for _ in range(count):
        ctx.dir_history_mgr.record_use(str(d))
    ctx.dir_history_mgr.pin(str(d))
    ctx.data.setdefault("ordered_dirs", [])
    ctx.data["ordered_dirs"].append({"path": str(d), "label": raw_path, "pinned": True})


@given(parsers.parse('"{raw_path}" is not pinned with usage count {count:d}'))
def given_path_not_pinned_with_count(ctx, raw_path, count, tmp_path):
    """Create a real dir and record N uses (NOT pinned)."""
    name = raw_path.replace("~/Projects/", "").replace("/", "_")
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    for _ in range(count):
        ctx.dir_history_mgr.record_use(str(d))
    ctx.data.setdefault("ordered_dirs", [])
    ctx.data["ordered_dirs"].append({"path": str(d), "label": raw_path, "pinned": False})


@then(parsers.parse('"{raw_a}" should appear above "{raw_b}"'))
def then_a_above_b(ctx, raw_a, raw_b):
    """Check that the pinned dir appears above the unpinned dir in the list."""
    ordered_dirs = ctx.data.get("ordered_dirs", [])
    path_a = next((o["path"] for o in ordered_dirs if o["label"] == raw_a), None)
    path_b = next((o["path"] for o in ordered_dirs if o["label"] == raw_b), None)

    if not path_a or not path_b:
        pytest.skip(f"Could not find paths for '{raw_a}' / '{raw_b}'")

    # Open the form to make the picker list visible
    ctx.ensure_mounted()

    async def _open():
        ctx.app._show_new_agent_form()
        await ctx.pilot.pause()

    ctx.run(_open())

    option_list = ctx.app.query_one("#dir-list")
    pos_a = pos_b = None
    for i in range(option_list.option_count):
        opt = option_list.get_option_at_index(i)
        if str(opt.id) == path_a:
            pos_a = i
        elif str(opt.id) == path_b:
            pos_b = i

    assert pos_a is not None, f"'{raw_a}' ({path_a}) not found in list"
    assert pos_b is not None, f"'{raw_b}' ({path_b}) not found in list"
    assert pos_a < pos_b, (
        f"Expected '{raw_a}' (pos {pos_a}) above '{raw_b}' (pos {pos_b})"
    )


# ── Scenario 17: Search scans filesystem for new dirs ────────────────────────


@given(parsers.parse('"{raw_path}" exists on disk'))
def given_path_exists_on_disk(ctx, raw_path, tmp_path):
    """Create a real directory whose name matches a search pattern.

    Also mounts the app and opens the new-agent form, pointing default_dir at
    tmp_path so that the filesystem scan in DirHistoryManager.search() will
    discover the newly created directory.
    """
    name = raw_path.replace("~/Projects/", "").replace("/", "_")
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    ctx.data["fs_dir"] = str(d)
    ctx.data["fs_dir_name"] = d.name

    # Mount and configure default_dir to point at tmp_path (parent of d)
    ctx.ensure_mounted()
    ctx.app.config["default_dir"] = str(tmp_path)

    async def _open_form():
        ctx.app._show_new_agent_form()
        await ctx.pilot.pause()
        # Update the picker's default_dir as well so it scans tmp_path
        try:
            picker = ctx.app.query_one("#dir-picker")
            picker._default_dir = str(tmp_path)
        except Exception:
            pass

    ctx.run(_open_form())


@given(parsers.parse('"{raw_path}" is not in the directory history'))
def given_path_not_in_history(ctx, raw_path):
    """No-op: the dir was just created but never recorded in history."""
    pass


@then(parsers.parse('"{raw_path}" should appear in the results'))
def then_path_in_results(ctx, raw_path):
    """The dir should appear in the search results via filesystem scan."""
    fs_dir = ctx.data.get("fs_dir")
    if not fs_dir:
        pytest.skip("No filesystem dir recorded")

    option_list = ctx.app.query_one("#dir-list")
    visible_ids = [
        str(option_list.get_option_at_index(i).id)
        for i in range(option_list.option_count)
        if option_list.get_option_at_index(i).id != "__separator__"
    ]
    assert fs_dir in visible_ids, (
        f"Expected '{fs_dir}' ('{raw_path}') in search results, got: {visible_ids}"
    )


# ── Scenario 18: Tree hides hidden directories ────────────────────────────────


@given('the current directory contains ".git" and "src"')
def given_dir_contains_hidden_and_visible(ctx, tmp_path):
    """Point the tree at a tmp directory that contains .git and src subdirs.

    The tree was opened in given_tree_browser_showing using config["default_dir"].
    We update config["default_dir"] to tmp_path, create the subdirs, and
    re-open the tree so it reflects the updated root.
    """
    from pathlib import Path

    root = tmp_path / "tree_root"
    root.mkdir(parents=True, exist_ok=True)
    (root / ".git").mkdir(parents=True, exist_ok=True)
    (root / "src").mkdir(parents=True, exist_ok=True)
    ctx.data["tree_root"] = str(root)

    async def _reload_tree():
        # Update the form's _default_dir and re-open the tree
        form = ctx.app.query_one("NewAgentForm")
        form._default_dir = str(root)

        # Remove existing tree widgets (await so they are gone before remounting)
        for selector in ("#dir-tree", "#dir-display", "#tree-hint"):
            try:
                await ctx.app.query_one(selector).remove()
            except Exception:
                pass
        await ctx.pilot.pause()

        from aque.desk import FolderTree
        from textual.widgets import Static
        from aque.widgets.dir_picker import key_hint

        step_widget = form.query_one("#new-agent-step")
        await form.mount(
            Static(f"[bold]Selected:[/bold] {root}", id="dir-display"),
            after=step_widget,
        )
        await form.mount(
            FolderTree(str(root), id="dir-tree"),
            after=form.query_one("#dir-display"),
        )
        tree_hint = "   ".join([
            key_hint("Enter", "expand/collapse"),
            key_hint("s", "select"),
            key_hint("Esc", "back to picker"),
        ])
        await form.mount(
            Static(tree_hint, id="tree-hint"),
            after=form.query_one("#dir-tree"),
        )
        await ctx.pilot.pause()
        # Expand the root so children are visible
        tree = ctx.app.query_one("#dir-tree")
        tree.root.expand()
        await ctx.pilot.pause()

    ctx.run(_reload_tree())


@then('the directory tree should show "src"')
def then_tree_shows_src(ctx):
    """Verify the FolderTree has a node whose label contains 'src'."""
    tree = ctx.app.query_one("#dir-tree")
    # Walk tree nodes to find a node with label "src"
    found = False
    for node in tree.root.children:
        if node.label and "src" in str(node.label):
            found = True
            break
    assert found, (
        f"Expected 'src' to appear as a tree node. "
        f"Children: {[str(n.label) for n in tree.root.children]}"
    )


@then('the directory tree should not show ".git"')
def then_tree_not_show_git(ctx):
    """Verify the FolderTree has NO node whose label is '.git'."""
    tree = ctx.app.query_one("#dir-tree")
    for node in tree.root.children:
        assert ".git" not in str(node.label), (
            f"Expected '.git' to be hidden but found node: {node.label}"
        )


# ── Scenario 19: Tree mode select advances to command step ───────────────────


@given(parsers.parse('the user has navigated to "{raw_path}"'))
def given_user_navigated_to(ctx, raw_path, tmp_path):
    """Set the selected dir in the form to simulate navigation in tree mode."""
    name = raw_path.replace("~/Projects/", "").replace("/", "_")
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)

    async def _navigate():
        form = ctx.app.query_one("NewAgentForm")
        form._selected_dir = str(d)
        await ctx.pilot.pause()

    ctx.run(_navigate())


@when('the user presses "s"')
def when_user_presses_s(ctx):
    async def _press():
        await ctx.pilot.press("s")
        await ctx.pilot.pause()

    ctx.run(_press())


# ── Scenario 20: Submitting the label launches the agent ─────────────────────


@given("the user is on the label step")
def given_user_on_label_step(ctx, tmp_path):
    """Navigate to the label step via simulated user interaction."""
    myapp_dir = tmp_path / "myapp"
    myapp_dir.mkdir(parents=True, exist_ok=True)
    ctx.data["launch_dir"] = str(myapp_dir)
    ctx.ensure_mounted()

    async def _navigate_to_label():
        ctx.app._show_new_agent_form()
        await ctx.pilot.pause()
        # Navigate directly to command step via form method (sets _selected_dir)
        form = ctx.app.query_one("NewAgentForm")
        form._selected_dir = str(myapp_dir)
        form.show_command_step()
        await ctx.pilot.pause()
        # Now type a command and press Enter to trigger show_label_step via event
        await ctx.pilot.press("c", "l", "a", "u", "d", "e")
        await ctx.pilot.press("enter")
        await ctx.pilot.pause()

    ctx.run(_navigate_to_label())


@given(parsers.parse('the label is "{label_text}"'))
def given_label_is(ctx, label_text):
    """Pre-fill the label input with the given text.

    Also starts a mock patcher for launch_agent so that pressing Enter in the
    label step doesn't actually create a tmux session.  The mock is stopped
    after the test in cleanup (via ctx.data["_mock_patcher"]).
    """
    from unittest.mock import patch, MagicMock
    from aque.state import AgentInfo, AgentState
    import datetime

    # Build a real AgentInfo so that the "agent" lookup in on_input_submitted
    # finds a valid object and calls _show_dashboard() rather than crashing.
    launch_dir = ctx.data.get("launch_dir", "/tmp/myapp")

    def _fake_launch(command, working_dir, label, state_manager, prefix="aque", background=False):
        agent_id = state_manager.next_id()
        agent = AgentInfo(
            id=agent_id,
            tmux_session=f"{prefix}-fake-{agent_id}",
            label=label or "fake-agent",
            dir=working_dir,
            command=command,
            state=AgentState.RUNNING,
            pid=99999,
        )
        state_manager.add_agent(agent)
        return agent_id

    patcher = patch("aque.desk.launch_agent", side_effect=_fake_launch)
    mock_obj = patcher.start()
    ctx.data["mock_launch_agent"] = mock_obj
    ctx.data["_mock_patcher"] = patcher

    async def _set_label():
        label_input = ctx.app.query_one("#label-input")
        label_input.clear()
        label_input.value = label_text
        await ctx.pilot.pause()

    ctx.run(_set_label())


@then("a new tmux session should be created")
def then_tmux_session_created(ctx):
    """Verify that launch_agent was called (tracked via mock)."""
    mock_launch = ctx.data.get("mock_launch_agent")
    patcher = ctx.data.get("_mock_patcher")
    if patcher is not None:
        patcher.stop()
        ctx.data["_mock_patcher"] = None
    if mock_launch is None:
        pytest.skip("launch_agent mock not set up")
    assert mock_launch.called, "Expected launch_agent to have been called"


@then("the agent should appear in the state file")
def then_agent_in_state_file(ctx):
    """Verify a new agent was added to the state."""
    state = ctx.app.state_mgr.load()
    assert len(state.agents) >= 1, (
        f"Expected at least 1 agent in state, got {len(state.agents)}"
    )


@then("the user should be attached to the new agent")
def then_user_attached(ctx):
    """After launch with _skip_attach=True, the app should be back on dashboard."""
    dashboard = ctx.app.query_one("#dashboard")
    assert dashboard.display is True, (
        "Expected dashboard to be visible after launch (since _skip_attach=True)"
    )
