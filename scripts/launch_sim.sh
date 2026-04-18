#!/usr/bin/env bash
# Launch neon-sim — auto-detects Isaac Sim vs MuJoCo backend
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

BACKEND="${NEON_SIM_BACKEND:-auto}"
ROOM="${1:-assets/rooms/cagatay_lab.usdz}"

if [[ ! -f "$ROOM" ]]; then
    echo "❌ Room file not found: $ROOM"
    echo "   Usage: $0 <path-to-room.usdz-or-.obj>"
    exit 1
fi

# Auto-detect backend
if [[ "$BACKEND" == "auto" ]]; then
    if command -v isaac-sim >/dev/null 2>&1 || [[ -d "/isaac-sim" ]] || [[ -d "/opt/nvidia/isaac-sim" ]]; then
        BACKEND="isaac"
    else
        BACKEND="mujoco"
    fi
fi

echo "🦿🪐 neon-sim launching"
echo "   Backend: $BACKEND"
echo "   Room: $ROOM"

case "$BACKEND" in
    isaac)
        SIM_ROOM="${ROOM%.usdz}_sim.usd"
        if [[ ! -f "$SIM_ROOM" ]]; then
            echo "📦 Preprocessing room (USDZ → sim-ready USD)..."
            python3 scripts/convert_polycam.py "$ROOM" --out "$SIM_ROOM"
        fi
        ISAAC_PY="${ISAAC_PYTHON:-/isaac-sim/python.sh}"
        exec "$ISAAC_PY" neon_sim/isaac/stage.py --room "$SIM_ROOM"
        ;;
    mujoco)
        # On macOS we need mjpython (MuJoCo's Cocoa-aware python) for the GUI viewer.
        # Headless runs work with regular python3.
        PYEXE="python3"
        if [[ "$(uname -s)" == "Darwin" ]] && command -v mjpython >/dev/null 2>&1; then
            PYEXE="mjpython"
            echo "   Using mjpython for Cocoa event loop"
        fi
        exec "$PYEXE" -m neon_sim.mujoco.stage --room "$ROOM" "${@:2}"
        ;;
    *)
        echo "❌ Unknown backend: $BACKEND (use 'isaac' or 'mujoco')"
        exit 1
        ;;
esac
