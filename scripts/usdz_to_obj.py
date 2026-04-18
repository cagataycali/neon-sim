#!/usr/bin/env python3
"""Convert a Polycam USDZ scan to OBJ (for MuJoCo).

Prefers `pxr` (usd-core) for fidelity, falls back to `trimesh` on
platforms without a usd-core wheel (e.g. linux-aarch64 / Jetson).
"""
from __future__ import annotations
import argparse
import sys
import zipfile
from pathlib import Path

USE_PXR = False
USE_TRIMESH = False
try:
    from pxr import Usd, UsdGeom  # type: ignore
    USE_PXR = True
except ImportError:
    try:
        import trimesh  # type: ignore
        USE_TRIMESH = True
    except ImportError:
        sys.exit("❌ Need either usd-core or trimesh. Try: pip install trimesh")


def export_obj_pxr(usdz_path: Path, out: Path):
    """High-fidelity path via OpenUSD."""
    stage = Usd.Stage.Open(str(usdz_path))
    verts = []
    faces = []
    v_offset = 1

    for prim in stage.Traverse():
        if prim.GetTypeName() != "Mesh":
            continue
        mesh = UsdGeom.Mesh(prim)
        pts = mesh.GetPointsAttr().Get() or []
        fvc = mesh.GetFaceVertexCountsAttr().Get() or []
        fvi = mesh.GetFaceVertexIndicesAttr().Get() or []

        xf_cache = UsdGeom.XformCache()
        world_xf = xf_cache.GetLocalToWorldTransform(prim)

        for p in pts:
            wp = world_xf.Transform(p)
            verts.append((wp[0], wp[1], wp[2]))

        idx = 0
        for count in fvc:
            indices = [fvi[idx + i] + v_offset for i in range(count)]
            for i in range(1, count - 1):
                faces.append((indices[0], indices[i], indices[i + 1]))
            idx += count

        v_offset += len(pts)

    _write_obj(out, verts, faces)


def export_obj_trimesh(usdz_path: Path, out: Path):
    """Fallback via trimesh — works on aarch64 where usd-core has no wheel.

    trimesh reads USDZ by treating it as a ZIP of USDA/USDC + images.
    We extract, find the primary USD file, load it via trimesh.load().
    """
    # USDZ is a zip container
    with zipfile.ZipFile(usdz_path) as zf:
        # Try native trimesh first
        scene_or_mesh = trimesh.load(str(usdz_path), file_type="usdz", force="mesh")

    if scene_or_mesh is None or (hasattr(scene_or_mesh, "is_empty") and scene_or_mesh.is_empty):
        sys.exit("❌ trimesh could not parse USDZ — try installing usd-core or pass --obj directly")

    # Get combined mesh
    if hasattr(scene_or_mesh, "dump"):
        mesh = scene_or_mesh.dump(concatenate=True)
    else:
        mesh = scene_or_mesh

    verts = [(float(v[0]), float(v[1]), float(v[2])) for v in mesh.vertices]
    faces = [(int(f[0]) + 1, int(f[1]) + 1, int(f[2]) + 1) for f in mesh.faces]
    _write_obj(out, verts, faces)


def _write_obj(out: Path, verts, faces):
    with out.open("w") as f:
        f.write("# neon-sim: converted from USDZ\n")
        f.write(f"# verts: {len(verts)}  faces: {len(faces)}\n")
        for v in verts:
            f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
        for face in faces:
            f.write(f"f {face[0]} {face[1]} {face[2]}\n")
    print(f"✅ Wrote {out}: {len(verts)} verts, {len(faces)} faces")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", help="Input .usdz")
    ap.add_argument("--out", default=None, help="Output .obj")
    ap.add_argument("--backend", choices=["auto", "pxr", "trimesh"], default="auto")
    args = ap.parse_args()

    inp = Path(args.input).resolve()
    if not inp.exists():
        sys.exit(f"❌ Not found: {inp}")
    out = Path(args.out).resolve() if args.out else inp.with_suffix(".obj")

    backend = args.backend
    if backend == "auto":
        backend = "pxr" if USE_PXR else "trimesh"

    print(f"📦 Converting {inp} → {out}  (backend: {backend})")

    if backend == "pxr":
        if not USE_PXR:
            sys.exit("❌ pxr/usd-core not installed")
        export_obj_pxr(inp, out)
    else:
        if not USE_TRIMESH:
            sys.exit("❌ trimesh not installed")
        export_obj_trimesh(inp, out)


if __name__ == "__main__":
    main()
