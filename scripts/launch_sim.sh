#!/usr/bin/env bash
# Launch neon-sim — auto-detects Isaac Sim vs MuJoCo backend
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

BACKEND="${NEON_SIM_BACKEND:-auto}"
ROOM="${1:-assets/rooms/cagatay_lab.usdz}"

if [[ ! -f "$ROOM" ]]; then
    echo "❌ Room file not found: $ROOM"
    echo "   Usage: $0 <path-to-room.usdz-or-.xml>"
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
        # Isaac reads USDZ natively — no preprocessing needed
        ISAAC_PY="${ISAAC_PYTHON:-/isaac-sim/python.sh}"
        exec "$ISAAC_PY" neon_sim/isaac/stage.py --room "$ROOM"
        ;;
    mujoco)
        # MuJoCo stage.py auto-runs scripts/usd2mjcf_with_textures.py on USDZ.
        # On macOS use mjpython for the Cocoa-aware GUI viewer.
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
