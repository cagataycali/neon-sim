# 🦿🪐 neon-sim

> Drive your Unitree G1 through **your actual room** (scanned with Polycam) in NVIDIA Isaac Sim — using the same neon agent that controls the real robot.

[![docs](https://img.shields.io/badge/docs-github%20pages-orange)](https://cagataycali.github.io/neon-sim)
[![runtime](https://img.shields.io/badge/pairs%20with-neon--runtime-ff6b6b)](https://github.com/cagataycali/neon-runtime)

## The idea

```
┌──────────────────────────────────────────────────────────────────┐
│                        YOUR MAC MINI                              │
│                                                                   │
│  neon-runtime (Telegram agent)                                   │
│    │                                                              │
│    ▼ DDS (CycloneDDS, topic: rt/api/sport/*)                     │
│    │                                                              │
│  neon-sim bridge                                                  │
│    │                                                              │
│    ▼ Isaac Sim (loads your Polycam .usdz)                        │
│                                                                   │
│    🏠 Your scanned room + 🤖 G1 articulation                     │
└──────────────────────────────────────────────────────────────────┘
```

Your `neon-runtime` agent **doesn't know** it's talking to a sim — same DDS
topics, same tools, same motion guard. Test new behaviors safely in sim,
deploy to hardware with confidence.

## Quick start

```bash
# 1. Install Isaac Sim (Linux/Windows — not macOS native, but runs in WSL/Docker)
#    https://developer.nvidia.com/isaac-sim

# 2. Clone this repo
git clone git@github.com:cagataycali/neon-sim.git
cd neon-sim

# 3. Drop your Polycam USDZ in
cp ~/Desktop/my_room.usdz assets/rooms/

# 4. Launch sim + DDS bridge
./scripts/launch_sim.sh --room assets/rooms/my_room.usdz

# 5. In another terminal, run neon-runtime as usual
cd ../neon-runtime
./scripts/start-local.sh
# Ask it to "walk forward 1m" → robot walks in sim through your room
```

## What's in this repo

| Module | Purpose |
|---|---|
| `neon_sim/isaac/` | Isaac Sim stage loader + G1 spawner + DDS publisher |
| `neon_sim/bridge/` | Translates between Isaac's API and `unitree_hg` DDS messages |
| `neon_sim/mujoco/` | (alt) MuJoCo backend — no GPU needed |
| `neon_sim/assets/rooms/` | Your Polycam scans |
| `neon_sim/assets/robots/` | G1 USD model (fetched from Unitree) |
| `scripts/usd2mjcf_with_textures.py` | Preprocesses a raw Polycam USDZ for sim (decimation, colliders) |
| `scripts/launch_sim.sh` | One-command bring-up |

## Why not just use MuJoCo?

MuJoCo is great and **included as a fallback** — but Isaac wins because:

1. **Native USDZ loading** — your Polycam scan drops right in
2. **Photoreal PBR rendering** — scan textures look right
3. **Unitree ships official G1 USD** — articulation solved
4. **DDS bridge built in** (via Omniverse ROS2 bridge)

MuJoCo needs OBJ conversion + XML scene authoring. Slower to iterate.

## See also

- [neon-runtime](https://github.com/cagataycali/neon-runtime) — the agent itself
- [g1-runtime](https://github.com/cagataycali/g1-runtime) — hardware reverse-engineering notes
- [Polycam](https://poly.cam) — the scanning app

## License

MIT
