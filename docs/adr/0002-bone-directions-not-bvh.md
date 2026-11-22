# Export bone directions for a Blender script, not BVH

A saved pose is a versioned `pose.json` holding character-space bone directions,
twist reference vectors and pelvis orientation. A bundled single-file Blender
add-on aims the FK controls of the active Rigify rig at those directions.

We rejected BVH, even though it is the usual mocap format, because Blender has
no built-in retargeting. Applying a BVH to Rigify needs a matching rest pose, a
bone map, and a third-party or paid retargeter, which is too much for one still
pose, and the BVH's own proportions add error. We also rejected pose assets:
they can only be authored inside Blender, and they store bone-local values
that do not transfer between rigs with different rest poses or bone roll.

Aiming bones in the rig's own axes keeps each character's own bone lengths,
rest pose and roll.
