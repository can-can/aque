import pytest

from aque.orphans import OrphanedAgent
from aque.state import AgentInfo, AgentState
from aque.widgets.orphan_modal import OrphanModal


def _orphan(id: int, agent_type: str | None = None, session_id: str | None = None,
            resumable: bool = False) -> OrphanedAgent:
    return OrphanedAgent(
        agent=AgentInfo(
            id=id, tmux_session=f"aque-{id}", label=f"agent-{id}",
            dir="/tmp", command=["claude"], state=AgentState.RUNNING, pid=1,
            agent_type=agent_type, session_id=session_id,
        ),
        resumable=resumable,
    )


@pytest.mark.asyncio
async def test_orphan_modal_lists_orphans_and_dismisses_when_empty():
    from textual.app import App

    orphans = [_orphan(1, resumable=True), _orphan(2, resumable=False)]
    actions: list[tuple[str, int]] = []

    class Host(App):
        def on_mount(self):
            self.push_screen(OrphanModal(orphans, on_action=lambda a, oid: actions.append((a, oid))))

    async with Host().run_test() as pilot:
        await pilot.pause()
        modal = pilot.app.screen
        assert isinstance(modal, OrphanModal)
        assert len(modal.remaining_orphans()) == 2

        # Simulate Forget on orphan 1
        modal.handle_action("forget", 1)
        await pilot.pause()
        assert ("forget", 1) in actions
        assert len(modal.remaining_orphans()) == 1

        # Simulate Mark exited on orphan 2 — list empties, modal pops itself
        modal.handle_action("mark_exited", 2)
        await pilot.pause()
        assert ("mark_exited", 2) in actions
        # After empty, modal dismissed → screen is back to default
        assert not isinstance(pilot.app.screen, OrphanModal)


@pytest.mark.asyncio
async def test_orphan_modal_resume_disabled_when_not_resumable():
    from textual.app import App

    class Host(App):
        def on_mount(self):
            self.push_screen(OrphanModal([_orphan(1, resumable=False)], on_action=lambda *a: None))

    async with Host().run_test() as pilot:
        await pilot.pause()
        modal = pilot.app.screen
        assert modal.is_resume_disabled(1) is True


@pytest.mark.asyncio
async def test_orphan_modal_esc_dismisses_without_action():
    from textual.app import App

    actions: list = []

    class Host(App):
        def on_mount(self):
            self.push_screen(OrphanModal([_orphan(1)], on_action=lambda *a: actions.append(a)))

    async with Host().run_test() as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert actions == []
        assert not isinstance(pilot.app.screen, OrphanModal)


@pytest.mark.asyncio
async def test_orphan_modal_keeps_orphan_when_action_returns_error():
    """If on_action returns a non-None string (error), the orphan stays
    in the modal with an inline error message and the modal does not dismiss."""
    from textual.app import App

    class Host(App):
        def on_mount(self):
            self.push_screen(OrphanModal(
                [_orphan(1)],
                on_action=lambda a, oid: "Working directory missing",
            ))

    async with Host().run_test() as pilot:
        await pilot.pause()
        modal = pilot.app.screen
        assert isinstance(modal, OrphanModal)
        modal.handle_action("relaunch", 1)
        await pilot.pause()
        # Orphan still listed because action failed
        assert len(modal.remaining_orphans()) == 1
        # Modal stays open
        assert isinstance(pilot.app.screen, OrphanModal)
