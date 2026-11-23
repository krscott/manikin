# Agent guide for manikin

manikin turns a phone photo into a pose for a Blender Rigify rig. See README.md
for usage, GLOSSARY.md for domain terms, and docs/adr/ for key decisions.

## Development environment

Use `nix develop` to enter the development shell. Nix supplies runtime and
development dependencies, including setuptools. Its hooks create `.venv` if
missing, activate it, and install only the local project in editable mode,
without resolving or downloading Python packages. Each worktree has its own
editable installation. Agents can run this themselves; no user restart is needed.
Nix is required: sam-3d-body is packaged only in `nix/sam-3d-body.nix`.

For noninteractive commands, use `nix develop -c <command>`, for example:

```sh
nix develop -c python -m pytest
```

Run Python tools such as pytest and mypy with `python -m <tool>` so they use the
active environment and can find its installed packages.

Run `pyright` directly; Nix supplies it.

## Dependencies

Declare dependencies before installing them:

1. Add runtime dependencies to `pyproject.toml` under `dependencies`, or
   development dependencies under `project.optional-dependencies.dev`.
2. Add corresponding Nix runtime packages to `default.nix`. Add development
   tools needed by the Nix environment to `flake.nix`.
3. Exit and re-enter `nix develop` to load the updated Nix dependencies. To
   refresh package metadata or script entry points in an existing `.venv`, run
   `python -m pip install --no-deps --no-build-isolation -e .` in that shell.

`SAM-EXCEPTION` covers combining manikin only with SAM 3D Body code and
checkpoints. Ask the owner before adding any dependency, model, or runtime
download (such as `torch.hub`) under a non-free or GPL-incompatible license;
this includes switching checkpoints (the DINOv3 checkpoint fetches
DINOv3-licensed code). Do not copy sam-3d-body code into manikin: it stays under
the SAM License.

For libraries without type hints, add available stub packages to development
dependencies. If stubs are unavailable, use a mypy override scoped to the
affected module in `pyproject.toml`.

## Validation

| Check | Command |
|-------|---------|
| Pyright | `pyright` |
| Mypy | `python -m mypy .` |
| Tests | `python -m pytest` |
| GPU (manual) | `just test-gpu` |
| Blender (manual) | `just test-blender` |

`just check` runs the first three. Run the manual tests when changing the pose
math, the backend, or the Blender add-on; CI and `nix flake check` skip them.
The model weights for `just test-gpu` are described under "Model weights" in
the README.

Both type checkers must pass. Keep any necessary type-checking exceptions narrow
and explain why they are needed.

Use pytest fixtures for setup and teardown. Minimize mocks.

## Code style

- Use Python 3.13+ type hints, such as `list[str | None]`. See
  [Python compatibility](#python-compatibility) for the minimum-version policy.
- Keep imports at the top of the file unless a local import is necessary.
- Prefer returning values over raising exceptions. Make failures actionable.
- Use `pathlib.Path` instead of `os.path`.
- Prefer composition over inheritance and keep data easy to inspect, test,
  and serialize.

## Python compatibility

The minimum Python version is 3.13. Choose the oldest interpreter in the locked
nixpkgs whose package set works for both runtime and development dependencies,
and whose CUDA torch is on `cache.nixos-cuda.org` (see below). An interpreter
being present in nixpkgs is not enough.

When raising the minimum, update these together:

- `requires-python` in `pyproject.toml`.
- Black's `target-version`, mypy's `python_version`, and pyright's
  `pythonVersion` in `pyproject.toml`.
- The `pythonOlder` guard in `default.nix`, which rejects unsupported interpreters.
- `pythonMinimum` in `flake.nix`, used by `checks.python-minimum` and
  `cudaCachePaths`.
- The version in this file, in this section and under Code style.
- The "Python compatibility" section of the README.

The README's "Python compatibility" section explains how these settings are used.

## Nix-packaged command

The `-I` added to the `manikin` entry point in `default.nix` is deliberate. See
"Nix command isolation" in the project README before changing it.

## CUDA builds come from the binary cache

`flake.nix` imports nixpkgs with `cudaSupport = true` and the default CUDA
capabilities, which is what `cache.nixos-cuda.org` builds. Changing the nixpkgs
config, CUDA capabilities, or torch overrides changes the derivations and
compiles torch locally for hours. Packages that must stay on cache.nixos.org,
such as Blender for tests, come from `plainPkgs` or plain `nixpkgs#...`.
After `nix flake update`, run `just check-cuda-cache`; keep the old lock if it
reports a miss. `torch-bin` is not an option while it needs a newer CUDA than
nixpkgs provides.

The NixOS module defaults to manikin's own package for the same reason; do not
rebuild manikin against the host's nixpkgs.

## Pose format and Blender add-on

- `manikin/blender/manikin_rigify.py` runs inside Blender's Python. It may only
  import the standard library and Blender modules, and is excluded from mypy and
  pyright because bpy has no stubs in nixpkgs. `tests/blender_driver.py` is the
  same.
- When `pose.json` changes incompatibly, bump `POSE_FORMAT_VERSION` in both
  `manikin/pose.py` and the add-on (`tests/test_cli.py` checks they match), then
  run `just regenerate-pose-fixture` and `just test-blender`.
- Spine ORG bones in a Rigify rig are rigidly parented to tweak bones, so the
  add-on measures the spine on DEF bones. It corrects each control iteratively
  because Rigify's spine controls each move parts of two segments.
