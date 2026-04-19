#!/usr/bin/env python3
"""USD/USDZ → textured MJCF using LightwheelAI/usd2mjcf + texture patch.

Pipeline:
  1. Flatten USDZ → USD, extract textures loose, retype Scope→Xform,
     rewrite asset paths (what usd2mjcf needs).
  2. Run usd2mjcf to get correct MJCF structure (mesh-per-material, transforms).
  3. Walk the ORIGINAL USD to recover {material → texture file} mapping.
  4. Patch the generated MJCF: convert <material rgba=...> → <material texture=...>
     + add <texture file="..."/> entries. Convert JPG textures to PNG.

Usage:
    python3 usd2mjcf_with_textures.py input.usdz --out-dir ./out
"""
from __future__ import annotations
import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

from pxr import Usd, UsdGeom, UsdShade, Sdf
from PIL import Image


def prep_usd(src: Path, workdir: Path) -> Path:
    """Extract textures, flatten USDZ, retype Scope→Xform, rewrite paths."""
    workdir.mkdir(parents=True, exist_ok=True)
    tex_dir = workdir / "textures"
    tex_dir.mkdir(exist_ok=True)

    # Extract textures
    if src.suffix.lower() == ".usdz":
        with zipfile.ZipFile(src) as zf:
            for n in zf.namelist():
                if n.lower().endswith((".jpg", ".jpeg", ".png")):
                    (tex_dir / Path(n).name).write_bytes(zf.read(n))

    stage = Usd.Stage.Open(str(src))
    flat = stage.Flatten()
    dst_usd = workdir / f"{src.stem}.usd"
    if dst_usd.exists():
        dst_usd.unlink()
    fs = Usd.Stage.CreateNew(str(dst_usd))
    fs.GetRootLayer().TransferContent(flat)

    for p in fs.Traverse():
        if p.GetTypeName() == "Scope":
            p.SetTypeName("Xform")

    # Rewrite texture asset paths to be local
    for p in fs.Traverse():
        if p.GetTypeName() != "Shader":
            continue
        shader = UsdShade.Shader(p)
        if shader.GetShaderId() != "UsdUVTexture":
            continue
        fi = shader.GetInput("file")
        v = fi.Get() if fi else None
        if v is None:
            continue
        ap = getattr(v, "authoredPath", None) or str(v)
        if ap:
            fi.Set(Sdf.AssetPath(f"./textures/{Path(ap).name}"))
    fs.Save()
    print(f"✓ Prepped USD: {dst_usd}")
    return dst_usd


def extract_material_textures(usdz_or_usd: Path) -> dict:
    """Return {material_name → texture_filename}."""
    stage = Usd.Stage.Open(str(usdz_or_usd))
    out = {}
    for prim in stage.Traverse():
        if prim.GetTypeName() != "Material":
            continue
        mat_name = prim.GetName()
        for d in Usd.PrimRange(prim):
            if d.GetTypeName() != "Shader":
                continue
            shader = UsdShade.Shader(d)
            if shader.GetShaderId() != "UsdUVTexture":
                continue
            fi = shader.GetInput("file")
            v = fi.Get() if fi else None
            if v is None:
                continue
            ap = getattr(v, "authoredPath", None) or str(v)
            if ap:
                out[mat_name] = Path(ap).name.rstrip("]")
                break
    return out


def ensure_png(tex_dir: Path, filename: str, max_dim: int = 1024) -> str:
    """Ensure filename exists as PNG in tex_dir; return final filename."""
    src = tex_dir / filename
    if src.suffix.lower() == ".png":
        return filename
    png = src.with_suffix(".png")
    if not png.exists():
        img = Image.open(src).convert("RGB")
        if max(img.size) > max_dim:
            r = max_dim / max(img.size)
            img = img.resize((int(img.size[0]*r), int(img.size[1]*r)), Image.LANCZOS)
        img.save(png, "PNG", optimize=True)
    return png.name


def patch_mjcf(mjcf_path: Path, mat_tex: dict, tex_dir: Path):
    """Wire textures into usd2mjcf's <material rgba> elements."""
    tree = ET.parse(mjcf_path)
    root = tree.getroot()
    asset = root.find("asset")
    if asset is None:
        print("⚠️  No <asset> in MJCF"); return

    # Find target materials, collect unique textures
    tex_to_use = {}  # filename → tex name
    patched = 0
    for mat_el in asset.findall("material"):
        mat_name = mat_el.get("name")
        if mat_name not in mat_tex:
            continue
        tex_fname = mat_tex[mat_name]
        png_fname = ensure_png(tex_dir, tex_fname)
        if png_fname not in tex_to_use:
            tex_name = f"tex_{Path(png_fname).stem[:16]}"
            tex_to_use[png_fname] = tex_name
        tex_name = tex_to_use[png_fname]
        # Swap rgba → texture
        if "rgba" in mat_el.attrib:
            del mat_el.attrib["rgba"]
        mat_el.set("texture", tex_name)
        mat_el.set("texuniform", "false")
        mat_el.set("specular", "0.1")
        patched += 1

    # Add <texture> entries at the TOP of <asset>
    # Figure out relative path from MJCF → textures dir
    rel_prefix = Path("..") / tex_dir.relative_to(tex_dir.parent.parent)
    # Actually we want path relative to MJCF directory:
    rel_prefix = Path(
        (tex_dir.resolve() if tex_dir.is_absolute() else tex_dir).resolve()
        .relative_to(mjcf_path.parent.resolve().parent if mjcf_path.parent.resolve() != tex_dir.resolve().parent else mjcf_path.parent.resolve())
    ) if False else None
    # Simplest: copy textures into MJCF/textures so paths are stable
    mjcf_tex_dir = mjcf_path.parent / "textures"
    mjcf_tex_dir.mkdir(exist_ok=True)
    for png_fname, tex_name in tex_to_use.items():
        dst = mjcf_tex_dir / png_fname
        if not dst.exists():
            shutil.copy(tex_dir / png_fname, dst)

    # Insert texture nodes
    for png_fname, tex_name in tex_to_use.items():
        t = ET.Element("texture")
        t.set("name", tex_name)
        t.set("type", "2d")
        t.set("file", f"textures/{png_fname}")
        asset.insert(0, t)

    tree.write(mjcf_path, xml_declaration=True, encoding="utf-8")
    print(f"✓ Patched MJCF: {patched} materials → {len(tex_to_use)} textures")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", help=".usdz or .usd input")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--generate-collision", action="store_true")
    args = ap.parse_args()

    src = Path(args.input).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Prep USD
    prepped = prep_usd(src, out_dir)

    # 2. Extract material → texture mapping BEFORE conversion
    mat_tex = extract_material_textures(prepped)
    print(f"✓ Found {len(mat_tex)} textured materials")

    # 3. Run usd2mjcf
    cmd = [sys.executable, "/tmp/usd2mjcf/test/usd2mjcf_test.py", str(prepped)]
    if args.generate_collision:
        cmd.append("--generate_collision")
    print(f"→ Running: {' '.join(cmd)}")
    subprocess.run(cmd, check=True, cwd="/tmp/usd2mjcf")

    mjcf_path = prepped.parent / "MJCF" / f"{prepped.stem}.xml"
    if not mjcf_path.exists():
        sys.exit(f"❌ Expected MJCF at {mjcf_path}")

    # 4. Patch textures into MJCF
    patch_mjcf(mjcf_path, mat_tex, out_dir / "textures")

    print(f"\n✅ Done: {mjcf_path}")


if __name__ == "__main__":
    main()
