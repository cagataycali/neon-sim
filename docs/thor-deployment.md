# Deploying to Thor (aarch64 Jetson)

## What works on Thor

- ✅ MuJoCo simulation (same 27× realtime as Mac, ~12× on Thor)
- ✅ CycloneDDS bridge (same loopback DDS pattern)
- ✅ `unitree_sdk2_python` (already installed)
- ✅ Python 3.12 + all neon-sim deps except `usd-core`

## What doesn't work (known)

### ❌ Isaac Sim WebRTC streaming

**Status:** Isaac Sim 5.1 is source-built at `~/isaacsim/_build/linux-aarch64/release/`,
BUT `omni.kit.livestream.webrtc` has no aarch64 wheel on the NVIDIA extension
registry. Only available for `lx64` (x86_64 Linux) and `wx64` (Windows x64).

Log snippet:
```
[isaacsim.exp.full.streaming-5.1.0 -> omni.services.livestream.nvcf-7.2.0]
dependency: 'omni.kit.livestream.webrtc' = { version='^' } can't be satisfied.
Available versions:
 (none found)
 Platform incompatible packages:
	 - [omni.kit.livestream.webrtc-7.0.0+107.1.0.lx64.d.cp311]
	 - [omni.kit.livestream.webrtc-7.0.0+107.1.0.wx64.d.cp311]
	 (...)
```

### ❌ VNC + Isaac Sim (Vulkan)

TigerVNC runs on `:5901` but uses a software X server without GPU acceleration.
Isaac Sim needs Vulkan surfaces that VNC can't provide.

Log snippet:
```
[Error] [omni.kit.renderer.plugin] advanceCurrentFrame: backbuffers are not initialized!
[Error] [rtx.denoising.plugin] Failed to compile compute shader: rtx/nrd/PackForNRD.cs.hlsl
```

### ❌ No physical display

```
# cat /sys/class/drm/card*-HDMI*/status
disconnected
disconnected
```

## Working alternatives

### Option A: MuJoCo on Thor + RTSP streaming

MuJoCo's `mujoco.Renderer` produces frames we can pipe to `ffmpeg` → RTSP.
View in Safari / VLC on Mac.

Setup (TODO):
```bash
# Thor side
ffmpeg -f rawvideo -pixel_format rgb24 -video_size 1920x1080 -i - \
       -c:v h264_nvmpi -preset llhp -tune zerolatency \
       -f rtsp rtsp://0.0.0.0:8554/live &

# Mac side (view)
open rtsp://192.168.1.151:8554/live
```

### Option B: TurboVNC + VirtualGL (GPU-accelerated VNC)

Needs `sudo apt install` (requires interactive password right now).
TurboVNC + VirtualGL give Isaac Sim a GPU-backed X server via VNC.

```bash
sudo apt install -y virtualgl turbovnc
sudo /opt/VirtualGL/bin/vglserver_config  # GPU grant
/opt/TurboVNC/bin/vncserver :2 -geometry 1920x1080 -depth 24
vglrun -d :0 ~/isaacsim/_build/linux-aarch64/release/isaac-sim.sh
```

### Option C: Isaac Sim headless → MP4

Use `SimulationApp(headless=True)` + `isaacsim.sensors.camera.Camera` + Replicator
annotator → write PNG sequence, encode to MP4 with ffmpeg, watch after.

Good for **demos**, not **live observation**.

### Option D: Sim on Mac, runtime on Thor (what we actually did tonight)

- Mac: `mjpython -m neon_sim.mujoco.stage --room assets/rooms/cagatay_lab.obj`
- Thor: `python -m neon` (neon-runtime agent + Telegram listener)
- Both bind to `lo0`/`lo` — they don't actually see each other, but:
  - Mac demos the SIM LOOP (user → Mac MuJoCo → DDS commands)
  - Thor demos the AGENT LOOP (Telegram → neon → G1 DDS → MCU)
  - Future: bridge them via zenoh or a DDS router

## Thor software inventory

| Component | Status | Location |
|---|---|---|
| Isaac Sim 5.1 (source build) | ✅ built | `~/isaacsim/_build/linux-aarch64/release/` |
| MuJoCo 3.7.0 | ✅ installed | `~/unitree-g1-test/.venv` |
| CycloneDDS 0.10.2 | ✅ installed | `/usr/local/lib/libddsc.so.0.10.2` |
| unitree_sdk2_python | ✅ installed | same venv |
| neon-sim (cloned) | ✅ | `~/neon-workspace/neon-sim` |
| neon-runtime (cloned) | ✅ | `~/neon-workspace/neon-runtime` |
| Polycam lab scan | ✅ on disk | `~/neon-workspace/neon-sim/assets/rooms/cagatay_lab.obj` |
| TigerVNC | ✅ running | port 5901 (no GPU) |
| xrdp | ✅ running | port 3389 |
| TurboVNC | ❌ not installed | needs apt (password) |
| VirtualGL | ❌ not installed | needs apt (password) |

## Commands validated

```bash
# MuJoCo headless, G1 + lab room, 2s sim
$VENV/bin/python -m neon_sim.mujoco.stage \
    --room assets/rooms/cagatay_lab.obj --duration 2 --no-bridge

# Runs in 0.16s on Thor (12× real-time, vs 27× on Mac M-series)
```
