"""Manual tests that run the Blender add-on in headless Blender.

Run with `just test-blender`, which provides Blender from the locked nixpkgs.
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.blender

ROOT = Path(__file__).parent.parent
ADDON = ROOT / "manikin" / "blender" / "manikin_rigify.py"
DRIVER = Path(__file__).parent / "blender_driver.py"
POSE = Path(__file__).parent / "data" / "kungfu.pose.json"


@pytest.fixture(scope="module")
def applied(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    blender = os.environ.get("MANIKIN_BLENDER")
    if not blender:
        pytest.skip("Set MANIKIN_BLENDER to a Blender executable")
    out = tmp_path_factory.mktemp("blender") / "result.json"
    subprocess.run(
        [
            blender,
            "--background",
            "--factory-startup",
            "--python-exit-code",
            "1",
            "--python",
            str(DRIVER),
            "--",
            str(ADDON),
            str(POSE),
            str(out),
        ],
        check=True,
    )
    result: dict[str, Any] = json.loads(out.read_text())
    return result


def test_operator_finishes(applied: dict[str, Any]) -> None:
    assert applied["operator"] == ["FINISHED"]


def test_bones_point_where_the_pose_says(applied: dict[str, Any]) -> None:
    errors: dict[str, dict[str, float]] = applied["errors"]
    # Rigify's spine gives two adjacent segments the same twist source, so their
    # twists cannot match independently; allow a little twist error.
    bad = {
        bone: error
        for bone, error in errors.items()
        if error["direction"] > 0.5 or error["reference"] > 2.0
    }
    assert not bad, json.dumps(bad, indent=2)


def test_limbs_switch_to_fk_and_are_keyed(applied: dict[str, Any]) -> None:
    ik_fk: dict[str, float] = applied["ik_fk"]
    assert set(ik_fk.values()) == {1.0}
    assert applied["keyed"] is True
