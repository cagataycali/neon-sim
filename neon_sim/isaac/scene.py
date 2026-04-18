"""Isaac Sim: G1 in Cagatay's lab + DDS Sport Server + live H.264 stream."""
from __future__ import annotations

import argparse
import atexit
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=9999)
ap.add_argument("--width", type=int, default=1280)
ap.add_argument("--height", type=int, default=720)
ap.add_argument("--fps", type=int, default=15)
ap.add_argument("--bitrate", type=int, default=4000)
ap.add_argument("--room", default=str(Path.home() / "neon-workspace/neon-sim/assets/rooms/cagatay_lab.usdz"))
ap.add_argument("--g1-mjcf", default=str(Path.home() / "unitree_mujoco/unitree_robots/g1/g1_29dof.xml"))
ap.add_argument("--dds-iface", default=os.getenv("G1_NETWORK_INTERFACE", "lo"))
ap.add_argument("--duration", type=float, default=0)
ap.add_argument("--skip-room", action="store_true", help="Skip loading USDZ room")
ap.add_argument("--skip-g1", action="store_true", help="Skip loading G1 MJCF")
args = ap.parse_args()


from isaacsim import SimulationApp
kit = SimulationApp({
    "width": args.width,
    "height": args.height,
    "headless": True,
    "renderer": "RaytracedLighting",
})

import numpy as np
print("[isaac-g1] numpy:", np.__version__, flush=True)

from isaacsim.core.api import World
from isaacsim.sensors.camera import Camera
import omni.usd
import omni.kit.commands
from isaacsim.asset.importer.mjcf import _mjcf

# DDS imports (after Isaac)
try:
    from unitree_sdk2py.core.channel import (
        ChannelFactoryInitialize, ChannelSubscriber, ChannelPublisher,
    )
    from unitree_sdk2py.idl.unitree_api.msg.dds_ import Request_ as DDSRequest
    from unitree_sdk2py.idl.unitree_api.msg.dds_ import Response_ as DDSResponse
    from unitree_sdk2py.g1.loco.g1_loco_api import (
        ROBOT_API_ID_LOCO_SET_FSM_ID,
        ROBOT_API_ID_LOCO_SET_VELOCITY,
        ROBOT_API_ID_LOCO_SET_STAND_HEIGHT,
        ROBOT_API_ID_LOCO_SET_BALANCE_MODE,
    )
    DDS_AVAILABLE = True
except ImportError as e:
    print(f"[isaac-g1] ⚠️  DDS import failed ({e}); render-only mode")
    DDS_AVAILABLE = False


print("[isaac-g1] ═══ SimulationApp ready ═══", flush=True)

world = World(stage_units_in_meters=1.0)
world.scene.add_default_ground_plane()


# --- Load room USDZ
if not args.skip_room and Path(args.room).exists():
    print(f"[isaac-g1] Loading room: {args.room}", flush=True)
    stage = omni.usd.get_context().get_stage()
    room_prim = stage.DefinePrim("/World/Room", "Xform")
    room_prim.GetReferences().AddReference(args.room)
    from pxr import Gf, UsdGeom
    rx = UsdGeom.Xformable(room_prim)
    rx.ClearXformOpOrder()
    rx.AddTranslateOp().Set(Gf.Vec3d(0, 0, 0))
    print("[isaac-g1] ✓ Room referenced", flush=True)
else:
    if args.skip_room:
        print("[isaac-g1] Skipping room", flush=True)
    else:
        print(f"[isaac-g1] ⚠️  Room not found: {args.room}", flush=True)


# --- Import G1 via the supported command (not raw interface call)
g1_loaded = False
if not args.skip_g1 and Path(args.g1_mjcf).exists():
    print(f"[isaac-g1] Importing G1 MJCF: {args.g1_mjcf}", flush=True)
    try:
        # Configure import options via the command
        status, import_config = omni.kit.commands.execute("MJCFCreateImportConfig")
        # These fields come from the real ImportConfig on this version
        try: import_config.fix_base = False
        except AttributeError: pass
        try: import_config.self_collision = False
        except AttributeError: pass
        try: import_config.import_inertia_tensor = True
        except AttributeError: pass
        try: import_config.distance_scale = 1.0
        except AttributeError: pass
        try: import_config.make_default_prim = False
        except AttributeError: pass

        status, _ = omni.kit.commands.execute(
            "MJCFCreateAsset",
            mjcf_path=args.g1_mjcf,
            import_config=import_config,
            prim_path="/World/G1",
            dest_path="",
        )
        print(f"[isaac-g1] ✓ G1 import command returned status={status}", flush=True)
        g1_loaded = True
    except Exception as e:
        print(f"[isaac-g1] ⚠️  MJCF import failed: {type(e).__name__}: {e}", flush=True)
        import traceback; traceback.print_exc()
else:
    print("[isaac-g1] Skipping G1 import", flush=True)


# --- Camera
print("[isaac-g1] Creating camera...", flush=True)
cam = Camera(
    prim_path="/World/Camera",
    position=np.array([3.0, 3.0, 2.0]),
    resolution=(args.width, args.height),
)

world.reset()
cam.initialize()
cam.set_world_pose(
    position=np.array([3.0, 3.0, 2.0]),
    orientation=np.array([0.6532815, -0.2705981, -0.2705981, 0.6532815]),
)
print("[isaac-g1] ✓ Camera ready", flush=True)


# ═══════ DDS Sport Server ═══════
cmd_state = {
    "vx": 0.0, "vy": 0.0, "vyaw": 0.0,
    "vel_until": 0.0,
    "fsm_id": 200,
    "stand_height": 0.75,
    "lock": threading.Lock(),
    "count": 0,
}

def handle_sport_request(req):
    try:
        api_id = req.header.identity.api_id
        params = req.parameter

        with cmd_state["lock"]:
            cmd_state["count"] += 1
            label = f"[#{cmd_state['count']}]"

            if api_id == ROBOT_API_ID_LOCO_SET_VELOCITY:
                p = json.loads(params) if params else {}
                cmd_state["vx"] = float(p.get("x", 0))
                cmd_state["vy"] = float(p.get("y", 0))
                cmd_state["vyaw"] = float(p.get("z", 0))
                duration = float(p.get("duration", 1.0))
                cmd_state["vel_until"] = time.time() + duration
                print(f"[isaac-g1] {label} ⮕ SetVelocity vx={cmd_state['vx']:.2f} vy={cmd_state['vy']:.2f} vyaw={cmd_state['vyaw']:.2f} for {duration}s", flush=True)

            elif api_id == ROBOT_API_ID_LOCO_SET_FSM_ID:
                p = json.loads(params) if params else {}
                cmd_state["fsm_id"] = int(p.get("data", 200))
                cmd_state["vx"] = cmd_state["vy"] = cmd_state["vyaw"] = 0.0
                print(f"[isaac-g1] {label} ⮕ SetFsmId {cmd_state['fsm_id']}", flush=True)

            elif api_id == ROBOT_API_ID_LOCO_SET_STAND_HEIGHT:
                p = json.loads(params) if params else {}
                raw = float(p.get("data", 0))
                cmd_state["stand_height"] = 0.85 if raw > 1_000_000 else 0.65
                print(f"[isaac-g1] {label} ⮕ StandHeight→{cmd_state['stand_height']:.2f}m", flush=True)

            else:
                print(f"[isaac-g1] {label} ⮕ api_id={api_id}", flush=True)

        resp = DDSResponse()
        resp.header.identity.id = req.header.identity.id
        resp.header.identity.api_id = api_id
        resp.header.status.code = 0
        resp.data = ""
        sport_pub.Write(resp)
    except Exception as e:
        print(f"[isaac-g1] request handler error: {type(e).__name__}: {e}", flush=True)


if DDS_AVAILABLE:
    try:
        ChannelFactoryInitialize(0, args.dds_iface)
        sport_sub = ChannelSubscriber("rt/api/sport/request", DDSRequest)
        sport_sub.Init(handle_sport_request, 10)
        sport_pub = ChannelPublisher("rt/api/sport/response", DDSResponse)
        sport_pub.Init()
        print(f"[isaac-g1] ✓ DDS Sport Service on iface={args.dds_iface}", flush=True)
    except Exception as e:
        print(f"[isaac-g1] ⚠️  DDS init failed: {e}", flush=True)
        DDS_AVAILABLE = False


# ═══════ GStreamer sink ═══════
gst_cmd = [
    "gst-launch-1.0", "-q",
    "fdsrc", "fd=0",
    "!", "videoparse",
        f"width={args.width}", f"height={args.height}",
        "format=rgba", f"framerate={args.fps}/1",
    "!", "videoconvert",
    "!", "x264enc", f"bitrate={args.bitrate}",
        "speed-preset=ultrafast", "tune=zerolatency", "key-int-max=30",
    "!", "h264parse", "config-interval=1",
    "!", "mpegtsmux",
    "!", "tcpserversink", "host=0.0.0.0", f"port={args.port}", "sync=false",
]
gst = subprocess.Popen(gst_cmd, stdin=subprocess.PIPE, stdout=sys.stderr, stderr=sys.stderr)
print(f"[isaac-g1] ▶ Stream: tcp://0.0.0.0:{args.port}", flush=True)


def cleanup(*_):
    try:
        if gst.stdin: gst.stdin.close()
    except: pass
    try:
        gst.terminate(); gst.wait(timeout=3)
    except: gst.kill()

atexit.register(cleanup)
signal.signal(signal.SIGINT, lambda *_: (cleanup(), sys.exit(0)))
signal.signal(signal.SIGTERM, lambda *_: (cleanup(), sys.exit(0)))


print("[isaac-g1] === Main loop starting ===", flush=True)
start = time.time()
frames = 0
forever = (args.duration == 0)

try:
    while kit._app.is_running():
        if not forever and (time.time() - start) > args.duration:
            break

        with cmd_state["lock"]:
            now = time.time()
            if now > cmd_state["vel_until"]:
                cmd_state["vx"] = cmd_state["vy"] = cmd_state["vyaw"] = 0.0
            vx, vy, vyaw = cmd_state["vx"], cmd_state["vy"], cmd_state["vyaw"]

        world.step(render=True)
        rgba = cam.get_rgba()
        if rgba is None or rgba.size == 0:
            continue
        if rgba.shape != (args.height, args.width, 4):
            continue

        try:
            gst.stdin.write(rgba.tobytes())
            gst.stdin.flush()
            frames += 1
            if frames % (args.fps * 2) == 0:
                elapsed = time.time() - start
                cmd_info = f"cmd(vx={vx:.2f} vy={vy:.2f} vyaw={vyaw:.2f})" if abs(vx) + abs(vy) + abs(vyaw) > 0.01 else ""
                print(f"[isaac-g1]  frames={frames} fps={frames/elapsed:.1f} reqs={cmd_state['count']} {cmd_info}", flush=True)
        except BrokenPipeError:
            break

except KeyboardInterrupt:
    pass

print(f"[isaac-g1] Done. {frames} frames, {cmd_state['count']} DDS requests", flush=True)
cleanup()
kit.close()
