<p align="center">
  <img src="https://raw.githubusercontent.com/can-can/aque/main/docs/logo.svg" width="80" alt="aque logo">
</p>

<h1 align="center">Aque</h1>

<p align="center">
  <a href="https://pypi.org/project/aque/"><img src="https://img.shields.io/pypi/v/aque.svg" alt="PyPI version"></a>
  <a href="https://pypi.org/project/aque/"><img src="https://img.shields.io/pypi/pyversions/aque.svg" alt="Python"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
</p>

A tmux-based agent queue manager. You sit at one "desk" and your AI agents come to you.

## Why?

Running multiple AI coding agents (Claude Code, aider, Codex) at once? They all need your attention at different times. Aque queues them so you work through them one at a time — no forgotten terminal tabs, no context switching.

![Demo](https://raw.githubusercontent.com/can-can/aque/main/docs/demo.gif)

## Install

```bash
pipx install aque
```

Or with pip:

```bash
pip install aque
```

Requires: Python 3.11+, [tmux](https://github.com/tmux/tmux)

### Development

```bash
git clone https://github.com/can-can/aque.git
cd aque
pip install -e ".[dev]"
```

## Usage

Launch agents:

```bash
aque run --dir ~/projects/api --label "auth fix" -- claude --model opus
aque run --dir ~/projects/web -- aider --model gpt-4
aque run --dir ~/code/tests -- codex
```

Sit at your desk:

```bash
aque desk
```

The desk shows a **unified dashboard** with all your agents, their states, and a live preview of the selected agent's terminal output.

### Dashboard Keys

| Key | Action |
|-----|--------|
| ↑↓ | Navigate agent list |
| Enter | Attach to selected agent |
| n | Create new agent |
| k | Kill selected agent (moves to history) |
| h | Toggle hold on selected agent |
| q | Quit desk |

### Detach Behavior

When you detach from a tmux session (`Ctrl-b d`), aque handles the transition automatically:

- **Running/waiting agent** — auto-dismissed back to running, returns to dashboard
- **Exited agent** — auto-marked as done and moved to history

No action menu, no extra steps.

### Auto-Attach

When a waiting agent is detected (on the dashboard or after detaching), aque shows a **3-second countdown modal** and auto-attaches to the top-priority waiting agent. Press **Esc** to cancel and stay on the dashboard.

### Idle Detection

Aque monitors tmux panes for prompt markers (`❯`, `$`, `>>>`) to detect when an agent is waiting for input. After the configured idle timeout (default: 10s), the agent transitions from `running` to `waiting` and enters the queue.

### Agent States

| State | Meaning |
|-------|---------|
| running | Agent is actively working |
| waiting | Agent is idle, queued for your attention |
| focused | You are currently attached to this agent |
| on_hold | Paused, skipped in the queue |
| exited | Tmux session has ended |
| done | Completed, moved to history |

### Other Commands

```bash
aque list    # show all agents and states
aque kill 3  # terminate an agent
```

## Configuration

Edit `~/.aque/config.yaml`:

```yaml
idle_timeout: 10
snapshot_interval: 2
session_prefix: aque
action_keys:
  dismiss: d
  done: k
  skip: s
  hold: h
```

## License

[MIT](LICENSE)
