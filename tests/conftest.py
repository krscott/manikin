import io

import pytest
from PIL import Image

from manikin.pose import SKELETON, BoneFrame, Joint, Pose


@pytest.fixture
def sample_pose() -> Pose:
    """A simple pose with every bone and joint, for tests that don't check math."""
    return Pose(
        bones={
            bone: BoneFrame(direction=(0.0, 0.0, 1.0), reference=(0.0, -1.0, 0.0))
            for bone in SKELETON
        },
        joints={joint: (0.0, 0.0, 0.1 * i) for i, joint in enumerate(Joint)},
        image_points={joint: (10.0 + i, 20.0) for i, joint in enumerate(Joint)},
        image_size=(64, 48),
    )


@pytest.fixture
def jpeg_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), "gray").save(buffer, format="JPEG")
    return buffer.getvalue()
