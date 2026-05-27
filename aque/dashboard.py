"""Pure (no Textual) controller for the desk dashboard's display state.

Owns the "what should be on screen right now" question:

* filter / search
* per-session snooze tracking and triage-candidate selection
* sort order, fingerprint dedup, and row state-change cue accounting

Responders are never their own row — they surface as a badge on the partner's
row and are reachable via the partner-side ``attach_responder`` action (Ctrl+Enter).

The controller never touches widgets — it accepts ``AppState`` snapshots and
returns plain Python values so it can be unit-tested without spinning a
Textual app.
"""

from __future__ import annotations

from pathlib import Path

from aque.state import AgentInfo, AgentState, AppState


STATE_PRIORITY = {
    AgentState.WAITING: 0,
    AgentState.EXITED: 1,
    AgentState.RUNNING: 2,
    AgentState.ON_HOLD: 3,
    AgentState.DONE: 4,
}

# How long the row state-change cue (the leading ``▴``) stays visible after
# we detect a transition. Three seconds is roughly one-and-a-half periodic
# refreshes, so the marker is reliably caught by a glancing user.
CHANGE_CUE_SECS = 3.0


def _dir_sort_key(dir_path: str) -> tuple[str, str]:
    """Folder key for the dashboard list: the directory's last two path
    components, e.g. ``/Users/cancan/Projects/aque`` → ``("Projects", "aque")``.
    Shorter paths are left-padded with ``""`` so every key is a 2-tuple."""
    last_two = Path(dir_path).parts[-2:]
    return ("",) * (2 - len(last_two)) + last_two


def sorted_agents(agents: list[AgentInfo]) -> list[AgentInfo]:
    """Order the dashboard list by folder, then by name.

    Agents in the same project (same last-two-path-components folder) sit
    together; ties within a folder break on the agent's label. State no longer
    influences ordering — the list is a stable, navigable index rather than a
    priority queue (urgency surfaces via the triage banner instead)."""
    return sorted(agents, key=lambda a: (_dir_sort_key(a.dir), a.label))


class DashboardController:
    """In-memory display state for the dashboard.

    Lifecycle: created once per ``DeskApp``. Filter / search / snooze state is
    session-only and is not persisted to ``state.json``.
    """

    def __init__(self) -> None:
        # Filter is one of the AgentStates (or None); search is a substring
        # matched against name, dir, type, and state.
        self.filter: AgentState | None = None
        self.search: str = ""
        # Agents the user has explicitly snoozed in this session — they won't
        # re-trigger the triage pill until their state changes again.
        self.snoozed: set[int] = set()
        # Remembered last_change_at per snoozed agent — when this changes,
        # the agent has re-entered waiting and should re-trigger the pill.
        self._snoozed_last_change: dict[int, str] = {}
        # Row state-change cue: ``_prev_row_state`` remembers each agent's
        # last-rendered state; ``_change_at`` records when we noticed a
        # transition. The renderer queries ``should_show_change_cue`` to
        # decide whether to prefix the row with ``▴``.
        self._prev_row_state: dict[int, AgentState] = {}
        self._change_at: dict[int, float] = {}
        # Last computed (id, state) fingerprint of the displayed list — used
        # by the refresh path to skip rebuilds when nothing changed.
        self._last_fingerprint: list[tuple[int, str]] | None = None

    # ── Filter / search ─────────────────────────────────────────────

    def toggle_filter(self, state: AgentState | None) -> None:
        """Click ``state`` once to filter to it, again to clear."""
        self.filter = None if self.filter == state else state
        self.invalidate_fingerprint()

    def set_search(self, value: str) -> None:
        self.search = value
        self.invalidate_fingerprint()

    def clear_filters(self) -> bool:
        """Drop filter + search. Returns ``True`` if anything was cleared."""
        if self.filter is None and not self.search:
            return False
        self.filter = None
        self.search = ""
        self.invalidate_fingerprint()
        return True

    # ── Visibility pipeline ─────────────────────────────────────────

    def visible_agents(self, agents: list[AgentInfo]) -> list[AgentInfo]:
        """Apply filter / search to ``agents``.

        Responders never get their own row — they surface as a badge on the
        partner row (the renderer looks them up via ``AppState.get_responder_for``).
        """
        base = [a for a in agents if not a.is_responder]

        if self.filter is not None:
            base = [a for a in base if a.state == self.filter]

        q = self.search.strip().lower()
        if q:
            def matches(a: AgentInfo) -> bool:
                return (
                    q in a.label.lower()
                    or q in a.dir.lower()
                    or q in a.state.value.lower()
                    or (a.agent_type or "").lower().find(q) != -1
                )
            base = [a for a in base if matches(a)]

        return base

    def compute_visible(self, state: AppState) -> list[AgentInfo]:
        """Active (non-DONE) agents → sorted → visible. The dashboard's main
        list query — used by the refresh path and any test that wants the
        rendered order without poking at filter internals."""
        active = [a for a in state.agents if a.state != AgentState.DONE]
        return self.visible_agents(sorted_agents(active))

    # ── Fingerprint dedup ───────────────────────────────────────────

    def fingerprint(
        self,
        agents: list[AgentInfo],
        responder_states: dict[int, str] | None = None,
    ) -> list[tuple[int, str, str]]:
        """Per-row identity tuple used to detect when the rendered list must
        rebuild. Includes the paired responder's state (when provided) so a
        responder transition refreshes the partner's badge even though the
        partner's own state didn't change.
        """
        rs = responder_states or {}
        return [(a.id, a.state.value, rs.get(a.id, "")) for a in agents]

    def fingerprint_changed(
        self,
        agents: list[AgentInfo],
        responder_states: dict[int, str] | None = None,
    ) -> bool:
        """Compare ``agents`` (and optional paired responder states) against
        the cached fingerprint and update it. Returns ``True`` when anything
        changed; callers skip the rebuild path when ``False``."""
        new = self.fingerprint(agents, responder_states)
        changed = new != self._last_fingerprint
        self._last_fingerprint = new
        return changed

    def invalidate_fingerprint(self) -> None:
        """Force the next ``fingerprint_changed`` call to return True."""
        self._last_fingerprint = None

    # ── Change-cue tracking ─────────────────────────────────────────

    def record_state_transitions(
        self, agents: list[AgentInfo], now: float
    ) -> None:
        """Record per-agent state transitions at ``now``.

        Agents whose state changed since the last call get a fresh
        ``_change_at`` stamp; agents that dropped out of the list are forgotten.
        """
        for a in agents:
            prev = self._prev_row_state.get(a.id)
            if prev is not None and prev != a.state:
                self._change_at[a.id] = now
            self._prev_row_state[a.id] = a.state
        gone = set(self._prev_row_state) - {a.id for a in agents}
        for aid in gone:
            self._prev_row_state.pop(aid, None)
            self._change_at.pop(aid, None)

    def should_show_change_cue(self, agent_id: int, now: float) -> bool:
        return now - self._change_at.get(agent_id, 0.0) < CHANGE_CUE_SECS

    # ── Snooze / triage ─────────────────────────────────────────────

    def snooze(self, agent: AgentInfo) -> None:
        """Suppress triage for ``agent`` until its state changes again."""
        self.snoozed.add(agent.id)
        self._snoozed_last_change[agent.id] = agent.last_change_at

    def gc_snoozes(self, state: AppState) -> None:
        """Drop snooze entries for agents that have moved on or vanished."""
        for aid in list(self.snoozed):
            agent = state.get_agent(aid)
            if agent is None:
                self.snoozed.discard(aid)
                self._snoozed_last_change.pop(aid, None)
                continue
            if self._snoozed_last_change.get(aid) != agent.last_change_at:
                self.snoozed.discard(aid)
                self._snoozed_last_change.pop(aid, None)

    def pick_triage_candidate(
        self, state: AppState
    ) -> tuple[AgentInfo, int] | None:
        """Top-priority WAITING non-responder not currently snoozed.

        Returns ``(top, queue_len)`` — the agent to surface in the triage
        modal plus the count of others behind it, or ``None`` if nothing is
        waiting. GC's stale snoozes as a side effect.
        """
        self.gc_snoozes(state)
        candidates = [
            a for a in state.agents
            if a.state == AgentState.WAITING
            and not a.is_responder
            and a.id not in self.snoozed
        ]
        if not candidates:
            return None
        candidates.sort(
            key=lambda a: (STATE_PRIORITY.get(a.state, 99), a.last_change_at)
        )
        return candidates[0], len(candidates)

    def pick_auto_attach_target(
        self, agents: list[AgentInfo]
    ) -> AgentInfo | None:
        """Top-priority WAITING agent that is NOT a responder.

        Used by the auto-attach modal/countdown to choose which waiting agent
        to surface to the user. Ignores snooze state — the modal is a user-
        initiated transition, not a notification.
        """
        candidates = [
            a for a in agents
            if a.state == AgentState.WAITING and not a.is_responder
        ]
        if not candidates:
            return None
        candidates.sort(
            key=lambda a: (STATE_PRIORITY.get(a.state, 99), a.last_change_at)
        )
        return candidates[0]
