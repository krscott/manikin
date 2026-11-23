"""Manual tests that run SAM 3D Body on the GPU. Run with `just test-gpu`.

They need the model weights (see 'Model weights' in the README) and a CUDA GPU.
Set MANIKIN_UPDATE_FIXTURES=1 to rewrite tests/data/kungfu.pose.json instead of
comparing against it.
"""

import json
import math
import os
from pathlib import Path

import numpy as np
import pytest
import torch

from manikin import __version__
from manikin.config import defaults
from manikin.photo import Photo, decode_photo
from manikin.pose import SKELETON, Bone, EstimateError, Joint, Pose, pose_file
from manikin.sam_backend import BACKEND_NAME, SamBackend, missing_weights_error

pytestmark = pytest.mark.gpu

DATA = Path(__file__).parent / "data"
FIXTURE = DATA / "kungfu.pose.json"


@pytest.fixture(scope="module")
def model_dir() -> Path:
    path = Path(os.environ.get("MANIKIN_MODEL_DIR") or defaults()["model_dir"])
    error = missing_weights_error(path)
    if error is not None:
        pytest.skip(error)
    return path


@pytest.fixture(scope="module")
def backend(model_dir: Path) -> SamBackend:
    return SamBackend(model_dir=model_dir, idle_timeout=600)


@pytest.fixture(scope="module")
def kungfu(backend: SamBackend) -> tuple[Photo, Pose]:
    photo = decode_photo((DATA / "kungfu.jpg").read_bytes())
    assert isinstance(photo, Photo)
    pose = backend.estimate(np.asarray(photo.image))
    assert not isinstance(pose, EstimateError), pose
    return photo, pose


def test_pose_matches_fixture(kungfu: tuple[Photo, Pose]) -> None:
    _, pose = kungfu
    document = pose_file(pose, backend=BACKEND_NAME, manikin_version=__version__)
    if os.environ.get("MANIKIN_UPDATE_FIXTURES") == "1":
        FIXTURE.write_text(json.dumps(document, indent=2) + "\n")
    expected = json.loads(FIXTURE.read_text())
    for bone, spec in expected["bones"].items():
        for key in ("direction", "reference"):
            angle = _angle(document["bones"][bone][key], spec[key])
            assert angle < 3.0, f"{bone} {key} moved {angle:.1f}°"


def test_raised_knee_and_extended_arms(kungfu: tuple[Photo, Pose]) -> None:
    """Sanity checks a person can verify by looking at the photo."""
    _, pose = kungfu
    joints = pose.joints
    # The subject's left knee is raised to hip height; the right leg stands.
    assert joints[Joint.KNEE_L][2] > joints[Joint.KNEE_R][2] + 0.3
    # Both arms reach out to their own side.
    assert joints[Joint.WRIST_L][0] > joints[Joint.SHOULDER_L][0] + 0.2
    assert joints[Joint.WRIST_R][0] < joints[Joint.SHOULDER_R][0] - 0.2
    # The pelvis faces -Y after removing camera yaw.
    forward = pose.bones[Bone.PELVIS].reference
    assert forward[1] < -0.9


def test_image_points_land_on_the_person(kungfu: tuple[Photo, Pose]) -> None:
    photo, pose = kungfu
    assert pose.image_size == photo.image.size
    # Rough bounds of the person in the 960x1440 photo.
    for joint, (x, y) in pose.image_points.items():
        assert 250 < x < 900 and 550 < y < 1250, f"{joint} at {(x, y)}"


def test_all_bones_present(kungfu: tuple[Photo, Pose]) -> None:
    _, pose = kungfu
    assert set(pose.bones) == set(SKELETON)


def _angle(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return math.degrees(math.acos(max(-1.0, min(1.0, dot))))


def test_idle_unload_frees_gpu_memory(model_dir: Path) -> None:
    now = [0.0]
    idle = SamBackend(model_dir=model_dir, idle_timeout=60, clock=lambda: now[0])
    photo = decode_photo((DATA / "kungfu.jpg").read_bytes())
    assert isinstance(photo, Photo)
    baseline = torch.cuda.memory_allocated()
    assert not isinstance(idle.estimate(np.asarray(photo.image)), EstimateError)
    assert idle.loaded
    assert torch.cuda.memory_allocated() > baseline + 1e9

    now[0] = 59.0
    assert not idle.unload_if_idle()
    now[0] = 61.0
    assert idle.unload_if_idle()
    assert not idle.loaded
    assert torch.cuda.memory_allocated() < baseline + 1e8
