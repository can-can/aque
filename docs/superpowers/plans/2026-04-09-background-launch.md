# Background Launch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move `_wait_for_shell` + `send_keys` off the UI thread so the desk TUI attaches to tmux instantly — the user watches the shell boot and the command type itself.

**Architecture:** Add a `background: bool = False` parameter to `launch_agent`. When `True`, phase 2 (shell wait + send_keys) runs on a daemon thread; phase 1 (session creation + state registration) stays synchronous. Only `desk.py` passes `background=True`; CLI and existing tests are unchanged.

**Tech Stack:** Python `threading`, libtmux, Textual (no new dependencies)

---

### Task 1: Add background thread support to `launch_agent`

**Files:**
- Modify: `aque/run.py:1-86`

- [ ] **Step 1: Add `threading` import and `_background_threads` list**

At the top of `aque/run.py`, add the import and module-level list after the existing imports:

```python
import threading
```

And after the `SHELL_PROMPT_RE` line:

```python
_background_threads: list[threading.Thread] = []
```

- [ ] **Step 2: Add `background` parameter and split into phases**

Replace the current `launch_agent` function body. The full updated function:

```python
def launch_agent(
    command: list[str],
    working_dir: str,
    label: str | None,
    state_manager: StateManager,
    prefix: str = "aque",
    background: bool = False,
) -> int:
    if label is None:
        dir_basename = Path(working_dir).name
        label = f"{command[0]} . {dir_basename}"

    agent_id = state_manager.next_id()
    sanitized_label = _sanitize_session_name(label)
    session_name = f"{prefix}-{sanitized_label}-{agent_id}"

    if not shutil.which("tmux"):
        raise RuntimeError(
            "tmux is not installed. Install it with: brew install tmux"
        )

    server = libtmux.Server()

    # Kill stale session with the same name if it exists
    existing = server.sessions.get(session_name=session_name, default=None)
    if existing:
        existing.kill()

    session = server.new_session(
        session_name=session_name,
        start_directory=working_dir,
        detach=True,
    )

    session.set_option("remain-on-exit", "on")

    pane = session.active_pane
    cmd_str = shlex.join(command)

    agent = AgentInfo(
        id=agent_id,
        tmux_session=session_name,
        label=label,
        dir=working_dir,
        command=command,
        state=AgentState.RUNNING,
        pid=int(pane.pane_pid),
    )
    state_manager.add_agent(agent)

    def _finalize() -> None:
        try:
            _wait_for_shell(pane)
            pane.send_keys(cmd_str, enter=True)
        except Exception:
            pass

    if background:
        thread = threading.Thread(target=_finalize, daemon=True)
        thread.start()
        _background_threads.append(thread)
    else:
        _finalize()

    return agent_id
```

Key changes from the original:
- `AgentInfo` is built and persisted **before** `_wait_for_shell` (was after)
- `_finalize()` wraps the shell wait + send_keys with try/except
- `background=True` dispatches `_finalize` to a daemon thread
- `_finalize` body is identical for both paths — same `_wait_for_shell` + `send_keys`

- [ ] **Step 3: Run existing tests to verify no regression**

Run: `cd /Users/cancan/Projects/aque && python -m pytest tests/test_run.py -v`

Expected: All 4 existing tests PASS. They don't pass `background=True`, so they hit the synchronous `_finalize()` path (same behavior as before, but `AgentInfo` is persisted earlier — which is fine because tests assert on final state).

- [ ] **Step 4: Commit**

```bash
git add aque/run.py
git commit -m "feat: add background parameter to launch_agent

Phase 2 (_wait_for_shell + send_keys) can now run on a daemon
thread when background=True, returning immediately after session
creation and state registration."
```

---

### Task 2: Add test for background launch mode

**Files:**
- Modify: `tests/test_run.py`

- [ ] **Step 1: Write the test**

Add the following test to the `TestLaunchAgent` class in `tests/test_run.py`:

```python
    @patch("aque.run._wait_for_shell")
    @patch("aque.run.shutil.which", return_value="/usr/bin/tmux")
    @patch("aque.run.libtmux.Server")
    def test_launch_background_returns_before_finalize(self, mock_server_cls, mock_which, mock_wait, tmp_aque_dir):
        import time
        import aque.run

        # Make _wait_for_shell take a moment so we can observe ordering
        mock_wait.side_effect = lambda pane: time.sleep(0.1)

        mock_server = MagicMock()
        mock_server_cls.return_value = mock_server
        mock_session = MagicMock()
        mock_session.name = "aque-bg-1"
        mock_pane = MagicMock()
        mock_pane.pane_pid = "99999"
        mock_session.active_pane = mock_pane
        mock_server.new_session.return_value = mock_session

        mgr = StateManager(tmp_aque_dir)
        agent_id = launch_agent(
            command=["claude", "--model", "opus"],
            working_dir="/tmp/test",
            label="bg test",
            state_manager=mgr,
            background=True,
        )

        # launch_agent returned immediately — agent is in state
        assert agent_id == 1
        state = mgr.load()
        assert len(state.agents) == 1
        assert state.agents[0].label == "bg test"

        # send_keys has NOT been called yet (thread is still in _wait_for_shell sleep)
        mock_pane.send_keys.assert_not_called()

        # Join the background thread and verify finalization completed
        threads = list(aque.run._background_threads)
        aque.run._background_threads.clear()
        for t in threads:
            t.join(timeout=2.0)

        mock_wait.assert_called_once_with(mock_pane)
        mock_pane.send_keys.assert_called_once_with("claude --model opus", enter=True)
```

- [ ] **Step 2: Run the new test**

Run: `cd /Users/cancan/Projects/aque && python -m pytest tests/test_run.py::TestLaunchAgent::test_launch_background_returns_before_finalize -v`

Expected: PASS

- [ ] **Step 3: Run all tests in test_run.py**

Run: `cd /Users/cancan/Projects/aque && python -m pytest tests/test_run.py -v`

Expected: All 5 tests PASS

- [ ] **Step 4: Commit**

```bash
git add tests/test_run.py
git commit -m "test: verify background launch returns before finalize"
```

---

### Task 3: Pass `background=True` from the desk TUI

**Files:**
- Modify: `aque/desk.py:876`

- [ ] **Step 1: Add `background=True` to the launch_agent call**

In `aque/desk.py`, in the `on_input_submitted` method, change the `launch_agent` call (around line 876):

```python
            agent_id = launch_agent(
                command=command,
                working_dir=form._selected_dir,
                label=form._label or None,
                state_manager=self.state_mgr,
                prefix=self.config["session_prefix"],
                background=True,
            )
```

The only change is adding `background=True,` — all surrounding code stays identical.

- [ ] **Step 2: Run the full test suite to verify no regression**

Run: `cd /Users/cancan/Projects/aque && python -m pytest tests/ -v`

Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add aque/desk.py
git commit -m "feat: desk TUI launches agents with background=True

The form no longer freezes for 1-5s during shell readiness
detection. Users are attached to tmux instantly and see the
command type itself once the shell is ready."
```

---

### Task 4: Manual smoke test

- [ ] **Step 1: Run the desk TUI and launch a new agent**

Run: `cd /Users/cancan/Projects/aque && python -m aque desk`

1. Press `n` to open the new agent form
2. Select a directory
3. Enter a command (e.g. `echo hello`)
4. Enter a label and press Enter

**Verify:**
- The form disappears instantly (no 1–5s freeze)
- tmux attaches immediately
- You see the shell prompt appear, then the command types itself and executes
- Detaching (`Ctrl-b d`) returns to the dashboard with the agent listed

- [ ] **Step 2: Test with a real long-running command**

Launch another agent with `claude` or `sleep 30` to verify the background thread works when the shell takes a moment to start and the user is already watching.
