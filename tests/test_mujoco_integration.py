"""Full integration test: USDZ → OBJ → MuJoCo composite scene."""
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


def test_mujoco_composite_loads(tmp_path):
    """Build a composite scene with a tiny fake room and verify it loads."""
    mujoco = pytest.importorskip("mujoco")

    # Build a fake room OBJ
    room = tmp_path / "fake_room.obj"
    room.write_text('''# fake room
v -2 -2 0
v 2 -2 0
v 2 2 0
v -2 2 0
v -2 -2 3
v 2 -2 3
v 2 2 3
v -2 2 3
f 1 2 3
f 1 3 4
f 5 6 7
f 5 7 8
''')

    g1_scene = Path.home() / "unitree_mujoco/unitree_robots/g1/scene_29dof.xml"
    if not g1_scene.exists():
        pytest.skip("unitree_mujoco not installed")

    # Use our stage module to build a composite
    from neon_sim.mujoco.stage import build_composite_scene, find_g1_scene

    g1 = find_g1_scene("29")
    composite = build_composite_scene(g1, room)
    assert composite.exists()

    # Load it in MuJoCo
    model = mujoco.MjModel.from_xml_path(str(composite))
    assert model.nbody >= 30  # G1 has 31 + 1 for room
    assert model.nu == 29      # 29-DoF G1

    data = mujoco.MjData(model)
    # Step a few times to ensure physics is valid
    for _ in range(10):
        mujoco.mj_step(model, data)

    assert data.time > 0
