# Isaac Sim vs MuJoCo

Pick your fighter:

## Isaac Sim 🥇

**Use if**: you have an NVIDIA GPU (RTX series), running Linux or WSL.

### Pros
- Native `.usdz` import — no OBJ conversion
- PBR rendering with your scan textures
- Unitree ships an official G1 USD model (in `isaacsim.robot.assets`)
- Omniverse bridge supports ROS 2 / DDS natively
- Reinforcement learning ready (Isaac Lab)

### Cons
- Requires NVIDIA RTX hardware (not M-series Mac)
- Heavy install (~30GB)
- Linux-first (Windows via WSL is flaky)

### Install
https://developer.nvidia.com/isaac-sim → pick latest 4.x.

Launch:

```bash
NEON_SIM_BACKEND=isaac ./scripts/launch_sim.sh assets/rooms/my_room.usdz
```

## MuJoCo 🪶

**Use if**: you're on a Mac, or no NVIDIA GPU, or just want something lightweight.

### Pros
- Runs everywhere (M-series Mac, Linux, Windows)
- Fast — no GPU needed
- Unitree ships G1 MJCF models in `unitree_mujoco`
- `pip install mujoco` and you're done (no 30GB download)

### Cons
- Can't load USDZ directly — must convert to OBJ (done automatically)
- No PBR; scan textures become plain mesh color
- No official DDS bridge — we ship our own (same as Isaac path)

### Install

```bash
pip install mujoco usd-core cyclonedds
git clone https://github.com/unitreerobotics/unitree_mujoco ~/unitree_mujoco
```

Launch:

```bash
NEON_SIM_BACKEND=mujoco ./scripts/launch_sim.sh assets/rooms/my_room.usdz
```

## Shared: The DDS bridge

Both backends use the same `neon_sim/bridge/dds_bridge.py` — which means
your agent code, `neon-runtime`, doesn't know or care which one you pick.

Swap between them to taste.

## Which should I start with?

- **Have a Mac, want to ship tonight** → MuJoCo
- **Have a Linux gaming PC with RTX** → Isaac
- **Want photoreal demos to show off** → Isaac
- **Want something that works on an airplane** → MuJoCo
