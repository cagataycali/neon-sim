#!/usr/bin/env bash
# Launch Isaac Sim on Thor with H.264 stream over TCP.
# Detects aarch64 path; falls back gracefully on x86_64.
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${PORT:-9999}"
FPS="${FPS:-15}"

# Find Isaac Sim install
ISAAC_BASE=""
for base in "$HOME/isaacsim/_build/linux-aarch64/release" \
            "$HOME/isaacsim/_build/linux-x86_64/release" \
            "/isaac-sim" \
            "/opt/nvidia/isaac-sim"; do
    if [[ -x "$base/python.sh" ]]; then
        ISAAC_BASE="$base"
        break
    fi
done

if [[ -z "$ISAAC_BASE" ]]; then
    echo "❌ Isaac Sim not found. Build it or install via Omniverse launcher." >&2
    exit 1
fi

echo "🦾 Isaac Sim: $ISAAC_BASE"
echo "📺 Stream:    tcp://0.0.0.0:$PORT  (connect from any LAN client)"
echo

cd "$HERE"
exec "$ISAAC_BASE/python.sh" neon_sim/isaac/stream.py \
    --port "$PORT" --fps "$FPS" "$@"
