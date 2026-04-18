#!/usr/bin/env bash
# Thor bootstrap — idempotent, safe to re-run
# Clones repos, checks for Isaac Sim, validates GPU, preps the sim
set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}✓${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }
err()  { echo -e "${RED}✗${NC} $1"; }
hdr()  { echo; echo -e "${YELLOW}━━━ $1 ━━━${NC}"; }

hdr "1. System info"
uname -a
if command -v nvidia-smi &>/dev/null; then
    nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
    ok "NVIDIA GPU detected"
else
    warn "No nvidia-smi found"
fi

# Thor-specific checks (Jetson Thor / AGX Thor)
if [[ -f /etc/nv_tegra_release ]]; then
    cat /etc/nv_tegra_release
    ok "Jetson/Tegra platform"
fi

hdr "2. Working directory"
WORK="${HOME}/neon-workspace"
mkdir -p "$WORK"
cd "$WORK"
ok "Using $WORK"

hdr "3. Clone repos"
for repo in neon-sim neon-runtime; do
    if [[ -d "$repo" ]]; then
        (cd "$repo" && git pull --ff-only) && ok "$repo updated"
    else
        git clone "https://github.com/cagataycali/${repo}.git" && ok "$repo cloned"
    fi
done

hdr "4. Clone unitree_mujoco (for the G1 MJCF)"
if [[ ! -d "$HOME/unitree_mujoco" ]]; then
    git clone https://github.com/unitreerobotics/unitree_mujoco "$HOME/unitree_mujoco"
fi
ok "unitree_mujoco at $HOME/unitree_mujoco"

hdr "5. Isaac Sim detection"
ISAAC_FOUND=""
for path in /isaac-sim /opt/nvidia/isaac-sim "$HOME/isaac-sim" "$HOME/.local/share/ov/pkg"/isaac-sim*; do
    if [[ -d "$path" ]]; then
        ISAAC_FOUND="$path"
        ok "Found Isaac Sim at: $path"
        break
    fi
done
if [[ -z "$ISAAC_FOUND" ]]; then
    warn "Isaac Sim not found in standard locations"
    warn "Install from: https://developer.nvidia.com/isaac-sim"
    warn "Or use: omni launcher (if available)"
fi

hdr "6. Python deps"
python3 -m pip install --user --quiet \
    cyclonedds \
    mujoco \
    usd-core \
    trimesh \
    numpy \
    && ok "Core deps installed"

hdr "7. Install unitree_sdk2_python (for neon-runtime + DDS bridge)"
cd "$WORK"
if [[ ! -d unitree_sdk2_python ]]; then
    git clone https://github.com/unitreerobotics/unitree_sdk2_python.git
fi
(cd unitree_sdk2_python && python3 -m pip install --user --quiet -e .) && ok "unitree_sdk2_python installed"

hdr "8. Isaac / MuJoCo status"
cat <<'STATUS'

Next steps:
  Terminal 1 (Isaac, if available):
    cd ~/neon-workspace/neon-sim
    # Copy a Polycam USDZ here or use a placeholder
    ./scripts/launch_sim.sh assets/rooms/<your-room>.usdz
    # This auto-detects Isaac → launches it if /isaac-sim is present

  Terminal 2 (runtime):
    cd ~/neon-workspace/neon-runtime
    G1_NETWORK_INTERFACE=lo ./scripts/start-local.sh
    # Runtime publishes DDS; sim's bridge catches them

  Verify DDS is flowing:
    cd ~/neon-workspace/unitree_sdk2_python/example
    python3 low_level/g1/g1_low_level_example.py
STATUS

ok "Bootstrap complete"
