# manikin

Turns a phone photo of a person into a still pose that can be applied to a
Blender Rigify character.

## Language

**Pose**:
The static body configuration of one person, estimated from one photo. It does not depend on the estimation backend.
_Avoid_: animation, frame, landmarks

**Backend**:
The pose estimation model that turns a photo into a pose.
_Avoid_: estimator, detector, model (when meaning the whole backend)

**Preview**:
The view of a pose shown on the phone, so the user can choose Accept or Retake.

**Accept**:
The user's confirmation that a previewed pose is correct, which saves it.

**Retake**:
The user's rejection of a previewed pose. It discards the pose and asks for a new photo.

**Saved pose**:
What Accept writes: the original photo, the pose file, and an overlay image, kept together under one name.
_Avoid_: export, capture, take

**Target rig**:
The Rigify-generated armature of a character that a saved pose is applied to.
_Avoid_: skeleton, armature, metarig
