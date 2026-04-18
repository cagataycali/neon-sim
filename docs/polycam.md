# Polycam workflow

## Scanning tips

- **LiDAR mode** (iPhone Pro) beats photogrammetry for indoor scenes
- Keep walking, don't stand still — Polycam needs parallax
- Overlap by ~30% when panning
- Capture ceilings if you want them in sim (usually skip — robot doesn't fly)
- Close the walk-loop back to your start point for best alignment

## Export settings

Polycam → your scan → **Export** → **USDZ** → **High / Textured**.

The file is typically 10-50MB. Save to iCloud for easy Mac access.

## Importing to neon-sim

```bash
# Put the scan in assets/rooms/
cp ~/Downloads/my_office.usdz assets/rooms/

# Let the launch script preprocess it
./scripts/launch_sim.sh assets/rooms/my_office.usdz

# Or preprocess manually to inspect
python3 scripts/convert_polycam.py assets/rooms/my_office.usdz
```

## What the preprocessor does

1. **Extracts USDZ** (it's just a zip) and reads the USD stage
2. **Inspects geometry** — prints vertex/face counts and bounding box
3. **Converts Y-up → Z-up** — Polycam exports Y-up (ARKit/USD convention),
   Isaac Sim and MuJoCo prefer Z-up for robots
4. **Adds a floor plane** at the scan's minimum Z — Polycam often has
   tilted floors because of accumulated drift; a flat plane underneath
   guarantees the robot doesn't fall through
5. **Tags meshes as colliders** — static triangle-mesh physics
6. **Copies textures** alongside the output USD

## Coordinate gotchas

Polycam places the origin at your scan start. If the robot spawns
inside a wall, you have two options:

1. **Edit the USD** in Blender/Cursor to re-center
2. Use `--spawn-x --spawn-y --spawn-z` flags when launching

```bash
python3 -m neon_sim.isaac.stage --room assets/rooms/my_room_sim.usd \
  --spawn-x 2.0 --spawn-y -1.5 --spawn-z 1.0
```

## Mesh is too heavy

Polycam exports can hit 500k+ triangles. Physics gets slow above ~100k.

Options:
- **Blender decimate**: Open the USDZ, select all meshes, Modifier → Decimate (Collapse, ratio 0.3)
- **Polycam decimate**: Set export quality to "Medium" or "Low"
- **Manual collider boxes**: Replace the triangle-mesh collider with a few
  box primitives for walls/furniture. Much faster physics.

## Privacy note

Your scans show your actual space. We gitignore `assets/rooms/*.usdz` so
you don't accidentally commit your apartment layout to public GitHub.
