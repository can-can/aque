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

Use `--type` to enable signal-based idle detection for supported agent types:

```bash
aque run --type claude --dir ~/projects/api -- claude --model opus
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
| R | Toggle responder visibility |
| a | Toggle auto-response on selected partner |
| q | Quit desk |

### Detach Behavior

When you detach from a tmux session (`Ctrl-b d`), aque handles the transition automatically:

- **Running/waiting agent** — auto-dismissed back to running, returns to dashboard
- **Exited agent** — auto-marked as done and moved to history

No action menu, no extra steps.

### Auto-Attach

When a waiting agent is detected (on the dashboard or after detaching), aque shows a **3-second countdown modal** and auto-attaches to the top-priority waiting agent. Press **Esc** to cancel and stay on the dashboard.

### Agent Types & Signal-Based Detection

For supported agent types, aque can use signal files instead of polling for more reliable idle detection.

When you specify `--type`, aque installs a hook into the agent that writes a signal file when it stops. This is faster and more accurate than prompt-marker polling.

Currently supported types:

| Type | Detection |
|------|-----------|
| `claude` | Hook installed in `~/.claude/settings.json` |
| `codex` | Hook installed in `~/.codex/hooks.json` |
| `gemini` | Hook installed in `~/.gemini/settings.json` |
| `opencode` | Plugin installed in `~/.config/opencode/plugins/aque.js` |
| `aider` | `--notifications-command` injected at launch (no config hook) |

When creating an agent from the dashboard (`n`), the new agent form lets you select a type in the first step.

The agent type is shown as a tag in the agent list, and the detection method is shown in the preview panel.

### Auto-Responder

When you launch an agent, aque automatically pairs it with a responder agent — another aque-managed tmux session. After the partner sits in `waiting` for `responder_idle_gap` seconds (default 30), aque types a one-line nudge into the responder's pane. The responder reads the partner's screen with `tmux capture-pane` and replies with `tmux send-keys` using its own toolbelt.

Responders are hidden from the dashboard by default. Press **R** to reveal them, and **a** to toggle auto-response on the selected partner.

To suppress auto-response for a single launch: `aque run --no-responder -- ...`. To override the responder command for a single launch: `aque run --responder-cmd "claude --model haiku" -- ...`.

Disable globally in `~/.aque/config.yaml`:

```yaml
responder_enabled: false
```

Configurable keys (with defaults):

```yaml
responder_enabled: true
responder_command: ["claude"]
responder_idle_gap: 30
responder_dir: null   # null => ~/.aque/responders/<partner_id>/
```

### Idle Detection

Aque monitors tmux panes for prompt markers (`❯`, `$`, `>>>`) to detect when an agent is waiting for input. After the configured idle timeout (default: 10s), the agent transitions from `running` to `waiting` and enters the queue.

When using a typed agent, signal files take precedence over prompt-marker polling.

### Narrow Terminal Support

On terminals narrower than 80 columns, aque automatically switches to a compact single-column layout: the preview panel is hidden, the agent list uses shorter labels, and modals/forms adapt to fit. The layout updates live on resize.

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
default_dir: ~/Projects
action_keys:
  dismiss: d
  done: k
  skip: s
  hold: h
```

## License

[MIT](LICENSE)

## Remote control (`aque serve`)

Control your agents from the AqueIOS phone app over your LAN:

```bash
aque serve            # prints a QR code + token; advertises over Bonjour
```

Scan the QR code in the AqueIOS app to pair. To validate from a laptop/phone
browser first, open `http://<your-mac-ip>:8722/?id=<agent-id>&token=<token>`.

> ⚠️ **LAN-only / trusted-network only.** v1 traffic is unencrypted and a
> terminal grants full command execution on your Mac. Anyone on your network
> who has the token can drive your agents. Use it only on a network you trust;
> Tailscale + TLS hardening is planned for a later phase.
