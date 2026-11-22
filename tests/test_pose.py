from dataclasses import replace

from manikin.pose import (
    POSE_FORMAT,
    POSE_FORMAT_VERSION,
    SKELETON,
    Joint,
    Pose,
    out_of_frame_joints,
    pose_file,
    preview_edges,
)


def test_pose_file(sample_pose: Pose) -> None:
    document = pose_file(sample_pose, backend="test", manikin_version="1.2.3")
    assert document["format"] == POSE_FORMAT
    assert document["version"] == POSE_FORMAT_VERSION
    assert document["manikin_version"] == "1.2.3"
    assert set(document["bones"]) == {bone.value for bone in SKELETON}
    assert document["bones"]["foot.L"] == {
        "direction": [0.0, 0.0, 1.0],
        "reference": [0.0, -1.0, 0.0],
        "reference_axis": "up",
    }


def test_out_of_frame(sample_pose: Pose) -> None:
    assert out_of_frame_joints(sample_pose) == []
    points = dict(sample_pose.image_points)
    points[Joint.ANKLE_L] = (10.0, 48.0)
    points[Joint.WRIST_R] = (-1.0, 5.0)
    moved = replace(sample_pose, image_points=points)
    assert out_of_frame_joints(moved) == [Joint.ANKLE_L, Joint.WRIST_R]


def test_preview_edges_use_known_joints() -> None:
    edges = preview_edges()
    assert {j for edge in edges for j in edge} == set(Joint)
