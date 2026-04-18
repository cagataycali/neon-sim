"""MuJoCo scene loader — runs on Mac (no GPU needed).

Loads the Unitree G1 MJCF from `unitree_mujoco` and injects a Polycam
scanned room as a decoration mesh. Shares DDS bridge with Isaac backend.

Usage:
    python3 -m neon_sim.mujoco.stage --room assets/rooms/my_room.obj

If --room is a USDZ, we'll auto-convert via scripts/usdz_to_obj.py.

Key trick: the composite scene XML is written into the unitree_mujoco
g1 directory so that the G1's relative paths (to STL mesh files) keep
resolving.
"""
from __future__ import annotations
import argparse
import logging
import os
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

try:
    import mujoco
    import mujoco.viewer
except ImportError:
    print("❌ MuJoCo not installed. Run: pip install mujoco", file=sys.stderr)
    sys.exit(1)


# G1 MJCF candidate paths
G1_SCENE_PATHS = {
    "29": [
        Path.home() / "unitree_mujoco/unitree_robots/g1/scene_29dof.xml",
        Path("/opt/unitree_mujoco/unitree_robots/g1/scene_29dof.xml"),
    ],
    "23": [
        Path.home() / "unitree_mujoco/unitree_robots/g1/scene_23dof.xml",
        Path("/opt/unitree_mujoco/unitree_robots/g1/scene_23dof.xml"),
    ],
}


def find_g1_scene(dof: str = "29") -> Path:
    for p in G1_SCENE_PATHS[dof]:
        if p.exists():
            return p
    raise FileNotFoundError(
        f"G1 {dof}-DoF scene not found. Install unitree_mujoco:\n"
        "  git clone https://github.com/unitreerobotics/unitree_mujoco ~/unitree_mujoco"
    )


def ensure_obj(room_input: Path) -> Path:
    """If input is USDZ, convert to OBJ. Otherwise pass through."""
    if room_input.suffix.lower() == ".obj":
        return room_input

    if room_input.suffix.lower() == ".usdz":
        obj_out = room_input.with_suffix(".obj")
        if obj_out.exists():
            log.info(f"Using existing OBJ: {obj_out}")
            return obj_out

        log.info(f"Converting USDZ → OBJ: {room_input}")
        converter = Path(__file__).parent.parent.parent / "scripts" / "usdz_to_obj.py"
        result = subprocess.run(
            [sys.executable, str(converter), str(room_input), "--out", str(obj_out)],
            check=True, capture_output=True, text=True,
        )
        log.info(result.stdout)
        return obj_out

    raise ValueError(f"Unsupported room format: {room_input.suffix}")


def build_composite_scene(
    g1_scene: Path,
    room_obj: Path,
    room_pos: tuple = (0.0, 0.0, -0.5),
    room_euler_rad: tuple = (1.5708, 0.0, 0.0),  # Y-up → Z-up
    collide: bool = False,
) -> Path:
    """Build a scene XML that combines G1 + the room mesh.

    Writes the composite INTO the G1 directory so all relative paths
    (to STL meshes, texture files) continue to resolve.

    Args:
        collide: If True, room participates in physics. Start with False
                 so the robot has a stable floor to land on first.
    """
    g1_dir = g1_scene.parent

    tree = ET.parse(str(g1_scene))
    root = tree.getroot()

    # Register room mesh
    asset = root.find("asset")
    mesh = ET.SubElement(asset, "mesh")
    mesh.set("name", "neon_room")
    mesh.set("file", str(room_obj.resolve()))

    # Add room body
    worldbody = root.find("worldbody")
    body = ET.SubElement(worldbody, "body")
    body.set("name", "neon_room_body")
    body.set("pos", f"{room_pos[0]} {room_pos[1]} {room_pos[2]}")
    body.set("euler", f"{room_euler_rad[0]} {room_euler_rad[1]} {room_euler_rad[2]}")
    geom = ET.SubElement(body, "geom")
    geom.set("name", "neon_room_geom")
    geom.set("type", "mesh")
    geom.set("mesh", "neon_room")
    geom.set("contype", "1" if collide else "0")
    geom.set("conaffinity", "1" if collide else "0")
    geom.set("rgba", "0.85 0.75 0.65 0.6")

    out = g1_dir / "neon_sim_composite.xml"
    tree.write(str(out))
    return out


def make_robot_adapter(model: mujoco.MjModel, data: mujoco.MjData):
    """Create an adapter making MuJoCo look like an Isaac Articulation."""
    class MjRobotAdapter:
        def get_joint_positions(self):
            # Skip the 7-dof free joint (base pos + quat); joints start at index 7
            return [float(data.qpos[i]) for i in range(7, model.nq)]

        def get_joint_velocities(self):
            return [float(data.qvel[i]) for i in range(6, model.nv)]

        def get_world_pose(self):
            return (
                tuple(float(x) for x in data.qpos[:3]),
                tuple(float(x) for x in data.qpos[3:7]),
            )

    return MjRobotAdapter()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--room", required=True, help="Path to room (.obj or .usdz)")
    ap.add_argument("--dof", choices=["23", "29"], default="29")
    ap.add_argument("--headless", action="store_true",
                    help="Run without GUI (useful for CI / headless boxes)")
    ap.add_argument("--duration", type=float, default=0,
                    help="If >0, run for N sim seconds then exit (useful for tests)")
    ap.add_argument("--no-bridge", action="store_true",
                    help="Skip DDS bridge setup (for offline testing)")
    ap.add_argument("--collide", action="store_true",
                    help="Enable room/robot collision (off by default for stability)")
    args = ap.parse_args()

    room_input = Path(args.room).resolve()
    if not room_input.exists():
        sys.exit(f"❌ Room file not found: {room_input}")

    log.info(f"🏠 Room: {room_input}")
    room_obj = ensure_obj(room_input)
    log.info(f"   OBJ: {room_obj}")

    g1_scene = find_g1_scene(args.dof)
    log.info(f"🤖 G1 {args.dof}-DoF: {g1_scene}")

    composite = build_composite_scene(g1_scene, room_obj, collide=args.collide)
    log.info(f"🔀 Composite: {composite}")

    model = mujoco.MjModel.from_xml_path(str(composite))
    data = mujoco.MjData(model)
    log.info(
        f"   {model.nbody} bodies, {model.nu} actuators, "
        f"{model.ngeom} geoms, {model.nmesh} meshes"
    )

    # DDS bridge (optional)
    bridge = None
    if not args.no_bridge:
        try:
            from neon_sim.bridge.dds_bridge import DDSBridge
            robot = make_robot_adapter(model, data)
            bridge = DDSBridge(
                world=None,
                robot=robot,
                network_interface=os.getenv("G1_NETWORK_INTERFACE", "lo0"),
            )
            bridge.start()
        except Exception as e:
            log.warning(f"DDS bridge unavailable: {e} — continuing without")

    # Run the simulation
    if args.duration > 0:
        # Time-limited headless
        log.info(f"▶️  Running {args.duration}s headless...")
        start = time.time()
        steps = int(args.duration / model.opt.timestep)
        for i in range(steps):
            mujoco.mj_step(model, data)
            if bridge:
                bridge.tick()
            if i % 5000 == 0:
                log.info(f"   step {i}/{steps}, sim time {data.time:.2f}s")
        log.info(f"   done: {data.time:.2f}s simulated in {time.time()-start:.2f}s real")
    elif args.headless:
        # Infinite headless
        log.info("▶️  Running headless (Ctrl+C to stop)")
        try:
            while True:
                mujoco.mj_step(model, data)
                if bridge:
                    bridge.tick()
        except KeyboardInterrupt:
            log.info("interrupted")
    else:
        # Interactive viewer
        log.info("▶️  Launching interactive viewer (close window to exit)")
        with mujoco.viewer.launch_passive(model, data) as viewer:
            # Initial camera
            viewer.cam.distance = 4.0
            viewer.cam.elevation = -15

            while viewer.is_running():
                mujoco.mj_step(model, data)
                if bridge:
                    bridge.tick()
                viewer.sync()

    if bridge:
        bridge.stop()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    main()
