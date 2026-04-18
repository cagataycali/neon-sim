#!/usr/bin/env python3
"""Convert a Polycam USDZ scan to OBJ (for MuJoCo)."""
from __future__ import annotations
import argparse
import sys
import tempfile
import zipfile
from pathlib import Path

try:
    from pxr import Usd, UsdGeom
except ImportError:
    sys.exit("❌ Run: pip install usd-core")


def export_obj(stage: Usd.Stage, out: Path):
    """Write all meshes to a single OBJ file."""
    verts = []
    faces = []
    v_offset = 1  # OBJ is 1-indexed

    for prim in stage.Traverse():
        if prim.GetTypeName() != "Mesh":
            continue
        mesh = UsdGeom.Mesh(prim)
        pts = mesh.GetPointsAttr().Get() or []
        fvc = mesh.GetFaceVertexCountsAttr().Get() or []
        fvi = mesh.GetFaceVertexIndicesAttr().Get() or []

        # Transform points to world space
        xf_cache = UsdGeom.XformCache()
        world_xf = xf_cache.GetLocalToWorldTransform(prim)

        for p in pts:
            wp = world_xf.Transform(p)
            verts.append((wp[0], wp[1], wp[2]))

        # Triangulate (assume quads or more, reduce to tris for OBJ)
        idx = 0
        for count in fvc:
            indices = [fvi[idx + i] + v_offset for i in range(count)]
            # Fan triangulation
            for i in range(1, count - 1):
                faces.append((indices[0], indices[i], indices[i + 1]))
            idx += count

        v_offset += len(pts)

    with out.open("w") as f:
        f.write(f"# neon-sim: converted from USDZ\n")
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
    args = ap.parse_args()

    inp = Path(args.input).resolve()
    out = Path(args.out) if args.out else inp.with_suffix(".obj")

    with tempfile.TemporaryDirectory() as td:
        # Extract USDZ
        if inp.suffix == ".usdz":
            with zipfile.ZipFile(inp) as zf:
                zf.extractall(td)
            usda = next(Path(td).glob("*.usda"), None) or next(Path(td).glob("*.usdc"), None)
        else:
            usda = inp

        stage = Usd.Stage.Open(str(usda))
        export_obj(stage, out)


if __name__ == "__main__":
    main()
