#!/usr/bin/env bash
set -euo pipefail

# ── Config ───────────────────────────────────────────────────────
DEMO_DIR="/tmp/aque-demo"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
AQUE="$PROJECT_DIR/.venv/bin/aque"
PYTHON="$PROJECT_DIR/.venv/bin/python"
CAST_FILE="$SCRIPT_DIR/demo.cast"
GIF_FILE="$PROJECT_DIR/docs/demo.gif"

# ── Cleanup function ─────────────────────────────────────────────
cleanup() {
    echo "Cleaning up..."
    # Kill all demo agent sessions
    tmux list-sessions -F '#{session_name}' 2>/dev/null | grep '^aque-demo-' | while read -r s; do
        tmux kill-session -t "$s" 2>/dev/null || true
    done
    rm -rf "$DEMO_DIR"
}
trap cleanup EXIT

# ── Pre-flight checks ────────────────────────────────────────────
if ! command -v asciinema &>/dev/null; then
    echo "Error: asciinema is required but not found"
    exit 1
fi

# ── Setup ────────────────────────────────────────────────────────
echo "Setting up demo environment..."
cleanup 2>/dev/null || true
mkdir -p "$DEMO_DIR"
cp "$SCRIPT_DIR/config.yaml" "$DEMO_DIR/config.yaml"

# ── Seed agents ──────────────────────────────────────────────────
echo "Launching fake agents..."

# Agents use --delay so they don't go idle before the desk is visible.
# Timeline: desk opens at ~t=0, agent 1 idle at ~t=6, agent 2 idle at ~t=14
$AQUE --aque-dir "$DEMO_DIR" run --dir "$PROJECT_DIR" --label "api-auth" -- \
    "$PYTHON" "$SCRIPT_DIR/fake_agent.py" --delay 2 --work-duration 4 --label api-auth

$AQUE --aque-dir "$DEMO_DIR" run --dir "$PROJECT_DIR" --label "web-frontend" -- \
    "$PYTHON" "$SCRIPT_DIR/fake_agent.py" --delay 2 --work-duration 12 --label web-frontend

$AQUE --aque-dir "$DEMO_DIR" run --dir "$PROJECT_DIR" --label "test-suite" -- \
    "$PYTHON" "$SCRIPT_DIR/fake_agent.py" --delay 2 --work-duration 20 --label test-suite

echo "Agents launched. Waiting 1s for startup..."
sleep 1

# ── Record ───────────────────────────────────────────────────────
echo ""
echo "=== Starting interactive recording ==="
echo ""
echo "The desk will open with 3 agents. Here's what to do:"
echo ""
echo "  1. Watch: agents are all 'running'"
echo "  2. Wait: 'api-auth' goes 'waiting', countdown modal appears"
echo "  3. Auto-attaches to api-auth — you'll see the fake agent output"
echo "  4. DETACH: press Ctrl-b then d"
echo "  5. Back on dashboard, 'web-frontend' goes waiting, auto-attaches"
echo "  6. DETACH: press Ctrl-b then d"
echo "  7. Dashboard shows remaining agents running"
echo "  8. QUIT: press q"
echo ""
echo "Press Enter to start recording..."
read -r

asciinema rec --cols 120 --rows 35 \
    -c "$AQUE --aque-dir $DEMO_DIR desk" \
    "$CAST_FILE"

echo ""
echo "Recording complete: $CAST_FILE"

# ── Convert to GIF ──────────────────────────────────────────────
if command -v agg &>/dev/null; then
    echo "Converting to GIF..."
    mkdir -p "$(dirname "$GIF_FILE")"
    agg "$CAST_FILE" "$GIF_FILE"
    echo "GIF created: $GIF_FILE"
else
    echo ""
    echo "agg not found — skipping GIF conversion."
    echo "Install: cargo install --git https://github.com/asciinema/agg"
    echo "Then run: agg $CAST_FILE $GIF_FILE"
fi

echo "Done!"
