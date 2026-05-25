"""Pure unit tests for ``DashboardController`` — no Textual app required."""

from aque.dashboard import (
    CHANGE_CUE_SECS,
    DashboardController,
    STATE_PRIORITY,
    sorted_agents,
)
from aque.state import AgentInfo, AgentState, AppState


def _agent(
    id: int,
    *,
    label: str = "test",
    dir: str = "/p/x",
    state: AgentState = AgentState.RUNNING,
    is_responder: bool = False,
    partner_id: int | None = None,
    agent_type: str | None = None,
    last_change_at: str = "2026-01-01T00:00:00Z",
) -> AgentInfo:
    return AgentInfo(
        id=id,
        tmux_session=f"aque-{id}",
        label=label,
        dir=dir,
        command=["claude"],
        state=state,
        pid=100 + id,
        agent_type=agent_type,
        is_responder=is_responder,
        partner_id=partner_id,
        last_change_at=last_change_at,
    )


class TestSortedAgents:
    def test_groups_by_folder_then_label(self):
        agents = [
            _agent(1, label="b", dir="/p/api"),
            _agent(2, label="a", dir="/p/web"),
            _agent(3, label="a", dir="/p/api"),
        ]
        ordered = [a.id for a in sorted_agents(agents)]
        # api folder before web; within api, label "a" before "b"
        assert ordered == [3, 1, 2]


class TestStatePriority:
    def test_waiting_outranks_running(self):
        assert STATE_PRIORITY[AgentState.WAITING] < STATE_PRIORITY[AgentState.RUNNING]

    def test_done_is_lowest(self):
        assert STATE_PRIORITY[AgentState.DONE] == max(STATE_PRIORITY.values())


class TestVisibleAgents:
    def test_hides_responders_by_default(self):
        c = DashboardController()
        partner = _agent(1)
        resp = _agent(2, is_responder=True, partner_id=1)
        assert [a.id for a in c.visible_agents([partner, resp])] == [1]

    def test_pairs_responders_after_partner_when_shown(self):
        c = DashboardController()
        c.show_responders = True
        partner = _agent(1)
        other = _agent(3)
        resp = _agent(2, is_responder=True, partner_id=1)
        assert [a.id for a in c.visible_agents([partner, other, resp])] == [1, 2, 3]

    def test_filter_restricts_to_one_state(self):
        c = DashboardController()
        c.filter = AgentState.WAITING
        a = _agent(1, state=AgentState.WAITING)
        b = _agent(2, state=AgentState.RUNNING)
        assert [x.id for x in c.visible_agents([a, b])] == [1]

    def test_search_matches_label_dir_state_type(self):
        c = DashboardController()
        c.search = "API"  # case-insensitive
        match_label = _agent(1, label="auth api fix")
        match_dir = _agent(2, dir="/projects/api")
        match_type = _agent(3, agent_type="API_TYPE")
        miss = _agent(4, label="other")
        ids = [a.id for a in c.visible_agents([match_label, match_dir, match_type, miss])]
        assert set(ids) == {1, 2, 3}


class TestFilterToggle:
    def test_toggle_same_state_clears(self):
        c = DashboardController()
        c.toggle_filter(AgentState.WAITING)
        assert c.filter == AgentState.WAITING
        c.toggle_filter(AgentState.WAITING)
        assert c.filter is None

    def test_toggle_different_state_replaces(self):
        c = DashboardController()
        c.toggle_filter(AgentState.WAITING)
        c.toggle_filter(AgentState.RUNNING)
        assert c.filter == AgentState.RUNNING

    def test_clear_filters_reports_whether_anything_changed(self):
        c = DashboardController()
        assert c.clear_filters() is False
        c.filter = AgentState.WAITING
        assert c.clear_filters() is True
        assert c.filter is None
        assert c.search == ""


class TestFingerprint:
    def test_changed_on_first_call(self):
        c = DashboardController()
        assert c.fingerprint_changed([_agent(1)]) is True

    def test_unchanged_on_repeat(self):
        c = DashboardController()
        agents = [_agent(1)]
        c.fingerprint_changed(agents)
        assert c.fingerprint_changed(agents) is False

    def test_changed_when_state_flips(self):
        c = DashboardController()
        c.fingerprint_changed([_agent(1, state=AgentState.RUNNING)])
        assert c.fingerprint_changed([_agent(1, state=AgentState.WAITING)]) is True

    def test_invalidate_forces_next_to_be_true(self):
        c = DashboardController()
        agents = [_agent(1)]
        c.fingerprint_changed(agents)
        c.invalidate_fingerprint()
        assert c.fingerprint_changed(agents) is True


class TestChangeCue:
    def test_no_cue_for_unknown_agent(self):
        c = DashboardController()
        assert c.should_show_change_cue(1, now=10.0) is False

    def test_cue_after_transition_until_window_elapses(self):
        c = DashboardController()
        c.record_state_transitions([_agent(1, state=AgentState.RUNNING)], now=0.0)
        c.record_state_transitions([_agent(1, state=AgentState.WAITING)], now=1.0)
        assert c.should_show_change_cue(1, now=1.5) is True
        assert c.should_show_change_cue(1, now=1.0 + CHANGE_CUE_SECS + 0.1) is False

    def test_forgets_agents_that_left_the_list(self):
        c = DashboardController()
        c.record_state_transitions([_agent(1)], now=0.0)
        c.record_state_transitions([], now=1.0)
        assert 1 not in c._prev_row_state


class TestSnoozeAndTriage:
    def test_pick_triage_returns_top_waiting_non_responder(self):
        state = AppState(agents=[
            _agent(1, state=AgentState.RUNNING),
            _agent(2, state=AgentState.WAITING, last_change_at="2026-01-01T00:00:01Z"),
            _agent(3, state=AgentState.WAITING, last_change_at="2026-01-01T00:00:00Z"),
            _agent(4, state=AgentState.WAITING, is_responder=True, partner_id=1),
        ])
        c = DashboardController()
        result = c.pick_triage_candidate(state)
        assert result is not None
        top, queue_len = result
        assert top.id == 3  # earlier last_change_at wins the tie
        assert queue_len == 2  # responder excluded

    def test_pick_triage_returns_none_when_nothing_waiting(self):
        state = AppState(agents=[_agent(1, state=AgentState.RUNNING)])
        assert DashboardController().pick_triage_candidate(state) is None

    def test_snoozed_agent_is_skipped_until_state_changes(self):
        waiting = _agent(1, state=AgentState.WAITING, last_change_at="t1")
        state = AppState(agents=[waiting])
        c = DashboardController()
        c.snooze(waiting)
        assert c.pick_triage_candidate(state) is None
        # Same last_change_at → still snoozed.
        assert c.pick_triage_candidate(state) is None
        # Agent re-enters waiting with a fresh timestamp — snooze decays.
        bumped = _agent(1, state=AgentState.WAITING, last_change_at="t2")
        result = c.pick_triage_candidate(AppState(agents=[bumped]))
        assert result is not None and result[0].id == 1

    def test_gc_drops_snoozes_for_vanished_agents(self):
        a = _agent(1, state=AgentState.WAITING)
        c = DashboardController()
        c.snooze(a)
        c.gc_snoozes(AppState(agents=[]))
        assert c.snoozed == set()


class TestPickAutoAttach:
    def test_returns_top_waiting_non_responder(self):
        agents = [
            _agent(1, state=AgentState.RUNNING),
            _agent(2, state=AgentState.WAITING, last_change_at="t2"),
            _agent(3, state=AgentState.WAITING, last_change_at="t1"),
            _agent(4, state=AgentState.WAITING, is_responder=True, partner_id=1),
        ]
        picked = DashboardController().pick_auto_attach_target(agents)
        assert picked is not None and picked.id == 3

    def test_returns_none_when_nothing_waiting(self):
        agents = [_agent(1, state=AgentState.RUNNING)]
        assert DashboardController().pick_auto_attach_target(agents) is None

    def test_ignores_snooze(self):
        # Auto-attach is a user-initiated action, so it must NOT honor
        # the snooze list (unlike pick_triage_candidate).
        a = _agent(1, state=AgentState.WAITING)
        c = DashboardController()
        c.snooze(a)
        assert c.pick_auto_attach_target([a]) is a
