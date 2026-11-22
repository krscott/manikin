"""Runs inside headless Blender for tests/test_blender.py.

Usage: blender -b --factory-startup --python blender_driver.py -- ADDON POSE OUT
Generates a rig from Rigify's human metarig, applies POSE through the add-on's
import operator, and writes measured errors to OUT as JSON.
"""

import importlib.util
import json
import math
import sys
from pathlib import Path

import bpy


def main() -> None:
    addon_path, pose_path, out_path = map(Path, sys.argv[sys.argv.index("--") + 1 :])
    bpy.ops.preferences.addon_enable(module="rigify")
    bpy.ops.object.armature_human_metarig_add()
    bpy.ops.pose.rigify_generate()
    rig = next(o for o in bpy.data.objects if "rig_id" in o.data)
    bpy.context.view_layer.objects.active = rig

    spec = importlib.util.spec_from_file_location("manikin_rigify", addon_path)
    assert spec is not None and spec.loader is not None
    addon = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(addon)
    addon.register()

    result = bpy.ops.import_anim.manikin_pose(
        filepath=str(pose_path), insert_keyframe=True
    )
    document = addon.load_pose_file(pose_path)

    errors = {}
    for bone, spec in document["bones"].items():
        target = addon._Target(rig, bone, spec)
        current = target.current_frame(rig)
        errors[bone] = {
            name: math.degrees(target.frame.col[i].angle(current.col[i], 0.0))
            for i, name in enumerate(("direction", "reference"))
        }

    action = rig.animation_data.action if rig.animation_data else None
    out_path.write_text(
        json.dumps(
            {
                "operator": sorted(result),
                "errors": errors,
                "ik_fk": {
                    name: rig.pose.bones[name]["IK_FK"] for name in addon.IK_FK_HOLDERS
                },
                "keyed": (
                    action is not None and len(action.fcurves) > 0
                    if hasattr(action, "fcurves")
                    else action is not None
                ),
            }
        )
    )


main()
