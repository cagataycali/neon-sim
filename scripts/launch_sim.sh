#!/usr/bin/env bash
# Launch neon-sim — auto-detects Isaac Sim vs MuJoCo backend
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
cd "$HERE"

BACKEND="${NEON_SIM_BACKEND:-auto}"
ROOM="${1:-assets/rooms/cagatay_lab.usdz}"

if [[ ! -f "$ROOM" ]]; then
    echo "❌ Room file not found: $ROOM"
    echo "   Usage: $0 <path-to-room.usdz>"
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
        # Preprocess if needed
        SIM_ROOM="${ROOM%.usdz}_sim.usd"
        if [[ ! -f "$SIM_ROOM" ]]; then
            echo "📦 Preprocessing room (USDZ → sim-ready USD)..."
            python3 scripts/convert_polycam.py "$ROOM" --out "$SIM_ROOM"
        fi
        # Launch Isaac
        ISAAC_PY="${ISAAC_PYTHON:-/isaac-sim/python.sh}"
        exec "$ISAAC_PY" neon_sim/isaac/stage.py --room "$SIM_ROOM"
        ;;
    mujoco)
        # Preprocess if needed
        SIM_ROOM="${ROOM%.usdz}.obj"
        if [[ ! -f "$SIM_ROOM" ]]; then
            echo "📦 Preprocessing room (USDZ → OBJ)..."
            python3 scripts/usdz_to_obj.py "$ROOM" --out "$SIM_ROOM"
        fi
        # Launch MuJoCo
        exec python3 -m neon_sim.mujoco.stage --room "$SIM_ROOM"
        ;;
    *)
        echo "❌ Unknown backend: $BACKEND (use 'isaac' or 'mujoco')"
        exit 1
        ;;
esac
