# Background Launch: Instant Attach, Command Types Itself

## Problem

When launching a new agent from the desk TUI, the user fills out a 3-step form (directory → command → label). On label submission, `launch_agent` runs synchronously on the UI thread:

1. `server.new_session(...)` — creates the tmux session (fast)
2. `_wait_for_shell(pane)` — polls the pane for a shell prompt, up to **5 seconds**
3. `pane.send_keys(cmd_str, enter=True)` — sends the command

During step 2 the Textual UI is frozen on the label input — no redraw, no feedback, no escape. The user stares at a stuck form for 1–5 seconds until `_attach_to_agent` fires and tmux takes over the terminal.

Note: this wait is non-negotiable. A prior attempt (commit `822d83d`) passed the command via tmux's `window_command`, avoiding the wait entirely. It was reverted (`3e679e3`) because:
- The pane died immediately when the command exited — no shell to fall back to
- Shell config (`.zshrc`, PATH, aliases) was not loaded

So the shell must start first, then the command gets typed into it. This design keeps `_wait_for_shell` + `send_keys`, it only moves them off the UI thread.

## Design

Split `launch_agent` into two phases and let the TUI opt into running phase 2 in a background thread. The user is attached to the tmux session while the background thread is still waiting for the shell, so they see: blank pane → shell prompt appears → command is typed → command runs. No form freeze, no loading modal.

### Two Phases

**Phase 1 — synchronous, always:**
- `shutil.which("tmux")` check
- Sanitize label, compute `session_name`
- Kill stale session with the same name if present
- `server.new_session(...)` with `detach=True`
- `session.set_option("remain-on-exit", "on")`
- Read `pane.pane_pid` (the shell PID, valid as soon as `new_session` returns)
- Build `AgentInfo` and call `state_manager.add_agent(agent)`
- Return `agent_id`

Reading `pane.pane_pid` must happen in phase 1 because `AgentInfo.pid` depends on it, and `AgentInfo` is persisted before phase 2 runs. Do not move this into `_finalize`.

**Phase 2 — synchronous OR background thread:**
- `_wait_for_shell(pane)` — up to 5s, `raises=False`
- `pane.send_keys(cmd_str, enter=True)`

### API Change

```python
def launch_agent(
    command, working_dir, label, state_manager, prefix="aque",
    background: bool = False,    # NEW
) -> int:
```

- `background=False` (default) — current blocking behavior, used by `aque run` CLI and all existing tests. No change for them.
- `background=True` — used only by the desk TUI. Phase 2 is dispatched to a `threading.Thread(daemon=True)` and `launch_agent` returns the agent_id immediately after phase 1.

### Desk TUI Flow

In `desk.py`, `on_input_submitted` for the `label-input` step changes one argument:

```python
agent_id = launch_agent(
    command=command,
    working_dir=form._selected_dir,
    label=form._label or None,
    state_manager=self.state_mgr,
    prefix=self.config["session_prefix"],
    background=True,                      # NEW
)
# ... form cleanup unchanged ...
if agent and not self._skip_attach:
    self._attach_to_agent(agent)          # now attaches nearly instantly
```

`_attach_to_agent` is unchanged. When tmux suspends Textual and attaches to the new session, the background thread is still running in parallel — `_wait_for_shell` polls via `tmux capture-pane`, then `send_keys` issues `tmux send-keys -t <session>`. Both are independent client calls against the tmux server; neither is blocked by the attached client.

### Background Thread Behavior

```python
def _finalize(pane: Pane, cmd_str: str) -> None:
    try:
        _wait_for_shell(pane)
        pane.send_keys(cmd_str, enter=True)
    except Exception:
        pass
```

Wrapped in a bare `except` because failures are all benign from the app's point of view:

| Scenario | What happens |
|----------|--------------|
| Shell never prints a prompt within 5s | `_wait_for_shell` already uses `retry_until(..., raises=False)` — it falls through and `send_keys` runs anyway. Matches current behavior. |
| User kills the session before `send_keys` fires | `send_keys` raises; the bare except swallows it. Nothing else to clean up. |
| User detaches before `send_keys` fires | tmux keeps the session alive; `send_keys` lands normally. User sees the command the next time they attach. |
| `tmux` binary disappears mid-flight | `send_keys` raises; swallowed. |

### Thread Safety

`libtmux` operations shell out to independent `tmux` client subprocesses. The main thread entering `with self.suspend(): subprocess.run(["tmux", "attach-session", ...])` starts a tmux client attached to the session, but it does not hold any lock on the server. A background thread calling `pane.capture_pane()` (`tmux capture-pane -p -t …`) or `pane.send_keys(...)` (`tmux send-keys -t …`) runs its own short-lived client against the same server. This is the same reason you can run `tmux send-keys -t foo 'ls' Enter` from any terminal while someone else is attached to `foo`.

### Testing Hook

The new test needs to `.join()` the spawned thread to make assertions deterministic. Expose threads via a module-level list:

```python
# aque/run.py
_background_threads: list[threading.Thread] = []
```

When `background=True`, `launch_agent` appends the spawned thread to this list before returning. Tests drain and join it:

```python
import aque.run
# ... call launch_agent(..., background=True) ...
threads = list(aque.run._background_threads)
aque.run._background_threads.clear()
for t in threads:
    t.join(timeout=1.0)
```

The list is module-private (leading underscore), not part of the public API, and only read by tests. It is never read during normal operation. Nothing prunes entries during normal use — daemon threads exit on their own, and the list only grows for the lifetime of the process (bounded by the number of agents launched in a session, which is small).

## Files Changed

- `aque/run.py` — Add `background` parameter. Move `_wait_for_shell` + `send_keys` into an inner `_finalize()`. Dispatch to a daemon thread when `background=True`, append to `_background_threads`. Wrap `_finalize` body in `try/except Exception: pass`.
- `aque/desk.py` — `on_input_submitted` passes `background=True` to `launch_agent`.
- `tests/test_run.py` — Add one new test: `test_launch_background_returns_before_finalize`. Patches `_wait_for_shell` with a short `time.sleep` to force ordering, calls `launch_agent(..., background=True)`, asserts the function returned before `send_keys` was called, joins the thread, then asserts `send_keys` was called with the right args.

## Scope Guardrails — What This Does NOT Change

- No new `LAUNCHING` agent state
- No loading modal, spinner, toast, or status-bar indicator
- No changes to auto-attach, monitor daemon, or state machine
- No change to `aque run` CLI behavior (stays synchronous)
- No refactor of `_attach_to_agent` or `AutoAttachModal`
- No new dependencies

## Edge Cases

- **User submits the form with `_skip_attach=True` (test mode):** Phase 1 completes, agent is in state, background thread runs, no attach happens. Existing test hooks keep working — they already mock `_wait_for_shell`.
- **User launches many agents in rapid succession:** Each spawns its own daemon thread appended to `_background_threads`. The list grows but daemon threads exit within ~5s of launch. No cleanup needed; the list is only inspected by tests.
- **Form submission races with dashboard refresh:** Agent is added to state during phase 1 (before the background thread starts), so the next refresh sees it consistently.
- **Command contains shell metacharacters:** Unchanged — `shlex.join` quotes the command and `send_keys` sends it as literal keystrokes followed by Enter. The shell parses it exactly as before.
