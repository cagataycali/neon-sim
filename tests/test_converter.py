"""Integration test: can the converter round-trip a Polycam USDZ?"""
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest


@pytest.fixture
def minimal_usdz(tmp_path):
    """Build a tiny fake USDZ file to test the converter on."""
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
        int[] faceVertexIndices = [0, 1, 2, 3, 4, 5, 6, 7, 0, 1, 5, 4, 2, 3, 7, 6, 0, 3, 7, 4, 1, 2, 6, 5]
    }
}
''')

    usdz = tmp_path / "test.usdz"
    with zipfile.ZipFile(usdz, "w") as zf:
        zf.write(usda, "stage.usda")

    return usdz


def test_converter_basic(minimal_usdz, tmp_path):
    """Converter produces a valid USD from a minimal USDZ."""
    out = tmp_path / "out.usd"
    here = Path(__file__).parent.parent
    result = subprocess.run(
        [sys.executable, str(here / "scripts" / "convert_polycam.py"),
         str(minimal_usdz), "--out", str(out)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, f"Converter failed:\n{result.stderr}\n{result.stdout}"
    assert out.exists(), f"Output not created: {out}"
    assert out.stat().st_size > 100, "Output suspiciously small"


def test_usdz_to_obj(minimal_usdz, tmp_path):
    """USDZ → OBJ converter produces valid OBJ."""
    out = tmp_path / "out.obj"
    here = Path(__file__).parent.parent
    result = subprocess.run(
        [sys.executable, str(here / "scripts" / "usdz_to_obj.py"),
         str(minimal_usdz), "--out", str(out)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert out.exists()
    content = out.read_text()
    assert content.startswith("#"), "OBJ should start with comment"
    assert "v " in content, "OBJ should have vertex lines"
    assert "f " in content, "OBJ should have face lines"
