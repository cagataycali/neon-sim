# First run results

## Validated on real hardware

Tested on: **Apple M-series Mac Mini, macOS 15**, MuJoCo 3.5.0.

### What we ran

```bash
# 1. Clone unitree_mujoco (one-time)
git clone https://github.com/unitreerobotics/unitree_mujoco ~/unitree_mujoco

# 2. Drop Polycam scan in
cp ~/Library/Mobile\ Documents/com~apple~CloudDocs/cagatay_lab_3_7_2026.usdz \
   assets/rooms/cagatay_lab.usdz

# 3. Launch
./scripts/launch_sim.sh assets/rooms/cagatay_lab.usdz
```

### What happened

```
[INFO] 🏠 Room: assets/rooms/cagatay_lab.obj
[INFO] 🤖 G1 29-DoF: ~/unitree_mujoco/unitree_robots/g1/scene_29dof.xml
[INFO] 🔀 Composite: ~/unitree_mujoco/unitree_robots/g1/neon_sim_composite.xml
[INFO]    32 bodies, 29 actuators, 75 geoms, 37 meshes
[INFO] ▶️  Launching interactive viewer (close window to exit)
```

A MuJoCo window popped up showing the **29-DoF Unitree G1** standing in the middle of my **7.5 m × 13.3 m scanned lab**.

### Performance

| Metric | Value |
|---|---|
| Headless simulation speed | **27.7× real-time** (2 sim-seconds in 0.07 s) |
| Composite scene load | ~1 second |
| Interactive viewer frame rate | 60 fps steady |
| Memory footprint | ~380 MB |
| G1 bodies | 31 + 1 (room) = **32 bodies** |
| Room mesh | 170,022 verts / 212,577 faces |

### Why it's fast on a Mac

MuJoCo's CPU-based physics + the fact that:

1. The room is a **decoration mesh only** by default (contype=0) — no collision
2. The G1 articulation is already ≤30 DoF — manageable
3. Apple Silicon's memory bandwidth is excellent for dense linear algebra

Enable room collision with `--collide`:

```bash
mjpython -m neon_sim.mujoco.stage --room assets/rooms/my_room.obj --collide
```

Performance drops to ~5× real-time because every contact check hits 212 k triangles.
For real collision work, decimate the mesh first (Blender → Decimate → Collapse → ratio 0.2).

### Next step

With the viewer running, fire up `neon-runtime` in another terminal. It will
publish to `rt/api/sport/request` on the loopback interface — and this process
handles it. From the agent's perspective, it's the real G1.

```bash
# Terminal 1 (sim)
./scripts/launch_sim.sh assets/rooms/my_room.usdz

# Terminal 2 (agent)
cd ../neon-runtime
G1_NETWORK_INTERFACE=lo0 ./scripts/start-local.sh

# Telegram: /arm, stand up, walk forward 1m...
```

See [DDS Bridge](dds-bridge.md) for the full topic map.
