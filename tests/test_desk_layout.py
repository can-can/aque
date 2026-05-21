import pytest

from aque.desk import DeskApp


def test_effective_layout_auto_uses_width_breakpoint(tmp_aque_dir):
    app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
    app._layout_mode = "auto"
    assert app._effective_layout(79) == "stacked"
    assert app._effective_layout(80) == "wide"
    assert app._effective_layout(120) == "wide"


def test_effective_layout_forced_ignores_width(tmp_aque_dir):
    app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
    app._layout_mode = "wide"
    assert app._effective_layout(40) == "wide"
    app._layout_mode = "stacked"
    assert app._effective_layout(200) == "stacked"


def test_layout_mode_defaults_to_auto(tmp_aque_dir):
    app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
    assert app._layout_mode == "auto"


@pytest.mark.asyncio
async def test_auto_stacks_when_narrow(tmp_aque_dir):
    app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
    async with app.run_test() as pilot:
        app._apply_layout(width=70)
        await pilot.pause()
        assert app.query_one("#dashboard").has_class("stacked")
        # Terminal is shown at the bottom in stacked, not hidden.
        assert app.query_one("#preview-panel").display is True


@pytest.mark.asyncio
async def test_auto_two_column_when_wide(tmp_aque_dir):
    app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
    async with app.run_test() as pilot:
        app._apply_layout(width=120)
        await pilot.pause()
        assert not app.query_one("#dashboard").has_class("stacked")
        assert app.query_one("#preview-panel").display is True


@pytest.mark.asyncio
async def test_apply_layout_sets_narrow_flag_from_width(tmp_aque_dir):
    app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
    async with app.run_test() as pilot:
        app._apply_layout(width=70)
        assert app._narrow is True
        app._apply_layout(width=120)
        assert app._narrow is False


@pytest.mark.asyncio
async def test_narrow_previews_terminal_instead_of_skipping(tmp_aque_dir, monkeypatch):
    # In stacked (narrow) the terminal is visible at the bottom, so the
    # highlighted-agent preview MUST attach — regression guard against the
    # old "if self._narrow: return" that left the bottom panel empty.
    from aque.terminal.widget import TerminalView
    from aque.state import StateManager, AgentInfo, AgentState

    calls = []
    # attach() also takes a size_sync pin callback (embed-window pinning); accept
    # and ignore any extra kwargs so the mock matches the real signature.
    monkeypatch.setattr(TerminalView, "attach",
                        lambda self, argv, **kwargs: calls.append(argv))

    mgr = StateManager(tmp_aque_dir)
    mgr.add_agent(AgentInfo(
        id=1, tmux_session="s-1", label="alpha", dir="/tmp",
        command=["claude"], state=AgentState.RUNNING, pid=100,
    ))
    app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=False)
    async with app.run_test(size=(45, 24)) as pilot:
        await pilot.pause()
        app._apply_layout(width=45)          # narrow -> stacked
        ol = app.query_one("#agent-option-list")
        ol.highlighted = 0
        calls.clear()                        # ignore any mount-time attach
        app._attach_highlighted_terminal()
        await pilot.pause()
        assert calls, "terminal should attach (preview) in stacked/narrow layout"


@pytest.mark.asyncio
async def test_cycle_layout_advances_mode(tmp_aque_dir):
    app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
    async with app.run_test() as pilot:
        assert app._layout_mode == "auto"
        app.action_cycle_layout()
        assert app._layout_mode == "wide"
        app.action_cycle_layout()
        assert app._layout_mode == "stacked"
        app.action_cycle_layout()
        assert app._layout_mode == "auto"


@pytest.mark.asyncio
async def test_cycle_forces_stacked_on_wide_screen(tmp_aque_dir):
    app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
    async with app.run_test() as pilot:
        app._apply_layout(width=120)            # wide by width
        app.action_cycle_layout()               # auto -> wide
        app.action_cycle_layout()               # wide -> stacked
        app._apply_layout(width=120)            # re-apply at wide width
        await pilot.pause()
        assert app.query_one("#dashboard").has_class("stacked")


@pytest.mark.asyncio
async def test_forced_mode_survives_resize(tmp_aque_dir):
    app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
    async with app.run_test() as pilot:
        app._layout_mode = "wide"
        app._apply_layout(width=50)             # narrow width, but forced wide
        await pilot.pause()
        assert not app.query_one("#dashboard").has_class("stacked")


@pytest.mark.asyncio
async def test_status_indicator_only_when_forced(tmp_aque_dir):
    app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
    async with app.run_test() as pilot:
        app._layout_mode = "auto"
        app._refresh_status_bar()
        await pilot.pause()
        assert "Layout" not in str(app.query_one("#status-bar").render())
        app._layout_mode = "stacked"
        app._refresh_status_bar()
        await pilot.pause()
        assert "Layout: Stacked" in str(app.query_one("#status-bar").render())


def test_palette_includes_cycle_layout():
    from aque.widgets.command_palette import CommandPalette

    palette = CommandPalette([])
    labels = [it.label for it in palette._all_items()]
    assert any("Cycle layout" in label for label in labels)


@pytest.mark.asyncio
async def test_palette_cycle_layout_dispatch(tmp_aque_dir):
    from aque.widgets.command_palette import CommandItem

    app = DeskApp(aque_dir=tmp_aque_dir, _skip_attach=True)
    async with app.run_test() as pilot:
        before = app._layout_mode
        app._on_command_picked(
            CommandItem("Cycle layout (auto/wide/stacked)", "action", "cycle_layout")
        )
        await pilot.pause()
        assert app._layout_mode != before
