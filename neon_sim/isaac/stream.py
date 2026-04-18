"""Isaac Sim headless + GStreamer live H.264 stream (aarch64-compatible).

Why this exists: `omni.kit.livestream.webrtc` requires proprietary NVIDIA
native binaries that are ONLY published for x86_64 and Windows. On Jetson
(aarch64) the dependency solver fails with:

    omni.kit.livestream.webrtc = can't be satisfied.
    Available versions:
      - lx64.d.cp311, lx64.r.cp311 (Linux x86_64)
      - wx64.d.cp311, wx64.r.cp311 (Windows x86_64)
    [no la64 builds]

Solution: bypass Kit livestream. Run `SimulationApp(headless=True)` via EGL,
grab frames with `Camera.get_rgba()`, pipe raw bytes into a GStreamer
subprocess that encodes H.264 and serves it over TCP/RTSP.

Connection (from Mac / any client):
    ffplay tcp://<thor-ip>:9999
    open -a VLC tcp://<thor-ip>:9999

Validated on:
  NVIDIA Thor aarch64, L4T R38.2.2, Isaac Sim 5.1, GStreamer 1.24.

Usage:
    cd ~/isaacsim/_build/linux-aarch64/release
    ./python.sh /path/to/stream.py  [--port 9999 --fps 15 --width 1280 --height 720]
"""
from __future__ import annotations

import argparse
import atexit
import signal
import subprocess
import sys
import time
from pathlib import Path

# Must import SimulationApp BEFORE anything else that touches omni.*
# That's why we parse args here but don't import heavy stuff yet.
def _parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9999)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--fps", type=int, default=15)
    ap.add_argument("--bitrate", type=int, default=4000, help="kbps")
    ap.add_argument("--duration", type=float, default=600, help="seconds; 0 = forever")
    ap.add_argument("--renderer", default="RaytracedLighting",
                    choices=["RaytracedLighting", "PathTracing"])
    return ap.parse_args()

def main():
    args = _parse_args()

    from isaacsim import SimulationApp

    kit = SimulationApp({
        "width": args.width,
        "height": args.height,
        "headless": True,
        "renderer": args.renderer,
    })

    # Heavy Isaac imports AFTER SimulationApp() per Isaac convention
    import numpy as np
    from isaacsim.core.api import World
    from isaacsim.core.api.objects import DynamicCuboid
    from isaacsim.sensors.camera import Camera

    print(f"[isaac-stream] SimulationApp ready. Spawning GStreamer sink on port {args.port}",
          flush=True)

    # GStreamer pipeline: raw RGBA stdin → x264enc → mpegts over TCP
    gst_cmd = [
        "gst-launch-1.0", "-q",
        "fdsrc", "fd=0",
        "!", "videoparse",
            f"width={args.width}", f"height={args.height}",
            "format=rgba", f"framerate={args.fps}/1",
        "!", "videoconvert",
        "!", "x264enc",
            f"bitrate={args.bitrate}",
            "speed-preset=ultrafast",
            "tune=zerolatency",
            "key-int-max=30",
        "!", "h264parse", "config-interval=1",
        "!", "mpegtsmux",
        "!", "tcpserversink",
            "host=0.0.0.0", f"port={args.port}", "sync=false",
    ]
    gst = subprocess.Popen(
        gst_cmd,
        stdin=subprocess.PIPE,
        stdout=sys.stderr,
        stderr=sys.stderr,
    )

    def cleanup(*_):
        try:
            if gst.stdin:
                gst.stdin.close()
        except Exception:
            pass
        try:
            gst.terminate()
            gst.wait(timeout=3)
        except Exception:
            gst.kill()

    atexit.register(cleanup)
    signal.signal(signal.SIGINT, lambda *_: (cleanup(), sys.exit(0)))
    signal.signal(signal.SIGTERM, lambda *_: (cleanup(), sys.exit(0)))

    # Basic scene (caller can replace with real G1 + room setup)
    print("[isaac-stream] Building default scene (cube + ground + camera)", flush=True)
    world = World(stage_units_in_meters=1.0)
    world.scene.add_default_ground_plane()

    DynamicCuboid(
        prim_path="/World/Cube",
        position=np.array([0.0, 0.0, 0.5]),
        scale=np.array([0.4, 0.4, 0.4]),
        color=np.array([1.0, 0.5, 0.0]),
    )

    cam = Camera(
        prim_path="/World/Camera",
        position=np.array([3.0, 3.0, 2.5]),
        resolution=(args.width, args.height),
    )
    world.reset()
    cam.initialize()
    cam.set_world_pose(
        position=np.array([3.0, 3.0, 2.5]),
        orientation=np.array([0.6532815, -0.2705981, -0.2705981, 0.6532815]),
    )

    print(f"[isaac-stream] ▶ Streaming at tcp://0.0.0.0:{args.port}", flush=True)
    print(f"[isaac-stream]   From client:  ffplay tcp://<this-host>:{args.port}", flush=True)

    start = time.time()
    frames = 0
    forever = (args.duration == 0)

    try:
        while kit._app.is_running():
            if not forever and (time.time() - start) > args.duration:
                break
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
                    effective = frames / elapsed if elapsed > 0 else 0
                    print(f"[isaac-stream]   frames={frames} elapsed={elapsed:.1f}s eff_fps={effective:.2f}",
                          flush=True)
            except BrokenPipeError:
                print("[isaac-stream] GStreamer pipe closed, exiting", flush=True)
                break
    except KeyboardInterrupt:
        pass

    print(f"[isaac-stream] Done. Sent {frames} frames in {time.time()-start:.1f}s.",
          flush=True)
    cleanup()
    kit.close()


if __name__ == "__main__":
    main()
