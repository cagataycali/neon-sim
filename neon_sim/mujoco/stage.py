"""MuJoCo scene loader — runs on Mac (no GPU needed).

Uses `unitree_mujoco` G1 XML model + imports the Polycam room as a
static decoration mesh (OBJ converted from USDZ).

Entry point:
    python3 -m neon_sim.mujoco.stage --room assets/rooms/my_room.obj

MuJoCo's biggest limitation: it can't load USDZ directly. Polycam can
export OBJ as an alternative — use that, or run `convert_to_obj.py`.
"""
from __future__ import annotations
import argparse
import logging
import os
import sys
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

try:
    import mujoco
    import mujoco.viewer
except ImportError:
    print("❌ MuJoCo not installed. Run: pip install mujoco", file=sys.stderr)
    sys.exit(1)


# G1 MJCF path — from unitree_mujoco repo
G1_MJCF_PATHS = [
    Path.home() / "unitree_mujoco" / "unitree_robots" / "g1" / "scene_23dof.xml",
    Path.home() / "unitree_mujoco" / "unitree_robots" / "g1" / "scene_29dof.xml",
    # User-installed
    Path("/opt/unitree_mujoco/unitree_robots/g1/scene_29dof.xml"),
]


def _find_g1_mjcf() -> Path:
    for p in G1_MJCF_PATHS:
        if p.exists():
            return p
    raise FileNotFoundError(
        "G1 MJCF not found. Install unitree_mujoco:\n"
        "  git clone https://github.com/unitreerobotics/unitree_mujoco ~/unitree_mujoco"
    )


def build_scene_with_room(g1_mjcf: Path, room_obj: Path, out: Path):
    """Inject the room OBJ into a copy of the G1 MJCF scene."""
    import xml.etree.ElementTree as ET

    tree = ET.parse(str(g1_mjcf))
    root = tree.getroot()

    # Register the room as a mesh asset
    asset = root.find("asset")
    if asset is None:
        asset = ET.SubElement(root, "asset")

    mesh = ET.SubElement(asset, "mesh")
    mesh.set("name", "room")
    mesh.set("file", str(room_obj.resolve()))

    # Add as a static body (geom, not movable)
    worldbody = root.find("worldbody")
    body = ET.SubElement(worldbody, "body")
    body.set("name", "room")
    body.set("pos", "0 0 0")
    geom = ET.SubElement(body, "geom")
    geom.set("type", "mesh")
    geom.set("mesh", "room")
    geom.set("contype", "1")
    geom.set("conaffinity", "1")
    geom.set("rgba", "0.7 0.7 0.7 1")

    tree.write(str(out))
    log.info(f"Wrote composite scene: {out}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--room", required=True, help="Path to room (.obj)")
    ap.add_argument("--dof", choices=["23", "29"], default="29")
    ap.add_argument("--headless", action="store_true")
    args = ap.parse_args()

    room_path = Path(args.room).resolve()
    if not room_path.exists():
        sys.exit(f"❌ Room file not found: {room_path}")

    g1_mjcf = _find_g1_mjcf()
    log.info(f"G1 MJCF: {g1_mjcf}")

    # Build a composite scene XML in /tmp
    scene_path = Path("/tmp/neon_sim_scene.xml")
    build_scene_with_room(g1_mjcf, room_path, scene_path)

    # Load MuJoCo model
    model = mujoco.MjModel.from_xml_path(str(scene_path))
    data = mujoco.MjData(model)

    log.info(f"🏠 Scene loaded: {model.nbody} bodies, {model.nu} actuators")

    # Start DDS bridge in background (same bridge used by Isaac)
    from neon_sim.bridge.dds_bridge import DDSBridge

    # Adapter to make MuJoCo look like an Articulation
    class MjRobotAdapter:
        def __init__(self, model, data):
            self.model = model
            self.data = data

        def get_joint_positions(self):
            return list(self.data.qpos[:model.nu])

        def get_joint_velocities(self):
            return list(self.data.qvel[:model.nu])

        def get_world_pose(self):
            return (list(self.data.qpos[:3]), list(self.data.qpos[3:7]))

    robot = MjRobotAdapter(model, data)
    bridge = DDSBridge(world=None, robot=robot, network_interface=os.getenv("G1_NETWORK_INTERFACE", "lo"))

    try:
        bridge.start()
    except Exception as e:
        log.warning(f"DDS bridge startup failed: {e} — continuing without bridge")

    # Simulation loop
    if args.headless:
        log.info("▶️ Running headless")
        step_count = 0
        while True:
            mujoco.mj_step(model, data)
            bridge.tick()
            step_count += 1
            if step_count % 5000 == 0:
                log.info(f"  step {step_count}, sim time {data.time:.1f}s")
    else:
        log.info("▶️ Launching interactive viewer")
        with mujoco.viewer.launch_passive(model, data) as viewer:
            while viewer.is_running():
                mujoco.mj_step(model, data)
                bridge.tick()
                viewer.sync()

    bridge.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    main()
