# Quickstart

Get from "empty room scan" to "G1 walking in your room" in ~15 minutes.

## Prerequisites

=== "macOS (MuJoCo path)"

    ```bash
    # Python 3.10+
    pip install usd-core mujoco cyclonedds numpy

    # G1 MJCF model (one-time)
    git clone https://github.com/unitreerobotics/unitree_mujoco ~/unitree_mujoco

    # Optional: Unitree Python SDK (for full DDS bridge)
    cd /tmp
    git clone https://github.com/unitreerobotics/unitree_sdk2_python
    cd unitree_sdk2_python
    pip install -e .
    ```

=== "Linux + Isaac Sim"

    ```bash
    # Isaac Sim install (requires NVIDIA RTX GPU)
    # https://developer.nvidia.com/isaac-sim

    # Use Isaac's bundled Python
    alias python3="/isaac-sim/python.sh"

    # Packages
    python3 -m pip install usd-core cyclonedds

    # G1 USD is shipped with Isaac Sim:
    ls /isaac-sim/extscache/isaacsim.robot.assets/data/Robots/Unitree/G1/
    ```

## 1. Scan a room

1. Install [Polycam](https://poly.cam) on iPhone Pro / Android
2. Scan (LiDAR mode if available — much better than photogrammetry)
3. Export as **USDZ** (settings: full quality, textured)
4. AirDrop or iCloud to your Mac

## 2. Clone neon-sim

```bash
git clone git@github.com:cagataycali/neon-sim.git
cd neon-sim
pip install -e .
```

## 3. Drop your scan in

```bash
cp ~/Downloads/my_room.usdz assets/rooms/
```

## 4. Launch

```bash
./scripts/launch_sim.sh assets/rooms/my_room.usdz
```

This auto-detects your backend:

- Has Isaac Sim? → uses it, preprocesses USDZ → USD
- Otherwise → falls back to MuJoCo, converts USDZ → OBJ


!!! tip "macOS: use `mjpython` for the GUI"

    The MuJoCo interactive viewer needs the Cocoa event loop on macOS,
    which is provided by `mjpython` (shipped with `pip install mujoco`).
    Our `launch_sim.sh` auto-detects and uses it. For manual runs:

    ```bash
    mjpython -m neon_sim.mujoco.stage --room assets/rooms/my_room.obj
    ```

    Headless runs (with `--duration` or `--headless`) work with regular `python3`.

## 5. Connect neon-runtime

In another terminal:

```bash
cd ../neon-runtime
./scripts/start-local.sh
```

Then in Telegram: `/arm`, `stand up`, `walk forward 1m`...

The agent **has no idea** it's in sim — it publishes to the same DDS topics
that the real robot's sport_mode service listens to. neon-sim plays both
sides of that conversation.

## Troubleshooting

| Problem | Likely cause | Fix |
|---|---|---|
| "G1 USD not found" | Missing Isaac Sim robot assets | Set `ISAAC_ASSETS_PATH` or copy to `assets/robots/g1.usd` |
| "G1 MJCF not found" | No unitree_mujoco clone | `git clone https://github.com/unitreerobotics/unitree_mujoco ~/unitree_mujoco` |
| Robot spawns inside a wall | Room origin offset | Pass `--spawn-x 0 --spawn-y 0 --spawn-z 1.0` to stage |
| Robot falls through floor | Collider approximation wrong | Rerun converter with --generate-collision flag |
| DDS bridge "address in use" | Old instance running | `killall python3` or reboot |

See [Troubleshooting](preprocessing.md#troubleshooting) for more.
