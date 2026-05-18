# Manual end-to-end checklist: auto-responder

Run on a real terminal with tmux installed.

1. Launch a partner: `aque run --dir /tmp/scratch -- claude`
2. Run `aque list` — expect to see the partner and its `↳ resp(<id>)` row indented under it.
3. Open the dashboard: `aque desk`. Expect the responder to be HIDDEN by default.
4. Press **R** to reveal the responder. It appears indented under its partner.
5. Wait for the partner to go to `waiting`. After `responder_idle_gap` seconds, observe the AQUE: nudge line typed into the responder's pane.
6. Verify the responder's reply lands in the partner's pane (via the responder's own `tmux send-keys`).
7. Press **a** while the partner is selected. Status notification: `Auto-response: off`. Confirm nudges stop on the next waiting transition.
8. Press **a** again. Notification: `Auto-response: on`. Nudges resume.
9. Press **k** with the partner selected. Expect the responder's tmux session to be killed and its state record removed (verify with `aque list` and `tmux ls`).
10. `aque run --no-responder -- claude` — confirm only one agent is created (no paired responder).
