# SPDX-License-Identifier: AGPL-3.0-or-later
"""Apply a pose saved by manikin to a Rigify-generated rig.

Install from Blender: Edit > Preferences > Add-ons > Install from Disk.
Then select the generated rig and use File > Import > manikin pose (.json).

Each pose bone stores a direction and a twist reference in character space
(+X the character's left, -Y forward, +Z up), read here as the rig's armature
space. For every bone, the add-on builds the same frame from the rig's own rest
pose, and rotates the matching FK control by the difference. The rig keeps its
own proportions, rest pose, and bone roll.
"""

import json
import math
from pathlib import Path
from typing import Any

import bpy
from bpy.props import BoolProperty, StringProperty
from bpy_extras.io_utils import ImportHelper
from mathutils import Matrix, Vector

bl_info = {
    "name": "manikin pose importer",
    "author": "manikin",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "File > Import > manikin pose (.json)",
    "description": "Apply a pose captured by manikin to a Rigify rig",
    "category": "Import-Export",
}

POSE_FORMAT = "manikin-pose"
POSE_FORMAT_VERSION = 1

# Pose bone -> (FK control, first and last bone of the span that shows the body
# part). The span's first bone also carries its twist. The pelvis has no span:
# its rest direction is up, and the control carries its twist.
#
# Spine ORG bones are rigidly parented to tweak bones, while the visible spine is
# the DEF chain stretched between tweaks, so the spine is measured on DEF bones.
_TORSO: dict[str, tuple[str, tuple[str, str] | None]] = {
    "pelvis": ("torso", None),
    "spine_0": ("spine_fk", ("DEF-spine", "DEF-spine")),
    "spine_1": ("spine_fk.001", ("DEF-spine.001", "DEF-spine.001")),
    "spine_2": ("spine_fk.002", ("DEF-spine.002", "DEF-spine.002")),
    "spine_3": ("spine_fk.003", ("DEF-spine.003", "DEF-spine.003")),
    "neck": ("neck", ("ORG-spine.004", "ORG-spine.005")),
    "head": ("head", ("ORG-spine.006", "ORG-spine.006")),
}
_LIMB_CONTROLS = {
    "shoulder": "shoulder",
    "upper_arm": "upper_arm_fk",
    "forearm": "forearm_fk",
    "hand": "hand_fk",
    "thigh": "thigh_fk",
    "shin": "shin_fk",
    "foot": "foot_fk",
    "toe": "toe_fk",
}
CONTROLS: dict[str, tuple[str, tuple[str, str] | None]] = {
    **_TORSO,
    **{
        f"{bone}.{side}": (f"{control}.{side}", (f"ORG-{bone}.{side}",) * 2)
        for side in ("L", "R")
        for bone, control in _LIMB_CONTROLS.items()
    },
}

# Bones holding Rigify's IK/FK switch; 1.0 is FK.
IK_FK_HOLDERS = (
    "upper_arm_parent.L",
    "upper_arm_parent.R",
    "thigh_parent.L",
    "thigh_parent.R",
)

_AXES = {"forward": Vector((0.0, -1.0, 0.0)), "up": Vector((0.0, 0.0, 1.0))}


class PoseError(Exception):
    """A problem with the pose file or the rig, shown to the user."""


def load_pose_file(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        raise PoseError(f"Cannot read {path}: {e}") from e
    if not isinstance(document, dict) or document.get("format") != POSE_FORMAT:
        raise PoseError(f"{path} is not a manikin pose file")
    version = document.get("version")
    if version != POSE_FORMAT_VERSION:
        raise PoseError(
            f"{path} uses pose format version {version}, but this add-on reads "
            f"version {POSE_FORMAT_VERSION}. Run `manikin blender-script` from the "
            f"manikin that saved it (version {document.get('manikin_version')}) "
            "and reinstall the add-on."
        )
    bones = document.get("bones")
    if not isinstance(bones, dict):
        raise PoseError(f"{path} has no bones")
    missing = sorted(set(CONTROLS) - set(bones))
    if missing:
        raise PoseError(f"{path} is missing bones: {', '.join(missing)}")
    for bone in CONTROLS:
        if not _valid_bone(bones[bone]):
            raise PoseError(f"{path} has an invalid entry for bone {bone}")
    return document


def _valid_bone(spec: Any) -> bool:
    def vector(value: Any) -> bool:
        return (
            isinstance(value, list)
            and len(value) == 3
            and all(isinstance(v, (int, float)) and math.isfinite(v) for v in value)
            and any(v != 0 for v in value)
        )

    return (
        isinstance(spec, dict)
        and vector(spec.get("direction"))
        and vector(spec.get("reference"))
        and spec.get("reference_axis") in _AXES
    )


def apply_pose(
    rig: bpy.types.Object, document: dict[str, Any], *, insert_keyframe: bool
) -> dict[str, float]:
    """Pose the rig's FK controls; return each bone's remaining error in degrees.

    Each control is rotated by the difference between where its bone points now
    and where it should point, repeated until the bones settle. Rigify moves some
    bones (such as the middle of the spine) through tweak bones rather than
    rigidly, so a single step is not always exact.
    """
    _check_rig(rig)
    targets = {
        bone: _Target(rig, bone, spec)
        for bone, spec in document["bones"].items()
        if bone in CONTROLS
    }

    for holder in IK_FK_HOLDERS:
        pose_bone = rig.pose.bones.get(holder)
        if pose_bone is not None and "IK_FK" in pose_bone:
            pose_bone["IK_FK"] = 1.0
            if insert_keyframe:
                pose_bone.keyframe_insert(data_path='["IK_FK"]')
    bpy.context.view_layer.update()

    # Parents first, so each control's parent is already close to its final pose.
    def depth(target: _Target) -> int:
        return len(rig.pose.bones[target.control].parent_recursive)

    ordered = sorted(targets.values(), key=depth)
    for _ in range(_MAX_PASSES):
        worst = 0.0
        for target in ordered:
            correction = target.frame @ target.current_frame(rig).transposed()
            angle = correction.to_quaternion().angle
            worst = max(worst, angle)
            if angle > _TOLERANCE:
                pose_bone = rig.pose.bones[target.control]
                _set_rotation(rig, pose_bone, correction @ pose_bone.matrix.to_3x3())
                bpy.context.view_layer.update()
        if worst <= _TOLERANCE:
            break

    if insert_keyframe:
        for target in ordered:
            pose_bone = rig.pose.bones[target.control]
            pose_bone.keyframe_insert(data_path=_rotation_path(pose_bone))

    return {
        bone: math.degrees(
            (target.frame @ target.current_frame(rig).transposed())
            .to_quaternion()
            .angle
        )
        for bone, target in targets.items()
    }


_MAX_PASSES = 8
_TOLERANCE = math.radians(0.05)


class _Target:
    """Where one pose bone should point, and how to measure where it points now."""

    def __init__(self, rig: bpy.types.Object, bone: str, spec: dict[str, Any]):
        self.control, self.span = CONTROLS[bone]
        direction = _vector(spec["direction"])
        self.frame = _frame(direction, _vector(spec["reference"]))
        self.rest_direction = _rest_direction(rig, self.span)
        axis = _AXES[spec["reference_axis"]]
        self.rest_reference = _perpendicular(axis, self.rest_direction, bone=bone)
        # The bone whose rotation carries the twist: the span's first ORG bone,
        # or the control itself for the pelvis.
        self.measured = self.span[0] if self.span else self.control

    def current_frame(self, rig: bpy.types.Object) -> Matrix:
        rest = rig.data.bones[self.measured].matrix_local.to_3x3()
        rotation = rig.pose.bones[self.measured].matrix.to_3x3() @ rest.inverted()
        if self.span is None:
            direction = rotation @ self.rest_direction
        else:
            first, last = self.span
            direction = rig.pose.bones[last].tail - rig.pose.bones[first].head
        return _frame(direction, rotation @ self.rest_reference)


def _check_rig(rig: bpy.types.Object | None) -> None:
    if rig is None or rig.type != "ARMATURE" or "rig_id" not in rig.data:
        raise PoseError("Select a Rigify-generated rig (not the metarig) first")
    names = {control for control, _ in CONTROLS.values()} | {
        name for _, span in CONTROLS.values() if span for name in span
    }
    missing = sorted(name for name in names if name not in rig.pose.bones)
    if missing:
        raise PoseError(
            "The rig is missing bones from Rigify's human metarig: "
            + ", ".join(missing)
        )


def _rest_direction(rig: bpy.types.Object, span: tuple[str, str] | None) -> Vector:
    if span is None:
        return _AXES["up"].copy()
    first, last = span
    bones = rig.data.bones
    return (bones[last].tail_local - bones[first].head_local).normalized()


def _set_rotation(
    rig: bpy.types.Object, pose_bone: bpy.types.PoseBone, rotation: Matrix
) -> None:
    """Give `pose_bone` this armature-space rotation, keeping its position."""
    target = Matrix.Translation(pose_bone.matrix.translation) @ rotation.to_4x4()
    local = rig.convert_space(
        pose_bone=pose_bone, matrix=target, from_space="POSE", to_space="LOCAL"
    )
    quaternion = local.to_quaternion()
    mode = pose_bone.rotation_mode
    if mode == "QUATERNION":
        if pose_bone.rotation_quaternion.dot(quaternion) < 0:
            quaternion.negate()
        pose_bone.rotation_quaternion = quaternion
    elif mode == "AXIS_ANGLE":
        axis, angle = quaternion.to_axis_angle()
        pose_bone.rotation_axis_angle = (angle, *axis)
    else:
        pose_bone.rotation_euler = quaternion.to_euler(mode, pose_bone.rotation_euler)


def _rotation_path(pose_bone: bpy.types.PoseBone) -> str:
    if pose_bone.rotation_mode == "QUATERNION":
        return "rotation_quaternion"
    if pose_bone.rotation_mode == "AXIS_ANGLE":
        return "rotation_axis_angle"
    return "rotation_euler"


def _frame(direction: Vector, reference: Vector) -> Matrix:
    """Orthonormal basis: direction, reference made perpendicular, their cross."""
    d = direction.normalized()
    r = (reference - reference.dot(d) * d).normalized()
    return Matrix((d, r, d.cross(r))).transposed()


def _perpendicular(v: Vector, direction: Vector, *, bone: str) -> Vector:
    result = v - v.dot(direction) * direction
    if result.length < 1e-3:
        raise PoseError(f"The rig's {bone} rest direction is parallel to its axis")
    return result.normalized()


def _vector(values: Any) -> Vector:
    return Vector([float(v) for v in values])


class IMPORT_OT_manikin_pose(bpy.types.Operator, ImportHelper):
    """Apply a manikin pose to the selected Rigify rig"""

    bl_idname = "import_anim.manikin_pose"
    bl_label = "Import manikin pose"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".json"
    filter_glob: StringProperty(default="*.json", options={"HIDDEN"})  # type: ignore
    insert_keyframe: BoolProperty(  # type: ignore
        name="Insert keyframe",
        description="Key the posed controls and IK/FK switches on the current frame",
        default=False,
    )

    def execute(self, context: bpy.types.Context) -> set[str]:
        try:
            document = load_pose_file(Path(self.filepath))
            errors = apply_pose(
                context.active_object, document, insert_keyframe=self.insert_keyframe
            )
        except PoseError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        worst = max(errors, key=errors.__getitem__)
        self.report(
            {"INFO"},
            f"Posed {len(errors)} bones; largest remaining error "
            f"{errors[worst]:.1f}° ({worst})",
        )
        return {"FINISHED"}


def _menu(self: bpy.types.Menu, _: bpy.types.Context) -> None:
    self.layout.operator(IMPORT_OT_manikin_pose.bl_idname, text="manikin pose (.json)")


def register() -> None:
    bpy.utils.register_class(IMPORT_OT_manikin_pose)
    bpy.types.TOPBAR_MT_file_import.append(_menu)


def unregister() -> None:
    bpy.types.TOPBAR_MT_file_import.remove(_menu)
    bpy.utils.unregister_class(IMPORT_OT_manikin_pose)
