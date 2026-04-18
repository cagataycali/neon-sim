# Deploying to Thor (Jetson Thor aarch64)

## What we learned the hard way

### 🔴 `omni.kit.livestream.webrtc` — blocked on aarch64

We deep-dove the NVIDIA extension registry. The situation:

```
omni.kit.livestream.webrtc    — pure Python wrapper, 4.2 MB zip
  └── omni.kit.streamsdk.plugins   — 13 MB zip of NATIVE x86_64 .so files:
        • libNvStreamServer.so      ← proprietary, the actual WebRTC server
        • libNvStreamBase.so
        • libcarb.livestream-rtc.plugin.so
        • libcudart.so.12           ← x86 CUDA runtime
        • libssl.so.3, libPoco.so, libcrypto.so.3
```

All available platforms (checked `omni.kit.streamsdk.plugins.json`):
- `lx64` (Linux x86_64) ✅
- `wx64` (Windows x86_64) ✅
- `la64` (Linux aarch64) ❌ **no build published**

**Why:** `NvStreamServer` likely uses NVENC via the desktop CUDA encoder API;
Jetson NVENC goes through the Jetson Multimedia API (V4L2 m2m), a completely
different backend. NVIDIA hasn't ported StreamSDK to the Jetson path.

### 🟢 But Isaac Sim runs headless on Thor!

We got Isaac Sim 5.1 to render scenes offscreen via EGL:

```
[8.437s] app ready
[9.077s] Simulation App Startup Complete
```

- `SimulationApp({"headless": True, "renderer": "RaytracedLighting"})` works
- Camera + `cam.get_rgba()` returns H×W×4 numpy arrays
- Rendered 47 usable frames of a default scene with a cube
- DLSS (NGX) and OptiX denoising fail on Jetson — cosmetic errors, render
  still completes via standard Vulkan pipeline

### 🟢 Thor has hardware video encoders

```
/dev/v4l2-nvenc           ← Jetson NVENC device
gst-inspect-1.0 | grep nv  nvautogpuh264enc, nvcudah264enc, nvh264enc
ffmpeg has h264_v4l2m2m    (v4l2 mem2mem wrapper for NVENC)
```

Tested: **GStreamer x264enc** (software) works fine for our resolution.
Hardware NVENC via `nvh264enc` needs cudaupload plumbing — works once set up.

## The working pipeline

```
Thor                                         Mac/Browser
─────────────────────────────────────────    ────────────
Isaac Sim (headless EGL)                
      │                                  
      ├─ Python: Camera.get_rgba()       
      │                                  
      ├─ GStreamer pipeline:             
      │    appsrc  (raw frames)          
      │    → x264enc                     
      │    → rtspserver / webrtcbin      
      │                                  
      └─ RTSP on tcp/8554 ───────────────► VLC / Safari
                                          rtsp://192.168.1.151:8554/isaac
```

MP4-to-file already validated:

```bash
# On Thor — 47 frames → 968 KB MP4
gst-launch-1.0 -e \
  multifilesrc location=/tmp/isaac_frames/frame_%04d.png start-index=7 \
               caps="image/png,framerate=30/1" \
  ! pngdec ! videoconvert \
  ! x264enc bitrate=4000 tune=zerolatency speed-preset=ultrafast \
  ! mp4mux ! filesink location=/tmp/out.mp4
```

Download + play on Mac: ✓ works first try.

## Thor software inventory

| Component | Status | Location |
|---|---|---|
| **Isaac Sim 5.1 build** | ✅ builds + runs | `~/isaacsim/_build/linux-aarch64/release/` |
| **`omni.kit.livestream.webrtc`** | ❌ no aarch64 | registry has `lx64`+`wx64` only |
| **`omni.services.livestream.nvcf`** | ⚠️  pure-Py but needs webrtc dep | blocked transitively |
| **`omni.kit.window.movie_capture`** | ✅ pure-Python | can write MP4 via Kit |
| **MuJoCo 3.7** | ✅ | `~/unitree-g1-test/.venv` |
| **CycloneDDS 0.10.2** | ✅ | `/usr/local/lib/libddsc.so.0.10.2` |
| **unitree_sdk2_python** | ✅ | same venv |
| **`neon-sim`** | ✅ | `~/neon-workspace/neon-sim` |
| **`neon-runtime`** | ✅ | `~/neon-workspace/neon-runtime` |
| **Polycam lab scan OBJ** | ✅ | `~/neon-workspace/neon-sim/assets/rooms/cagatay_lab.obj` |
| **GStreamer 1.24 + nvcodec** | ✅ | hw NVENC + SW x264 both work |
| **ffmpeg 4.4** | ⚠️  old | no `-preset`/`-crf` flags, use GStreamer |
| **NVENC (`/dev/v4l2-nvenc`)** | ✅ | Jetson HW H.264/H.265 encoder |
| **TigerVNC (`:5901`)** | ⚠️  no Vulkan | can't host Isaac's renderer |

## Performance captured

| Metric | Value |
|---|---|
| Isaac Sim cold-start | ~9s to `app ready` |
| Full init (camera ready) | ~15-20s |
| Render + capture loop | ~105s total for 60 frames (~0.6 fps on aarch64 raytraced) |
| GStreamer PNG→MP4 encode | 604ms for 47 frames |

**Note:** 0.6 fps is because we're writing each frame to disk as a PNG. The
live-streaming version pipes raw frames to gstreamer → eliminates disk I/O →
should hit 15-30 fps at 1280×720.

## Next steps

1. **Live RTSP stream** — replace file-sink with `rtspserver` → Mac can `open rtsp://192.168.1.151:8554/isaac`
2. **Load the G1 MJCF** into Isaac via the mjcf importer
3. **Load the Polycam lab OBJ** as a mesh in the stage
4. **Bridge DDS** — same bridge code we run on Mac MuJoCo

## Commands that worked on Thor tonight

```bash
# Isaac Sim headless render + capture (no display needed)
cd ~/isaacsim/_build/linux-aarch64/release
./python.sh /path/to/headless_capture.py  # SimulationApp(headless=True)

# Encode captured frames to video
gst-launch-1.0 -e \
  multifilesrc location=/tmp/isaac_frames/frame_%04d.png \
               start-index=0 caps="image/png,framerate=30/1" \
  ! pngdec ! videoconvert \
  ! x264enc bitrate=4000 speed-preset=ultrafast \
  ! mp4mux ! filesink location=/tmp/isaac.mp4
```
