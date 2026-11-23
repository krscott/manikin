# SAM 3D Body as the pose estimation backend

Poses must be usable in commercially sold games, which rules out SMPL-based
models. Of the commercial-safe options, we chose SAM 3D Body (ViT-H checkpoint,
PyTorch, body-only inference, with no detector or field-of-view estimator) over
MediaPipe Pose Landmarker Heavy.

SAM 3D Body outputs real joint rotations, including twist, neck, head and feet,
and it runs on the GPU.

We rejected MediaPipe for four reasons:

- Its world landmarks are 33 points with depth that is "up to scale", so bone
  twist and head orientation would have to be guessed.
- Its GPU delegate failed on the RTX 4080 SUPER.
- Its PyPI build sends usage telemetry that cannot be disabled.
- It is not in nixpkgs.

## Consequences

- The checkpoints are under the SAM License. It allows commercial use of
  outputs but forbids activities subject to ITAR and end uses prohibited by
  trade controls (such as military, nuclear, espionage, or gun and
  illegal-weapon uses), and Meta can change it unilaterally. The project owner reviewed and accepted these
  terms.
- The checkpoints are gated on Hugging Face and approved manually, so they
  live outside the Nix store and are downloaded by hand.
- ViT-H was chosen over DINOv3 because accuracy is nearly identical and ViT-H
  avoids both a `torch.hub` network fetch at load time and a second custom
  license.
- The rest of the app depends only on the backend-neutral Pose type, so
  replacing the backend means replacing `SamBackend` and its MHR conversion.
