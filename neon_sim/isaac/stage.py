"""Isaac Sim stage loader — loads a Polycam room + spawns G1 robot.

This module is intended to run INSIDE Isaac Sim's Python environment.
It cannot run standalone (no `pip install isaacsim`).

Typical entrypoint:
    ./python.sh neon_sim/isaac/stage.py --room /path/to/room_sim.usd

Or via Isaac Sim's Script Editor.
"""
from __future__ import annotations
import argparse
import os
import sys
from pathlib import Path

# Isaac Sim imports — these only resolve inside the Isaac Sim python env
try:
    from isaacsim import SimulationApp
except ImportError:
    print("❌ This script must run inside Isaac Sim's python environment.", file=sys.stderr)
    print("   Run with: ./python.sh neon_sim/isaac/stage.py --room <path>", file=sys.stderr)
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--room", required=True, help="Path to room_sim.usd")
    ap.add_argument("--robot-usd", default=None,
                    help="Path to G1 robot USD (default: fetched from Unitree)")
    ap.add_argument("--spawn-x", type=float, default=0.0)
    ap.add_argument("--spawn-y", type=float, default=0.0)
    ap.add_argument("--spawn-z", type=float, default=0.8,
                    help="Starting Z (above floor so it falls into squat)")
    ap.add_argument("--headless", action="store_true", help="Run without GUI")
    ap.add_argument("--physics-dt", type=float, default=1.0 / 200.0)
    ap.add_argument("--render-dt", type=float, default=1.0 / 60.0)
    args = ap.parse_args()

    # Launch simulation
    config = {
        "headless": args.headless,
        "physics_dt": args.physics_dt,
        "rendering_dt": args.render_dt,
    }
    kit = SimulationApp(config)

    # Now imports work
    from omni.isaac.core import World
    from omni.isaac.core.utils.stage import add_reference_to_stage, create_new_stage
    from omni.isaac.core.utils.prims import create_prim
    from omni.isaac.core.articulations import Articulation
    import omni.usd

    print(f"🏠 Loading room: {args.room}")
    room_path = Path(args.room).resolve()
    if not room_path.exists():
        sys.exit(f"❌ Room file not found: {room_path}")

    # Create a fresh stage
    create_new_stage()
    world = World(
        physics_dt=args.physics_dt,
        rendering_dt=args.render_dt,
        stage_units_in_meters=1.0,
    )

    # Add the room as a reference
    add_reference_to_stage(str(room_path), "/World/Room")

    # Ground plane (backup in case the converted room's floor is off)
    world.scene.add_default_ground_plane()

    # Load the G1 robot
    robot_usd = args.robot_usd or _default_g1_usd()
    print(f"🤖 Loading robot: {robot_usd}")
    if not Path(robot_usd).exists():
        print(f"⚠️  Robot USD not found. Fetching from Unitree...")
        robot_usd = _download_g1_usd()

    add_reference_to_stage(str(robot_usd), "/World/G1")

    # Set spawn position (G1 lives in /World/G1/base or similar)
    g1 = Articulation(prim_path="/World/G1", name="g1", position=(args.spawn_x, args.spawn_y, args.spawn_z))
    world.scene.add(g1)

    world.reset()
    print("✅ Stage loaded. Simulation running.")

    # Hand off to DDS bridge
    from neon_sim.bridge.dds_bridge import DDSBridge
    bridge = DDSBridge(world=world, robot=g1)
    bridge.start()

    # Run sim loop
    try:
        while kit.is_running():
            world.step(render=True)
            bridge.tick()
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
    finally:
        bridge.stop()
        kit.close()


def _default_g1_usd() -> str:
    """Default path to the bundled G1 USD."""
    here = Path(__file__).parent.parent / "assets" / "robots" / "g1.usd"
    return str(here)


def _download_g1_usd() -> str:
    """Fetch the official Unitree G1 USD model."""
    import urllib.request
    # The official G1 USD is shipped with Isaac Sim extensions:
    #   isaacsim/extscache/isaacsim.robot.assets/data/Robots/Unitree/G1/g1.usd
    # If not found, user must copy it manually.
    isaac_path = os.environ.get("ISAAC_ASSETS_PATH", "")
    candidates = [
        f"{isaac_path}/Robots/Unitree/G1/g1.usd",
        "/isaac-sim/extscache/isaacsim.robot.assets/data/Robots/Unitree/G1/g1.usd",
        "/opt/nvidia/isaac-sim/exts/isaacsim.robot.assets/Robots/Unitree/G1/g1.usd",
    ]
    for c in candidates:
        if Path(c).exists():
            return c

    raise FileNotFoundError(
        "G1 USD not found. Options:\n"
        "  1. Set ISAAC_ASSETS_PATH to your Isaac Sim assets dir\n"
        "  2. Download from: https://github.com/unitreerobotics/unitree_mujoco\n"
        "     and convert with Isaac Sim's URDF importer\n"
        "  3. Place at: neon_sim/assets/robots/g1.usd"
    )


if __name__ == "__main__":
    main()
