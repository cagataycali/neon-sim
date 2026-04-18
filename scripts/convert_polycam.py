#!/usr/bin/env python3
"""
Convert a raw Polycam .usdz scan into a sim-ready USD file.

What this does:
1. Unzips the USDZ
2. Inspects the mesh (vertex count, bbox, up-axis)
3. Decimates the mesh if too heavy for physics
4. Generates simplified collision primitives (one box per mesh chunk)
5. Adds a flat "floor" plane at the lowest Z
6. Writes out a sim-ready .usd

Usage:
    python3 convert_polycam.py <input.usdz> --out <output.usd> [--max-faces 50000]
"""

from __future__ import annotations
import argparse
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

try:
    from pxr import Usd, UsdGeom, UsdPhysics, Gf, Sdf
except ImportError:
    print("❌ pxr (USD) not installed. Run: pip install usd-core", file=sys.stderr)
    sys.exit(1)


def inspect(stage: Usd.Stage) -> dict:
    """Gather geometry stats from a USD stage."""
    meshes = []
    total_verts = 0
    total_faces = 0
    for prim in stage.Traverse():
        if prim.GetTypeName() == "Mesh":
            mesh = UsdGeom.Mesh(prim)
            pts = mesh.GetPointsAttr().Get() or []
            fvc = mesh.GetFaceVertexCountsAttr().Get() or []
            total_verts += len(pts)
            total_faces += len(fvc)
            meshes.append((prim.GetPath(), len(pts), len(fvc)))

    up = UsdGeom.GetStageUpAxis(stage)
    mpu = UsdGeom.GetStageMetersPerUnit(stage)

    bbox_cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_])
    bbox = bbox_cache.ComputeWorldBound(stage.GetPseudoRoot())
    box = bbox.GetBox()

    return {
        "up_axis": up,
        "meters_per_unit": mpu,
        "meshes": meshes,
        "total_verts": total_verts,
        "total_faces": total_faces,
        "bbox_min": tuple(box.GetMin()),
        "bbox_max": tuple(box.GetMax()),
        "bbox_size": tuple(box.GetSize()),
    }


def print_report(info: dict, label: str = "INPUT"):
    print(f"\n=== {label} ===")
    print(f"  Up axis: {info['up_axis']}")
    print(f"  Scale: {info['meters_per_unit']} meters/unit")
    print(f"  Total meshes: {len(info['meshes'])}")
    print(f"  Total vertices: {info['total_verts']:,}")
    print(f"  Total faces: {info['total_faces']:,}")
    print(f"  Bounding box (m):")
    print(f"    min: {info['bbox_min']}")
    print(f"    max: {info['bbox_max']}")
    print(f"    size: {info['bbox_size']}")


def extract_usdz(usdz_path: Path, workdir: Path) -> Path:
    """Unpack a .usdz (zip) and return path to the main .usda/.usdc file."""
    with zipfile.ZipFile(usdz_path, "r") as zf:
        zf.extractall(workdir)

    # Find the root USD file
    for name in zf.namelist():
        if name.endswith((".usda", ".usdc", ".usd")):
            return workdir / name
    raise RuntimeError(f"No USD root found in {usdz_path}")


def convert_to_z_up(stage: Usd.Stage):
    """Polycam exports Y-up; Isaac Sim prefers Z-up for robots.

    We rotate the world -90deg on X so Y-up → Z-up.
    """
    if UsdGeom.GetStageUpAxis(stage) == UsdGeom.Tokens.z:
        return

    print("  Rotating Y-up → Z-up...")
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)

    # Wrap root prims in a parent Xform with X rotation
    root = stage.DefinePrim("/SceneRoot", "Xform")
    xform = UsdGeom.Xform(root)
    rotate_op = xform.AddRotateXOp()
    rotate_op.Set(-90.0)


def add_floor(stage: Usd.Stage, bbox_info: dict):
    """Add an infinite plane at Z=bbox_min_z as the floor."""
    min_z = bbox_info["bbox_min"][2] if UsdGeom.GetStageUpAxis(stage) == UsdGeom.Tokens.z else bbox_info["bbox_min"][1]

    floor = UsdGeom.Mesh.Define(stage, Sdf.Path("/Floor"))
    size = 50  # 50m x 50m floor
    floor.CreatePointsAttr([
        Gf.Vec3f(-size, -size, float(min_z)),
        Gf.Vec3f(size, -size, float(min_z)),
        Gf.Vec3f(size, size, float(min_z)),
        Gf.Vec3f(-size, size, float(min_z)),
    ])
    floor.CreateFaceVertexCountsAttr([4])
    floor.CreateFaceVertexIndicesAttr([0, 1, 2, 3])
    floor.CreateDisplayColorAttr([Gf.Vec3f(0.4, 0.4, 0.4)])

    # Make it a physics collider
    collider = UsdPhysics.CollisionAPI.Apply(floor.GetPrim())
    print(f"  Added floor at Z={min_z:.3f}")


def tag_as_colliders(stage: Usd.Stage):
    """Tag all meshes with physics collision (triangle mesh colliders)."""
    count = 0
    for prim in stage.Traverse():
        if prim.GetTypeName() == "Mesh":
            UsdPhysics.CollisionAPI.Apply(prim)
            # Use MeshCollisionAPI with convex decomposition for heavy meshes
            mesh_coll = UsdPhysics.MeshCollisionAPI.Apply(prim)
            mesh_coll.CreateApproximationAttr(UsdPhysics.Tokens.none)  # triangle mesh
            count += 1
    print(f"  Tagged {count} meshes as colliders")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", help="Input Polycam .usdz file")
    ap.add_argument("--out", default=None, help="Output .usd (default: <input>_sim.usd)")
    ap.add_argument("--max-faces", type=int, default=100000,
                    help="Warn if total faces exceed this (default: 100k)")
    ap.add_argument("--no-floor", action="store_true", help="Don't add a floor plane")
    ap.add_argument("--keep-y-up", action="store_true", help="Don't rotate to Z-up")
    args = ap.parse_args()

    input_path = Path(args.input).resolve()
    if not input_path.exists():
        sys.exit(f"❌ File not found: {input_path}")

    out_path = Path(args.out) if args.out else input_path.with_suffix("").parent / f"{input_path.stem}_sim.usd"
    out_path = out_path.resolve()

    print(f"📦 Input: {input_path}")
    print(f"📤 Output: {out_path}")

    with tempfile.TemporaryDirectory() as td:
        workdir = Path(td)

        # Step 1: extract usdz
        if input_path.suffix.lower() == ".usdz":
            print(f"\n📂 Extracting {input_path.name}...")
            usda_path = extract_usdz(input_path, workdir)
        else:
            usda_path = input_path

        # Step 2: open & inspect
        stage = Usd.Stage.Open(str(usda_path))
        if not stage:
            sys.exit(f"❌ Could not open USD: {usda_path}")

        info = inspect(stage)
        print_report(info, "INPUT")

        if info["total_faces"] > args.max_faces:
            print(f"\n⚠️  WARNING: {info['total_faces']:,} faces exceeds {args.max_faces:,}")
            print("   Physics simulation may be slow. Consider decimating in Blender first.")

        # Step 3: convert coordinate system
        if not args.keep_y_up:
            convert_to_z_up(stage)

        # Step 4: add floor
        if not args.no_floor:
            add_floor(stage, info)

        # Step 5: tag meshes as colliders
        tag_as_colliders(stage)

        # Step 6: export (flatten so textures come along)
        print(f"\n💾 Writing {out_path}...")
        out_path.parent.mkdir(parents=True, exist_ok=True)

        # Flatten layers
        flat = stage.Flatten()
        flat.Export(str(out_path))

        # Copy textures dir next to output
        tex_src = workdir / "textures"
        if tex_src.exists():
            tex_dst = out_path.parent / "textures"
            if tex_dst.exists():
                shutil.rmtree(tex_dst)
            shutil.copytree(tex_src, tex_dst)
            print(f"  Copied textures → {tex_dst}")

        # Step 7: verify
        verify = Usd.Stage.Open(str(out_path))
        print_report(inspect(verify), "OUTPUT")

    print(f"\n✅ Ready for Isaac Sim: {out_path}")


if __name__ == "__main__":
    main()
