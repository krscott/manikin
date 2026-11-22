"""Backend-neutral pose description and the saved `pose.json` format.

World coordinates follow Blender's convention for a character at rest:
+X is the subject's left, -Y is the subject's forward, +Z is up. Units are meters.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, Protocol

import numpy as np

type Vec2 = tuple[float, float]
type Vec3 = tuple[float, float, float]

POSE_FORMAT = "manikin-pose"
POSE_FORMAT_VERSION = 1


class Joint(StrEnum):
    PELVIS = "pelvis"
    SPINE_0 = "spine_0"
    SPINE_1 = "spine_1"
    SPINE_2 = "spine_2"
    SPINE_3 = "spine_3"
    NECK = "neck"
    HEAD = "head"
    HEAD_TOP = "head_top"
    CLAVICLE_L = "clavicle.L"
    SHOULDER_L = "shoulder.L"
    ELBOW_L = "elbow.L"
    WRIST_L = "wrist.L"
    KNUCKLES_L = "knuckles.L"
    HIP_L = "hip.L"
    KNEE_L = "knee.L"
    ANKLE_L = "ankle.L"
    BALL_L = "ball.L"
    TOE_TIP_L = "toe_tip.L"
    CLAVICLE_R = "clavicle.R"
    SHOULDER_R = "shoulder.R"
    ELBOW_R = "elbow.R"
    WRIST_R = "wrist.R"
    KNUCKLES_R = "knuckles.R"
    HIP_R = "hip.R"
    KNEE_R = "knee.R"
    ANKLE_R = "ankle.R"
    BALL_R = "ball.R"
    TOE_TIP_R = "toe_tip.R"


class Bone(StrEnum):
    PELVIS = "pelvis"
    SPINE_0 = "spine_0"
    SPINE_1 = "spine_1"
    SPINE_2 = "spine_2"
    SPINE_3 = "spine_3"
    NECK = "neck"
    HEAD = "head"
    SHOULDER_L = "shoulder.L"
    UPPER_ARM_L = "upper_arm.L"
    FOREARM_L = "forearm.L"
    HAND_L = "hand.L"
    THIGH_L = "thigh.L"
    SHIN_L = "shin.L"
    FOOT_L = "foot.L"
    TOE_L = "toe.L"
    SHOULDER_R = "shoulder.R"
    UPPER_ARM_R = "upper_arm.R"
    FOREARM_R = "forearm.R"
    HAND_R = "hand.R"
    THIGH_R = "thigh.R"
    SHIN_R = "shin.R"
    FOOT_R = "foot.R"
    TOE_R = "toe.R"


type ReferenceAxis = Literal["forward", "up"]


@dataclass(frozen=True, kw_only=True)
class BoneSpec:
    head: Joint
    tail: Joint
    # Body axis whose posed direction fixes the bone's twist. It must not be
    # parallel to the bone at rest.
    reference_axis: ReferenceAxis


def _sided(side: Literal["L", "R"]) -> dict[Bone, BoneSpec]:
    def j(name: str) -> Joint:
        return Joint(f"{name}.{side}")

    def b(name: str) -> Bone:
        return Bone(f"{name}.{side}")

    return {
        b("shoulder"): BoneSpec(
            head=j("clavicle"), tail=j("shoulder"), reference_axis="forward"
        ),
        b("upper_arm"): BoneSpec(
            head=j("shoulder"), tail=j("elbow"), reference_axis="forward"
        ),
        b("forearm"): BoneSpec(
            head=j("elbow"), tail=j("wrist"), reference_axis="forward"
        ),
        b("hand"): BoneSpec(
            head=j("wrist"), tail=j("knuckles"), reference_axis="forward"
        ),
        b("thigh"): BoneSpec(head=j("hip"), tail=j("knee"), reference_axis="forward"),
        b("shin"): BoneSpec(head=j("knee"), tail=j("ankle"), reference_axis="forward"),
        b("foot"): BoneSpec(head=j("ankle"), tail=j("ball"), reference_axis="up"),
        b("toe"): BoneSpec(head=j("ball"), tail=j("toe_tip"), reference_axis="up"),
    }


# The pelvis is special: its direction is the body's up axis, not the
# pelvis -> spine_0 segment, which points mostly backward.
SKELETON: Mapping[Bone, BoneSpec] = {
    Bone.PELVIS: BoneSpec(
        head=Joint.PELVIS, tail=Joint.SPINE_0, reference_axis="forward"
    ),
    Bone.SPINE_0: BoneSpec(
        head=Joint.SPINE_0, tail=Joint.SPINE_1, reference_axis="forward"
    ),
    Bone.SPINE_1: BoneSpec(
        head=Joint.SPINE_1, tail=Joint.SPINE_2, reference_axis="forward"
    ),
    Bone.SPINE_2: BoneSpec(
        head=Joint.SPINE_2, tail=Joint.SPINE_3, reference_axis="forward"
    ),
    Bone.SPINE_3: BoneSpec(
        head=Joint.SPINE_3, tail=Joint.NECK, reference_axis="forward"
    ),
    Bone.NECK: BoneSpec(head=Joint.NECK, tail=Joint.HEAD, reference_axis="forward"),
    Bone.HEAD: BoneSpec(head=Joint.HEAD, tail=Joint.HEAD_TOP, reference_axis="forward"),
    **_sided("L"),
    **_sided("R"),
}

# Joint pairs drawn in previews that are not bones themselves.
CONNECTORS: tuple[tuple[Joint, Joint], ...] = (
    (Joint.PELVIS, Joint.HIP_L),
    (Joint.PELVIS, Joint.HIP_R),
    (Joint.SPINE_3, Joint.CLAVICLE_L),
    (Joint.SPINE_3, Joint.CLAVICLE_R),
)


@dataclass(frozen=True, kw_only=True)
class BoneFrame:
    """A posed bone in world space.

    `reference` is where the bone's reference axis (see `BoneSpec`) points after
    posing. It is a unit vector perpendicular to `direction`.
    """

    direction: Vec3
    reference: Vec3


@dataclass(frozen=True, kw_only=True)
class Pose:
    bones: Mapping[Bone, BoneFrame]
    # World positions with the pelvis at the origin, for previews.
    joints: Mapping[Joint, Vec3]
    # Pixel positions in the upright photo, for overlays.
    image_points: Mapping[Joint, Vec2]
    image_size: tuple[int, int]


def out_of_frame_joints(pose: Pose) -> list[Joint]:
    width, height = pose.image_size
    return [
        joint
        for joint, (x, y) in pose.image_points.items()
        if not (0 <= x < width and 0 <= y < height)
    ]


def preview_edges() -> list[tuple[Joint, Joint]]:
    return [(spec.head, spec.tail) for spec in SKELETON.values()] + list(CONNECTORS)


def pose_file(pose: Pose, *, backend: str, manikin_version: str) -> dict[str, Any]:
    """The JSON document saved as `pose.json`."""
    return {
        "format": POSE_FORMAT,
        "version": POSE_FORMAT_VERSION,
        "manikin_version": manikin_version,
        "backend": backend,
        "bones": {
            bone.value: {
                "direction": _rounded(frame.direction),
                "reference": _rounded(frame.reference),
                "reference_axis": SKELETON[bone].reference_axis,
            }
            for bone, frame in pose.bones.items()
        },
    }


def _rounded(v: Vec3) -> list[float]:
    return [round(c, 6) for c in v]


@dataclass(frozen=True)
class EstimateError:
    message: str


class PoseBackend(Protocol):
    """Estimates poses from photos. Implementations must be thread-safe."""

    name: str

    @property
    def loaded(self) -> bool: ...

    def estimate(self, image: np.ndarray) -> Pose | EstimateError:
        """Estimate the pose of the person in an upright RGB image."""
        ...

    def unload_if_idle(self) -> bool:
        """Free the model if it has been idle long enough; return True if freed."""
        ...
