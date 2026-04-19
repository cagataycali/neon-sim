"""MuJoCo scene loader — runs on Mac (no GPU needed).

Loads the Unitree G1 MJCF from `unitree_mujoco` and injects a Polycam
scanned room (converted via scripts/usd2mjcf_with_textures.py) with full
per-material textures.

Usage:
    python3 -m neon_sim.mujoco.stage --room assets/rooms/my_room.usdz

If --room is a USDZ, we auto-convert it via the usd2mjcf pipeline
(LightwheelAI/usd2mjcf + our texture-patch layer). If it's already an
MJCF XML produced by that pipeline, we use it directly.
"""
from __future__ import annotations
import argparse
import logging
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

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

REPO_ROOT = Path(__file__).parent.parent.parent
CONVERTER = REPO_ROOT / "scripts" / "usd2mjcf_with_textures.py"


def find_g1_scene(dof: str = "29") -> Path:
    for p in G1_SCENE_PATHS[dof]:
        if p.exists():
            return p
    raise FileNotFoundError(
        f"G1 {dof}-DoF scene not found. Install unitree_mujoco:\n"
        "  git clone https://github.com/unitreerobotics/unitree_mujoco ~/unitree_mujoco"
    )


def ensure_room_mjcf(room_input: Path) -> Path:
    """Resolve --room to a textured MJCF file.

    - If it's already an XML (assumed to be our converter's output), return as-is.
    - If it's a .usdz or .usd, run usd2mjcf_with_textures.py.
    """
    suffix = room_input.suffix.lower()
    if suffix == ".xml":
        return room_input

    if suffix not in (".usdz", ".usd"):
        raise ValueError(f"Unsupported room format: {suffix} (want .usdz/.usd/.xml)")

    out_dir = room_input.parent / f"{room_input.stem}_lightwheel"
    mjcf = out_dir / "MJCF" / f"{room_input.stem}.xml"

    if mjcf.exists():
        log.info(f"✓ Using cached MJCF: {mjcf}")
        return mjcf

    log.info(f"Converting USD → textured MJCF: {room_input} → {out_dir}")
    subprocess.run(
        [sys.executable, str(CONVERTER), str(room_input), "--out-dir", str(out_dir)],
        check=True,
    )
    if not mjcf.exists():
        raise RuntimeError(f"Converter did not produce expected file: {mjcf}")
    return mjcf


def build_composite_scene(
    g1_scene: Path,
    room_mjcf: Path,
    room_pos: tuple = (0.0, 0.0, -0.05),
    room_euler_rad: tuple = (1.5708, 0.0, 0.0),  # Y-up → Z-up
    collide: bool = False,
) -> Path:
    """Build a composite scene merging G1 + textured room MJCF.

    Writes the composite into the G1 directory so G1 relative mesh paths
    keep resolving. Rewrites the room's mesh/texture `file=` attributes to
    absolute paths so they resolve from the G1 directory too.
    """
    tree = ET.parse(str(g1_scene))
    root = tree.getroot()

    # Parse the room MJCF
    room_tree = ET.parse(str(room_mjcf))
    room_root = room_tree.getroot()
    room_dir = room_mjcf.parent

    # -- Merge <asset> (textures, materials, meshes) --
    asset = root.find("asset")
    if asset is None:
        asset = ET.SubElement(root, "asset")

    room_asset = room_root.find("asset")
    for child in list(room_asset):
        # Rewrite relative file paths to absolute (so they resolve from G1 dir)
        if "file" in child.attrib:
            f = child.attrib["file"]
            if not Path(f).is_absolute():
                child.set("file", str((room_dir / f).resolve()))
        # Namespace to avoid collisions with G1 assets
        if "name" in child.attrib:
            child.set("name", f"neon_room_{child.attrib['name']}")
        # Mesh/material cross-references inside <geom> need the same prefix —
        # handled below. For <material texture="..."> rewrite too:
        if child.tag == "material" and "texture" in child.attrib:
            child.set("texture", f"neon_room_{child.attrib['texture']}")
        asset.append(child)

    # -- Improve headlight for textured scans --
    visual = root.find("visual")
    if visual is None:
        visual = ET.SubElement(root, "visual")
    hl = visual.find("headlight")
    if hl is None:
        hl = ET.SubElement(visual, "headlight")
    hl.set("diffuse", "0.6 0.6 0.6")
    hl.set("ambient", "0.3 0.3 0.3")
    hl.set("specular", "0 0 0")

    # -- Inject room body into worldbody --
    worldbody = root.find("worldbody")
    room_body = ET.SubElement(worldbody, "body")
    room_body.set("name", "neon_room")
    room_body.set("pos", f"{room_pos[0]} {room_pos[1]} {room_pos[2]}")
    room_body.set("euler", f"{room_euler_rad[0]} {room_euler_rad[1]} {room_euler_rad[2]}")

    room_world = room_root.find("worldbody")
    if room_world is not None:
        for geom in room_world.iter("geom"):
            new_geom = ET.SubElement(room_body, "geom")
            for k, v in geom.attrib.items():
                if k == "class":
                    continue  # defaults don't propagate across merged scenes
                if k == "mesh":
                    new_geom.set(k, f"neon_room_{v}")
                elif k == "material":
                    new_geom.set(k, f"neon_room_{v}")
                else:
                    new_geom.set(k, v)
            # Bake in what class=visual would have set
            if "type" not in new_geom.attrib: new_geom.set("type", "mesh")
            if "group" not in new_geom.attrib: new_geom.set("group", "1")
            new_geom.set("contype", "1" if collide else "0")
            new_geom.set("conaffinity", "1" if collide else "0")

    # If no geoms found in worldbody, fall through (LightwheelAI sometimes puts
    # geoms directly under <worldbody>/<body>). Try one more level:
    if len(list(room_body)) == 0 and room_world is not None:
        for body in room_world.iter("body"):
            for geom in body.iter("geom"):
                new_geom = ET.SubElement(room_body, "geom")
                for k, v in geom.attrib.items():
                    if k == "class":
                        continue  # defaults don't propagate across merged scenes
                    if k == "mesh":
                        new_geom.set(k, f"neon_room_{v}")
                    elif k == "material":
                        new_geom.set(k, f"neon_room_{v}")
                    else:
                        new_geom.set(k, v)
                if "type" not in new_geom.attrib: new_geom.set("type", "mesh")
                if "group" not in new_geom.attrib: new_geom.set("group", "1")
                new_geom.set("contype", "1" if collide else "0")
                new_geom.set("conaffinity", "1" if collide else "0")

    out = g1_scene.parent / "neon_sim_composite.xml"
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
    ap.add_argument("--room", required=True, help="Path to room (.usdz / .usd / .xml)")
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
    room_mjcf = ensure_room_mjcf(room_input)
    log.info(f"   MJCF: {room_mjcf}")

    g1_scene = find_g1_scene(args.dof)
    log.info(f"🤖 G1 {args.dof}-DoF: {g1_scene}")

    composite = build_composite_scene(g1_scene, room_mjcf, collide=args.collide)
    log.info(f"🔀 Composite: {composite}")

    model = mujoco.MjModel.from_xml_path(str(composite))
    data = mujoco.MjData(model)
    log.info(
        f"   {model.nbody} bodies, {model.nu} actuators, "
        f"{model.ngeom} geoms, {model.nmesh} meshes, {model.ntex} textures"
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
        log.info("▶️  Running headless (Ctrl+C to stop)")
        try:
            while True:
                mujoco.mj_step(model, data)
                if bridge:
                    bridge.tick()
        except KeyboardInterrupt:
            log.info("interrupted")
    else:
        log.info("▶️  Launching interactive viewer (close window to exit)")
        with mujoco.viewer.launch_passive(model, data) as viewer:
            viewer.cam.distance = 4.5
            viewer.cam.elevation = -20
            viewer.cam.azimuth = 135
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
