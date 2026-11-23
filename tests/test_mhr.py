import math

import numpy as np
import pytest

from manikin.mhr import (
    MHR_JOINTS,
    MHR_PARENTS,
    TOE_TIP_KEYPOINTS,
    MhrState,
    check_skeleton,
    pose_from_mhr,
    project,
)
from manikin.pose import SKELETON, Bone, Joint

# A standing figure in the MHR frame: +Y up, facing +Z, subject's left at +X.
CENTER = {
    "root": (0, 0.92, 0),
    "c_spine0": (0, 1.0, -0.02),
    "c_spine1": (0, 1.1, -0.02),
    "c_spine2": (0, 1.2, -0.01),
    "c_spine3": (0, 1.35, 0),
    "c_neck": (0, 1.5, 0),
    "c_head": (0, 1.6, 0.02),
    "c_head_null": (0, 1.8, 0.02),
}
SIDE = {
    "clavicle": (0.03, 1.42, 0),
    "uparm": (0.18, 1.42, 0),
    "lowarm": (0.35, 1.2, 0),
    "wrist_twist": (0.5, 1.0, 0),
    "wrist": (0.5, 1.0, 0),
    "middle1": (0.55, 0.93, 0),
    "upleg": (0.09, 0.9, 0),
    "lowleg": (0.1, 0.5, 0),
    "foot": (0.1, 0.1, 0),
    "talocrural": (0.1, 0.1, 0),
    "subtalar": (0.1, 0.07, 0.02),
    "transversetarsal": (0.1, 0.05, 0.06),
    "ball": (0.1, 0.02, 0.12),
}
TOE_TIP = (0.1, 0.02, 0.18)


def rest_state() -> MhrState:
    joints = np.zeros((127, 3))
    for name, p in CENTER.items():
        joints[MHR_JOINTS[name]] = p
    for name, (x, y, z) in SIDE.items():
        joints[MHR_JOINTS[f"l_{name}"]] = (x, y, z)
        joints[MHR_JOINTS[f"r_{name}"]] = (-x, y, z)
    keypoints = np.zeros((70, 3))
    keypoints[TOE_TIP_KEYPOINTS[Joint.TOE_TIP_L]] = TOE_TIP
    keypoints[TOE_TIP_KEYPOINTS[Joint.TOE_TIP_R]] = (-TOE_TIP[0], *TOE_TIP[1:])
    rotations = np.tile(np.eye(3), (127, 1, 1))
    return MhrState(joints=joints, rotations=rotations, keypoints=keypoints)


def rotation(axis: np.ndarray, degrees: float) -> np.ndarray:
    axis = axis / np.linalg.norm(axis)
    x, y, z = axis
    k = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])
    a = math.radians(degrees)
    result: np.ndarray = np.eye(3) + math.sin(a) * k + (1 - math.cos(a)) * k @ k
    return result


def rotated(state: MhrState, r: np.ndarray, *, joints: list[str] | None) -> MhrState:
    """Rotate the named joints by r about the first one's position.

    With `joints=None`, rotate the whole body (and keypoints) about the root.
    """
    names = (
        ["root", *(n for n in MHR_JOINTS if n != "root")] if joints is None else joints
    )
    indices = [MHR_JOINTS[name] for name in names]
    pivot = state.joints[indices[0]].copy()
    positions = state.joints.copy()
    rotations = state.rotations.copy()
    for i in indices:
        positions[i] = pivot + r @ (state.joints[i] - pivot)
        rotations[i] = r @ state.rotations[i]
    keypoints = state.keypoints
    if joints is None:
        keypoints = pivot + (state.keypoints - pivot) @ r.T
    return MhrState(joints=positions, rotations=rotations, keypoints=keypoints)


def estimate(state: MhrState):  # type: ignore[no-untyped-def]
    return pose_from_mhr(
        posed=state, rest=rest_state(), image_points={}, image_size=(100, 100)
    )


def test_rest_pose_in_blender_axes() -> None:
    pose = estimate(rest_state())
    assert pose.joints[Joint.PELVIS] == (0.0, 0.0, 0.0)
    # Subject's left is +X, up is +Z, forward is -Y.
    assert pose.joints[Joint.ELBOW_L][0] > 0.3
    assert pose.joints[Joint.HEAD_TOP][2] > 0.8
    assert pose.joints[Joint.TOE_TIP_L][1] < -0.1
    pelvis = pose.bones[Bone.PELVIS]
    assert pelvis.direction == pytest.approx((0, 0, 1))
    assert pelvis.reference == pytest.approx((0, -1, 0))
    assert pose.bones[Bone.FOOT_L].reference[2] > 0.8  # Feet use "up".


def test_frames_are_orthonormal() -> None:
    pose = estimate(rest_state())
    assert set(pose.bones) == set(SKELETON)
    for frame in pose.bones.values():
        d, r = np.array(frame.direction), np.array(frame.reference)
        assert np.linalg.norm(d) == pytest.approx(1)
        assert np.linalg.norm(r) == pytest.approx(1)
        assert np.dot(d, r) == pytest.approx(0, abs=1e-9)


def test_camera_yaw_is_removed_and_lean_kept() -> None:
    rest = estimate(rest_state())
    turned = rotated(rest_state(), rotation(np.array([0, 1.0, 0]), 70), joints=None)
    turned_pose = estimate(turned)
    for bone in SKELETON:
        assert turned_pose.bones[bone].direction == pytest.approx(
            rest.bones[bone].direction, abs=1e-9
        )

    leaning = rotated(rest_state(), rotation(np.array([1.0, 0, 0]), 20), joints=None)
    pelvis = estimate(leaning).bones[Bone.PELVIS]
    assert math.degrees(math.acos(pelvis.direction[2])) == pytest.approx(20)


def test_upper_arm_twist_moves_reference_only() -> None:
    state = rest_state()
    axis = state.joints[MHR_JOINTS["l_lowarm"]] - state.joints[MHR_JOINTS["l_uparm"]]
    arm = ["l_uparm", "l_lowarm", "l_wrist_twist", "l_wrist", "l_middle1"]
    twisted = estimate(rotated(state, rotation(axis, 90), joints=arm))
    rest = estimate(state)
    before, after = rest.bones[Bone.UPPER_ARM_L], twisted.bones[Bone.UPPER_ARM_L]
    assert after.direction == pytest.approx(before.direction, abs=1e-9)
    angle = math.degrees(math.acos(np.dot(before.reference, after.reference)))
    assert angle == pytest.approx(90)


def test_check_skeleton() -> None:
    parents = np.full(127, -1)
    for child, parent in MHR_PARENTS.items():
        parents[MHR_JOINTS[child]] = MHR_JOINTS[parent]
    assert check_skeleton(parents) is None
    parents[MHR_JOINTS["l_lowleg"]] = MHR_JOINTS["root"]
    error = check_skeleton(parents)
    assert error is not None and "l_lowleg" in error


def test_project_center() -> None:
    points = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
    pixels = project(
        points, focal_length=100, cam_t=np.array([0, 0, 10.0]), image_size=(200, 100)
    )
    assert pixels.tolist() == [[100, 50], [110, 50]]
