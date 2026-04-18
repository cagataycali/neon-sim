"""Isaac Sim: G1 (pre-built USD) in Cagatay's lab + DDS Sport Server + live stream."""
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
ap.add_argument("--g1-usd", default=str(Path.home() / ".cache/newton/newton-assets_unitree_g1_308a72cd/unitree_g1/usd/g1_isaac.usd"))
ap.add_argument("--dds-iface", default=os.getenv("G1_NETWORK_INTERFACE", "lo"))
ap.add_argument("--duration", type=float, default=0)
ap.add_argument("--skip-room", action="store_true")
ap.add_argument("--skip-g1", action="store_true")
args = ap.parse_args()


from isaacsim import SimulationApp
kit = SimulationApp({
    "width": args.width, "height": args.height,
    "headless": True, "renderer": "RaytracedLighting",
})

import numpy as np
from isaacsim.core.api import World
from isaacsim.sensors.camera import Camera
import omni.usd
from pxr import Gf, UsdGeom, Sdf

print(f"[isaac-g1] numpy={np.__version__}", flush=True)

# DDS
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
    )
    DDS_AVAILABLE = True
except ImportError as e:
    print(f"[isaac-g1] DDS import failed: {e}", flush=True)
    DDS_AVAILABLE = False


print("[isaac-g1] ═══ SimulationApp ready ═══", flush=True)
world = World(stage_units_in_meters=1.0)
world.scene.add_default_ground_plane()
stage = omni.usd.get_context().get_stage()


# --- Room USDZ as reference
if not args.skip_room and Path(args.room).exists():
    print(f"[isaac-g1] Loading room: {args.room}", flush=True)
    prim = stage.DefinePrim("/World/Room", "Xform")
    prim.GetReferences().AddReference(args.room)
    rx = UsdGeom.Xformable(prim)
    rx.ClearXformOpOrder()
    rx.AddTranslateOp().Set(Gf.Vec3d(0, 0, 0))
    print("[isaac-g1] ✓ Room ref added", flush=True)

# --- G1 USD as reference (not MJCF — this is the robust path)
G1_PRIM = "/World/G1"
if not args.skip_g1 and Path(args.g1_usd).exists():
    print(f"[isaac-g1] Referencing pre-built G1 USD: {args.g1_usd}", flush=True)
    try:
        g1 = stage.DefinePrim(G1_PRIM, "Xform")
        g1.GetReferences().AddReference(args.g1_usd)
        # Lift robot 1m so feet aren't inside ground
        gx = UsdGeom.Xformable(g1)
        gx.ClearXformOpOrder()
        gx.AddTranslateOp().Set(Gf.Vec3d(0, 0, 1.0))
        print("[isaac-g1] ✓ G1 USD referenced @ /World/G1, z=1m", flush=True)
    except Exception as e:
        print(f"[isaac-g1] ⚠️  G1 USD ref failed: {e}", flush=True)
elif not args.skip_g1:
    print(f"[isaac-g1] ⚠️  G1 USD not found: {args.g1_usd}", flush=True)
else:
    print("[isaac-g1] Skipping G1", flush=True)


# --- Camera
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


# --- Try to get the G1 as an articulation (for velocity control)
g1_art = None
try:
    from isaacsim.core.prims import SingleArticulation
    g1_art = SingleArticulation(prim_path=G1_PRIM, name="g1")
    g1_art.initialize()
    print(f"[isaac-g1] ✓ G1 articulation: {g1_art.num_dof} DOF", flush=True)
except Exception as e:
    print(f"[isaac-g1] ⚠️  G1 articulation init: {e}  (will drive root xform)", flush=True)


# --- DDS Sport Server
cmd_state = {
    "vx": 0.0, "vy": 0.0, "vyaw": 0.0,
    "vel_until": 0.0, "fsm_id": 200, "stand_height": 0.75,
    "lock": threading.Lock(), "count": 0,
}

def handle_sport_request(req):
    try:
        api_id = req.header.identity.api_id
        params = req.parameter
        with cmd_state["lock"]:
            cmd_state["count"] += 1
            p = json.loads(params) if params else {}
            if api_id == ROBOT_API_ID_LOCO_SET_VELOCITY:
                vel = p.get("velocity", [0,0,0])
                cmd_state["vx"] = float(vel[0])
                cmd_state["vy"] = float(vel[1])
                cmd_state["vyaw"] = float(vel[2])
                dur = float(p.get("duration", 1.0))
                cmd_state["vel_until"] = time.time() + dur
                print(f"[isaac-g1] [#{cmd_state['count']}] SetVelocity vx={cmd_state['vx']:.2f} vy={cmd_state['vy']:.2f} vyaw={cmd_state['vyaw']:.2f} dur={dur}s", flush=True)
            elif api_id == ROBOT_API_ID_LOCO_SET_FSM_ID:
                cmd_state["fsm_id"] = int(p.get("data", 200))
                print(f"[isaac-g1] [#{cmd_state['count']}] SetFsmId {cmd_state['fsm_id']}", flush=True)
            elif api_id == ROBOT_API_ID_LOCO_SET_STAND_HEIGHT:
                raw = float(p.get("data", 0))
                cmd_state["stand_height"] = 0.85 if raw > 1_000_000 else 0.65
                print(f"[isaac-g1] [#{cmd_state['count']}] StandHeight {cmd_state['stand_height']:.2f}m", flush=True)
            else:
                print(f"[isaac-g1] [#{cmd_state['count']}] api_id={api_id}", flush=True)
        resp = DDSResponse()
        resp.header.identity.id = req.header.identity.id
        resp.header.identity.api_id = api_id
        resp.header.status.code = 0
        resp.data = ""
        sport_pub.Write(resp)
    except Exception as e:
        print(f"[isaac-g1] handler error: {e}", flush=True)

if DDS_AVAILABLE:
    try:
        ChannelFactoryInitialize(0, args.dds_iface)
        sport_sub = ChannelSubscriber("rt/api/sport/request", DDSRequest)
        sport_sub.Init(handle_sport_request, 10)
        sport_pub = ChannelPublisher("rt/api/sport/response", DDSResponse)
        sport_pub.Init()
        print(f"[isaac-g1] ✓ DDS Sport Service on {args.dds_iface}", flush=True)
    except Exception as e:
        print(f"[isaac-g1] DDS init fail: {e}", flush=True)


# --- GStreamer sink
gst = subprocess.Popen([
    "gst-launch-1.0", "-q",
    "fdsrc", "fd=0",
    "!", "videoparse", f"width={args.width}", f"height={args.height}",
         "format=rgba", f"framerate={args.fps}/1",
    "!", "videoconvert",
    "!", "x264enc", f"bitrate={args.bitrate}",
         "speed-preset=ultrafast", "tune=zerolatency", "key-int-max=15",
    "!", "h264parse", "config-interval=-1",
    "!", "mpegtsmux",
    "!", "tcpserversink", "host=0.0.0.0", f"port={args.port}", "sync=false",
], stdin=subprocess.PIPE, stdout=sys.stderr, stderr=sys.stderr)
print(f"[isaac-g1] ▶ Stream tcp://0.0.0.0:{args.port}", flush=True)

def cleanup(*_):
    try:
        if gst.stdin: gst.stdin.close()
    except: pass
    try: gst.terminate(); gst.wait(timeout=3)
    except: gst.kill()

atexit.register(cleanup)
signal.signal(signal.SIGINT, lambda *_: (cleanup(), sys.exit(0)))
signal.signal(signal.SIGTERM, lambda *_: (cleanup(), sys.exit(0)))


# --- Main loop: apply velocity → integrate G1 base position
print("[isaac-g1] === Main loop starting ===", flush=True)
start = time.time()
frames = 0
forever = (args.duration == 0)

# Integrated pose for visual motion (simplified base-only kinematic motion)
g1_x, g1_y, g1_yaw = 0.0, 0.0, 0.0
g1_z = 1.0  # stand height
last_step = time.time()

# Resolve G1 root prim for xform writes
g1_prim_for_xform = stage.GetPrimAtPath(G1_PRIM) if not args.skip_g1 else None
g1_xformable = UsdGeom.Xformable(g1_prim_for_xform) if g1_prim_for_xform and g1_prim_for_xform.IsValid() else None

try:
    while kit._app.is_running():
        if not forever and (time.time() - start) > args.duration:
            break

        # Read current command
        with cmd_state["lock"]:
            now = time.time()
            if now > cmd_state["vel_until"]:
                cmd_state["vx"] = cmd_state["vy"] = cmd_state["vyaw"] = 0.0
            vx, vy, vyaw = cmd_state["vx"], cmd_state["vy"], cmd_state["vyaw"]
            sh = cmd_state["stand_height"]

        # Integrate base pose (kinematic — no real walking controller yet,
        # but you see the robot move in world frame)
        dt = now - last_step
        last_step = now
        if dt > 0.5: dt = 0.5  # cap on first step
        import math
        cos_y, sin_y = math.cos(g1_yaw), math.sin(g1_yaw)
        g1_x += (vx * cos_y - vy * sin_y) * dt
        g1_y += (vx * sin_y + vy * cos_y) * dt
        g1_yaw += vyaw * dt
        g1_z = sh  # stand height updates height

        # Apply to the G1 root xform
        if g1_xformable is not None:
            try:
                g1_xformable.ClearXformOpOrder()
                g1_xformable.AddTranslateOp().Set(Gf.Vec3d(g1_x, g1_y, g1_z))
                g1_xformable.AddRotateZOp().Set(math.degrees(g1_yaw))
            except Exception:
                pass

        world.step(render=True)
        rgba = cam.get_rgba()
        if rgba is None or rgba.size == 0 or rgba.shape != (args.height, args.width, 4):
            continue

        try:
            gst.stdin.write(rgba.tobytes())
            gst.stdin.flush()
            frames += 1
            if frames % (args.fps * 2) == 0:
                elapsed = time.time() - start
                print(f"[isaac-g1] frames={frames} fps={frames/elapsed:.1f} reqs={cmd_state['count']} pose=({g1_x:.2f},{g1_y:.2f},{math.degrees(g1_yaw):.0f}°)", flush=True)
        except BrokenPipeError:
            break

except KeyboardInterrupt:
    pass

print(f"[isaac-g1] Done. {frames} frames, {cmd_state['count']} reqs", flush=True)
cleanup(); kit.close()
