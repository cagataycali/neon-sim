"""Integration test: USDZ → textured MJCF pipeline."""
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


@pytest.fixture
def minimal_usdz(tmp_path):
    """Build a tiny fake USDZ to test the converter on."""
    usda = tmp_path / "stage.usda"
    usda.write_text('''#usda 1.0
(
    defaultPrim = "object"
    upAxis = "Y"
    metersPerUnit = 1.0
)

def Xform "object" {
    def Mesh "cube" {
        point3f[] points = [(-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
                            (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1)]
        int[] faceVertexCounts = [4, 4, 4, 4, 4, 4]
        int[] faceVertexIndices = [0, 1, 2, 3, 4, 5, 6, 7, 0, 1, 5, 4,
                                   2, 3, 7, 6, 0, 3, 7, 4, 1, 2, 6, 5]
    }
}
''')
    usdz = tmp_path / "test.usdz"
    with zipfile.ZipFile(usdz, "w") as zf:
        zf.write(usda, "stage.usda")
    return usdz


def test_usd2mjcf_with_textures(minimal_usdz, tmp_path):
    """Converter produces a valid MJCF from a minimal USDZ."""
    here = Path(__file__).parent.parent
    out_dir = tmp_path / "out"
    result = subprocess.run(
        [sys.executable, str(here / "scripts" / "usd2mjcf_with_textures.py"),
         str(minimal_usdz), "--out-dir", str(out_dir)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, (
        f"Converter failed:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    mjcf = out_dir / "MJCF" / "test.xml"
    assert mjcf.exists(), f"Expected MJCF at {mjcf}"
    content = mjcf.read_text()
    assert "<mujoco" in content, "Output should be a MuJoCo XML"
    assert "<mesh" in content, "Output should contain mesh references"


def test_mjcf_loads_in_mujoco(minimal_usdz, tmp_path):
    """Generated MJCF is actually loadable by MuJoCo."""
    mujoco = pytest.importorskip("mujoco")
    here = Path(__file__).parent.parent
    out_dir = tmp_path / "out"
    subprocess.run(
        [sys.executable, str(here / "scripts" / "usd2mjcf_with_textures.py"),
         str(minimal_usdz), "--out-dir", str(out_dir)],
        check=True,
    )
    mjcf = out_dir / "MJCF" / "test.xml"
    model = mujoco.MjModel.from_xml_path(str(mjcf))
    assert model.nmesh >= 1, "Should load at least one mesh"
