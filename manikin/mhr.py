"""Convert Momentum Human Rig (MHR) skeleton states into a backend-neutral Pose.

MHR states here use the MHR frame: +X image right, +Y up, +Z toward the camera.
A subject facing the camera has their left side at +X. Units are meters.
"""

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from manikin.pose import SKELETON, Bone, BoneFrame, Joint, Pose, Vec2, Vec3

type Array = NDArray[np.float64]

# Indices of the MHR joints manikin uses, with their expected parents.
MHR_JOINTS: Mapping[str, int] = {
    "root": 1,
    "l_upleg": 2,
    "l_lowleg": 3,
    "l_foot": 4,
    "l_talocrural": 5,
    "l_subtalar": 6,
    "l_transversetarsal": 7,
    "l_ball": 8,
    "r_upleg": 18,
    "r_lowleg": 19,
    "r_foot": 20,
    "r_talocrural": 21,
    "r_subtalar": 22,
    "r_transversetarsal": 23,
    "r_ball": 24,
    "c_spine0": 34,
    "c_spine1": 35,
    "c_spine2": 36,
    "c_spine3": 37,
    "r_clavicle": 38,
    "r_uparm": 39,
    "r_lowarm": 40,
    "r_wrist_twist": 41,
    "r_wrist": 42,
    "r_middle1": 52,
    "l_clavicle": 74,
    "l_uparm": 75,
    "l_lowarm": 76,
    "l_wrist_twist": 77,
    "l_wrist": 78,
    "l_middle1": 88,
    "c_neck": 110,
    "c_head": 113,
    "c_head_null": 126,
}

MHR_PARENTS: Mapping[str, str] = {
    "c_spine0": "root",
    "c_spine1": "c_spine0",
    "c_spine2": "c_spine1",
    "c_spine3": "c_spine2",
    "c_neck": "c_spine3",
    "c_head": "c_neck",
    "c_head_null": "c_head",
    **{
        f"{s}_{child}": f"{s}_{parent}" if parent != "root" else "root"
        for s in ("l", "r")
        for child, parent in (
            ("upleg", "root"),
            ("lowleg", "upleg"),
            ("foot", "lowleg"),
            ("talocrural", "foot"),
            ("subtalar", "talocrural"),
            ("transversetarsal", "subtalar"),
            ("ball", "transversetarsal"),
            ("uparm", "clavicle"),
            ("lowarm", "uparm"),
            ("wrist_twist", "lowarm"),
            ("wrist", "wrist_twist"),
            ("middle1", "wrist"),
        )
    },
    "l_clavicle": "c_spine3",
    "r_clavicle": "c_spine3",
}

# Indices into the MHR 70-keypoint set.
TOE_TIP_KEYPOINTS: Mapping[Joint, int] = {Joint.TOE_TIP_L: 15, Joint.TOE_TIP_R: 18}


def _sided_joints(side: str, s: str) -> dict[Joint, str]:
    return {
        Joint(f"clavicle.{side}"): f"{s}_clavicle",
        Joint(f"shoulder.{side}"): f"{s}_uparm",
        Joint(f"elbow.{side}"): f"{s}_lowarm",
        Joint(f"wrist.{side}"): f"{s}_wrist",
        Joint(f"knuckles.{side}"): f"{s}_middle1",
        Joint(f"hip.{side}"): f"{s}_upleg",
        Joint(f"knee.{side}"): f"{s}_lowleg",
        Joint(f"ankle.{side}"): f"{s}_foot",
        Joint(f"ball.{side}"): f"{s}_ball",
    }


# Pose joints taken from MHR skeleton joints. Toe tips come from keypoints.
JOINT_SOURCES: Mapping[Joint, str] = {
    Joint.PELVIS: "root",
    Joint.SPINE_0: "c_spine0",
    Joint.SPINE_1: "c_spine1",
    Joint.SPINE_2: "c_spine2",
    Joint.SPINE_3: "c_spine3",
    Joint.NECK: "c_neck",
    Joint.HEAD: "c_head",
    Joint.HEAD_TOP: "c_head_null",
    **_sided_joints("L", "l"),
    **_sided_joints("R", "r"),
}


def _sided_frames(side: str, s: str) -> dict[Bone, str]:
    return {
        Bone(f"shoulder.{side}"): f"{s}_clavicle",
        Bone(f"upper_arm.{side}"): f"{s}_uparm",
        # Forearm twist lives on the wrist_twist joint.
        Bone(f"forearm.{side}"): f"{s}_wrist_twist",
        Bone(f"hand.{side}"): f"{s}_wrist",
        Bone(f"thigh.{side}"): f"{s}_upleg",
        # Lower-leg twist lives on the foot (ankle) joint.
        Bone(f"shin.{side}"): f"{s}_foot",
        Bone(f"foot.{side}"): f"{s}_transversetarsal",
        Bone(f"toe.{side}"): f"{s}_ball",
    }


# MHR joint whose global rotation carries each bone's twist.
FRAME_SOURCES: Mapping[Bone, str] = {
    Bone.PELVIS: "root",
    Bone.SPINE_0: "c_spine0",
    Bone.SPINE_1: "c_spine1",
    Bone.SPINE_2: "c_spine2",
    Bone.SPINE_3: "c_spine3",
    Bone.NECK: "c_neck",
    Bone.HEAD: "c_head",
    **_sided_frames("L", "l"),
    **_sided_frames("R", "r"),
}

_UP = np.array([0.0, 1.0, 0.0])
_FORWARD = np.array([0.0, 0.0, 1.0])

# MHR frame -> Blender world: (x, y, z) -> (x, -z, y).
_TO_BLENDER = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]])


@dataclass(frozen=True, kw_only=True)
class MhrState:
    """One MHR skeleton state in the MHR frame."""

    joints: Array  # (127, 3) positions
    rotations: Array  # (127, 3, 3) global rotations
    keypoints: Array  # (70, 3) positions


def check_skeleton(parents: Array) -> str | None:
    """Return an error if `parents` is not the MHR skeleton manikin expects."""
    for child, parent in MHR_PARENTS.items():
        actual = int(parents[MHR_JOINTS[child]])
        if actual != MHR_JOINTS[parent]:
            return (
                f"Unexpected MHR skeleton: joint {child} has parent index {actual}, "
                f"expected {MHR_JOINTS[parent]} ({parent})"
            )
    return None


def joint_positions(state: MhrState) -> dict[Joint, Array]:
    positions = {
        joint: state.joints[MHR_JOINTS[name]] for joint, name in JOINT_SOURCES.items()
    }
    for joint, index in TOE_TIP_KEYPOINTS.items():
        positions[joint] = state.keypoints[index]
    return positions


def pose_from_mhr(
    *,
    posed: MhrState,
    rest: MhrState,
    image_points: Mapping[Joint, Vec2],
    image_size: tuple[int, int],
) -> Pose:
    posed_joints = joint_positions(posed)
    rest_joints = joint_positions(rest)

    bones: dict[Bone, tuple[Array, Array]] = {}
    for bone, spec in SKELETON.items():
        frame = MHR_JOINTS[FRAME_SOURCES[bone]]
        delta = posed.rotations[frame] @ rest.rotations[frame].T
        if bone == Bone.PELVIS:
            rest_direction = _UP
            direction = delta @ _UP
        else:
            rest_direction = _unit(rest_joints[spec.tail] - rest_joints[spec.head])
            direction = _unit(posed_joints[spec.tail] - posed_joints[spec.head])
        axis = _FORWARD if spec.reference_axis == "forward" else _UP
        rest_reference = _perpendicular(axis, rest_direction)
        reference = _perpendicular(delta @ rest_reference, direction)
        bones[bone] = (direction, reference)

    pelvis_forward = _TO_BLENDER @ bones[Bone.PELVIS][1]
    to_world = _face_forward(pelvis_forward) @ _TO_BLENDER
    pelvis = posed_joints[Joint.PELVIS]
    return Pose(
        bones={
            bone: BoneFrame(
                direction=_vec3(to_world @ direction),
                reference=_vec3(to_world @ reference),
            )
            for bone, (direction, reference) in bones.items()
        },
        joints={
            joint: _vec3(to_world @ (position - pelvis))
            for joint, position in posed_joints.items()
        },
        image_points=image_points,
        image_size=image_size,
    )


def project(
    points: Array, *, focal_length: float, cam_t: Array, image_size: tuple[int, int]
) -> Array:
    """Project MHR-frame points into pixels with SAM 3D Body's default camera."""
    width, height = image_size
    camera = points * np.array([1.0, -1.0, -1.0]) + cam_t
    center = np.array([width / 2, height / 2])
    projected: Array = focal_length * camera[:, :2] / camera[:, 2:3] + center
    return projected


def _face_forward(pelvis_forward: Array) -> Array:
    """Rotation about +Z that turns the pelvis to face -Y.

    The subject's yaw relative to the camera is incidental, so it is dropped.
    Lean is kept. If the pelvis faces straight up or down, yaw is undefined and
    left unchanged.
    """
    x, y = float(pelvis_forward[0]), float(pelvis_forward[1])
    if x * x + y * y < 1e-4:
        return np.eye(3)
    angle = np.arctan2(x, -y)  # Angle from -Y toward +X.
    c, s = np.cos(angle), np.sin(angle)
    return np.array([[c, s, 0.0], [-s, c, 0.0], [0.0, 0.0, 1.0]])


def _unit(v: Array) -> Array:
    unit: Array = v / np.linalg.norm(v)
    return unit


def _perpendicular(v: Array, direction: Array) -> Array:
    return _unit(v - np.dot(v, direction) * direction)


def _vec3(v: Array) -> Vec3:
    return (float(v[0]), float(v[1]), float(v[2]))
