"""Orchestrates the agent-launch flow.

The launch sequence — type-dispatch for session capture, picker integration,
hook install, ``launch_agent`` call, responder pairing, dir-history recording —
lives here so ``DeskApp`` doesn't have to know any of it.

The coordinator is intentionally Textual-free: the picker is pushed via the
injected ``push_modal`` callable and the post-launch attach/restore decision
is delegated to caller-supplied ``on_launched`` / ``on_cancelled`` callbacks.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from aque import responder
from aque.dir_history import DirHistoryManager
from aque.plugins import get_plugin, has_session_capture
from aque.run import launch_agent, relaunch_agent
from aque.state import AgentInfo, StateManager
from aque.widgets.resume_picker import PickerResult, ResumePickerScreen


PushModal = Callable[[object, Callable[[object], None]], None]
EnsureMonitor = Callable[[], None]
OnLaunched = Callable[[AgentInfo], None]
OnCancelled = Callable[[], None]


class LaunchCoordinator:
    """Owns the launch + resume flow for new and orphaned agents."""

    def __init__(
        self,
        state_mgr: StateManager,
        config: dict,
        aque_dir: Path,
        dir_history_mgr: DirHistoryManager,
        push_modal: PushModal,
        ensure_monitor: EnsureMonitor,
    ) -> None:
        self.state_mgr = state_mgr
        self.config = config
        self.aque_dir = aque_dir
        self.dir_history_mgr = dir_history_mgr
        self.push_modal = push_modal
        self.ensure_monitor = ensure_monitor

    # ── New-agent launch ────────────────────────────────────────────

    def launch(
        self,
        command: list[str],
        working_dir: str,
        label: str | None,
        agent_type: str | None,
        on_launched: OnLaunched,
        on_cancelled: OnCancelled | None = None,
    ) -> None:
        """Launch an agent. ``on_launched(agent)`` fires once the agent record
        exists in state.json and the responder is paired. ``on_cancelled()``
        fires only if a resume-picker was shown and the user dismissed it.

        Dispatch: when the plugin for ``agent_type`` exposes session capture,
        check for prior sessions; if any exist push the resume picker (its
        callback drives the rest), otherwise preassign a fresh session_id and
        launch synchronously. Plugins without capture launch straight through.
        """
        plugin = get_plugin(agent_type) if agent_type else None
        if has_session_capture(plugin):
            summaries = plugin.summarize(working_dir)
            if summaries:
                def on_pick(result: PickerResult | None) -> None:
                    if result is None:
                        if on_cancelled is not None:
                            on_cancelled()
                        return
                    if result.action == "fresh":
                        cmd, sid = plugin.preassign(command)
                    else:
                        # Resume — finisher will rewrite the command with the
                        # picked session_id.
                        cmd, sid = command, result.session_id
                    self._finish(
                        cmd, working_dir, label, agent_type, sid, on_launched
                    )
                self.push_modal(
                    ResumePickerScreen(summaries, working_dir, agent_type),
                    on_pick,
                )
                return
            # No prior sessions — still pre-assign so we skip capture.
            cmd, sid = plugin.preassign(command)
            self._finish(cmd, working_dir, label, agent_type, sid, on_launched)
            return
        self._finish(command, working_dir, label, agent_type, None, on_launched)

    def _finish(
        self,
        command: list[str],
        working_dir: str,
        label: str | None,
        agent_type: str | None,
        session_id: str | None,
        on_launched: OnLaunched,
    ) -> None:
        """Deterministic tail of ``launch``: command rewrite, hook install,
        ``launch_agent`` call, responder pairing, dir-history record,
        monitor ensure, then hand the new agent to ``on_launched``."""
        plugin = get_plugin(agent_type) if agent_type else None
        # ``resume_command`` is idempotent — calling it when the command was
        # already preassigned (carries ``--session-id``) is a no-op.
        if session_id is not None and has_session_capture(plugin):
            command = plugin.resume_command(command, session_id)

        # Hook-bundle plugins install their settings.json hooks on first
        # launch; capture-only plugins (the built-in claude) skip this branch.
        if plugin is not None and callable(getattr(plugin, "is_installed", None)):
            if not plugin.is_installed():
                plugin.install_hook()

        agent_id = launch_agent(
            command=command,
            working_dir=working_dir,
            label=label or None,
            state_manager=self.state_mgr,
            prefix=self.config["session_prefix"],
            background=True,
            agent_type=agent_type,
            session_id=session_id,
        )

        # ``launch_agent`` registers the agent atomically; trust the contract
        # and reuse this snapshot for the responder + on_launched delivery
        # instead of re-reading state.json twice.
        agent = self.state_mgr.load().get_agent(agent_id)

        if agent is not None and self.config.get("responder_enabled", True):
            responder.create_for(
                agent, self.config, self.state_mgr, aque_dir=self.aque_dir
            )

        self.dir_history_mgr.record_use(working_dir)
        self.ensure_monitor()

        if agent is not None:
            on_launched(agent)

    # ── Orphan resume ───────────────────────────────────────────────

    def can_resume(self, agent: AgentInfo) -> bool:
        """True when the agent's type has session capture and a captured
        ``session_id`` is available — the gate ``_handle_orphan_action`` checks
        before offering the Resume path."""
        plugin = get_plugin(agent.agent_type) if agent.agent_type else None
        return bool(agent.session_id) and has_session_capture(plugin)

    def resume(self, agent: AgentInfo) -> None:
        """Re-launch an orphaned agent via its plugin's resume command.

        Caller is responsible for confirming the agent is resumable — typically
        by checking ``can_resume`` (which mirrors ``find_orphans``'s
        ``resumable`` flag).
        """
        plugin = get_plugin(agent.agent_type)
        cmd = plugin.resume_command(agent.command, agent.session_id)
        relaunch_agent(
            agent_id=agent.id,
            command=cmd,
            state_manager=self.state_mgr,
            preserve_session_id=True,
        )
