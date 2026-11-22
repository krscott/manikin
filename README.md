# manikin

Capture a pose from a phone photo and apply it to a Blender
[Rigify](https://docs.blender.org/manual/en/latest/addons/rigging/rigify/index.html)
character.

manikin runs on a machine with an NVIDIA GPU and serves a small web page over
[Tailscale](https://tailscale.com). On your phone, take a photo of one person,
check the estimated skeleton, and accept it. manikin saves the photo and a
`pose.json`. A bundled Blender add-on then poses any Rigify rig to match.

Pose estimation uses Meta's
[SAM 3D Body](https://github.com/facebookresearch/sam-3d-body) (ViT-H checkpoint)
locally on the GPU. See [Licensing](#licensing).

## Requirements

- x86_64 Linux with Nix and an NVIDIA GPU (about 4 GB of free VRAM while a
  photo is processed).
- The `cache.nixos-cuda.org` binary cache. Without it, Nix compiles CUDA PyTorch
  locally, which takes hours.
- Tailscale on the GPU machine and the phone.
- Blender 4.2 or newer with Rigify enabled.

## Model weights

The SAM 3D Body checkpoints are gated. Request access at
<https://huggingface.co/facebook/sam-3d-body-vith>. Once approved, download the
pinned revision with a Hugging Face read token:

```sh
nix shell nixpkgs#python3Packages.huggingface-hub -c env HF_TOKEN=hf_... \
  hf download facebook/sam-3d-body-vith \
  --revision f7f4ba4f67739e297f291639afb7c59041745367 \
  --local-dir ~/.local/share/manikin/models/sam-3d-body-vith
```

The download is about 2.4 GB and is not needed again. manikin does not store
the token. If the weights are missing, `manikin serve` prints this command and
exits.

## Usage

```sh
nix run github:krscott/manikin -- serve
```

manikin listens on this machine's tailnet IPv4 address and logs the URL to open
on your phone, such as `http://myhost.example.ts.net:8471/`. `manikin url` prints
the URL with a QR code. The firewall must allow the port on `tailscale0`; the
[NixOS module](#nixos-module) can open it.

On the phone:

1. Tap **Take photo** (or **Choose photo**). Frame one person head to toe.
2. Check the preview: the skeleton drawn over the photo, and an orbitable 3D
   view. Warnings list joints that fall outside the photo.
3. Tap **Accept**, optionally with a name, or **Retake**.

The model loads with the first photo (several seconds) and unloads after
`model_idle_timeout` seconds without photos, freeing GPU memory.

### Applying a pose in Blender

1. Write the add-on with `manikin blender-script`, then install
   `manikin_rigify.py` in Blender via Edit > Preferences > Add-ons > Install
   from Disk.
2. Select a Rigify-generated rig (not the metarig).
3. Use File > Import > manikin pose (.json) and pick a saved `pose.json`.
   Enable **Insert keyframe** to key the pose on the current frame.

The add-on switches the arms and legs to FK and rotates the FK controls, torso,
neck, and head. The rig keeps its own proportions, rest pose, and bone roll. It
keeps the character facing its own forward direction and does not move it, so
adjust height and foot contact by hand. Reinstall the add-on after upgrading
manikin; it refuses `pose.json` versions it does not know.

## Configuration

Settings come from a TOML file, then command-line flags. Without `--config`,
manikin reads `$XDG_CONFIG_HOME/manikin/config.toml` (usually
`~/.config/manikin/config.toml`) if it exists. Unknown keys are errors.

| Key | Default | Meaning |
|-----|---------|---------|
| `out_dir` | `~/manikin/poses` | Where accepted poses are saved |
| `host` | tailnet IPv4 | Address to listen on and use in the URL |
| `port` | `8471` | Port to listen on |
| `model_dir` | `$XDG_DATA_HOME/manikin/models/sam-3d-body-vith` | SAM 3D Body weights |
| `model_idle_timeout` | `600` | Seconds without photos before unloading the model |

```toml
out_dir = "~/blender/poses"
model_idle_timeout = 300
```

## NixOS module

```nix
{
  inputs.manikin.url = "github:krscott/manikin";

  outputs = { nixpkgs, manikin, ... }: {
    nixosConfigurations.myhost = nixpkgs.lib.nixosSystem {
      modules = [
        manikin.nixosModules.default
        {
          services.manikin = {
            enable = true;
            user = "alice";
            openFirewall = true; # Opens the port on tailscale0 only.
            settings.out_dir = "/home/alice/blender/poses";
          };
        }
      ];
    };
  };
}
```

The service runs as `user`, so saved poses and model weights default to that
user's home directory, where a Flatpak Blender can read them. It uses manikin's
own package, built against manikin's locked nixpkgs, so CUDA PyTorch still comes
from the binary cache. `settings` accepts the [configuration](#configuration)
keys.

## Saved poses

Each accepted pose is a directory `<out_dir>/<YYYYMMDD-HHMMSS>[-<name>]/`:

- `photo.jpg` (or `.png`, `.webp`): the photo as uploaded.
- `pose.json`: the pose.
- `overlay.png`: the photo with the estimated skeleton.

`pose.json` describes a character at rest facing -Y with +Z up and +X on the
subject's left, in Blender's axes. The subject's left maps to Rigify's `.L`
bones. Each entry under `bones` has:

- `direction`: the unit vector the bone points along.
- `reference`: where the bone's `reference_axis` (`forward`, the body's -Y, or
  `up`, +Z) points after posing, made perpendicular to `direction`. It fixes the
  bone's twist.

The subject's yaw relative to the camera is removed; lean is kept, assuming the
phone was held roughly level. `version` changes whenever the format changes.

## Limitations

- One person per photo. With several people, the result is unpredictable.
- The whole body should be in the photo; joints outside it are guesses.
- Rigify's spine gives two adjacent segments the same twist source, so spine
  twist can be off by a degree or two.
- Fingers and facial expression are not captured.
- The page is plain HTTP on the tailnet. Browsers mark it "Not secure", which
  does not affect the native camera.

## Licensing

manikin is licensed under the GNU Affero General Public License v3.0 or later;
see `LICENSE`. Third-party parts keep their own licenses:

- SAM 3D Body code and checkpoints: [SAM License](https://github.com/facebookresearch/sam-3d-body/blob/main/LICENSE).
  It allows commercial use, places no restrictions on outputs, and prohibits
  uses related to weapons, military, and ITAR among others. Read it before use.
  Meta may change it.
- The Momentum Human Rig (MHR) model in the checkpoint: Apache 2.0.
- three.js, vendored in `manikin/static/vendor/three`: MIT.
- `tests/data/kungfu.jpg`: CC0; see `tests/data/README.md`.

See `docs/adr/` for why manikin uses SAM 3D Body and its own pose format.

## Development

```sh
nix develop
just check          # mypy, pyright, unit tests
just format
```

Nix supplies all dependencies. sam-3d-body is packaged only in `nix/`, so manual
setup without Nix is not supported. On first use, the shell creates a separate
`.venv` for the checkout and installs only the local project in editable mode,
without resolving or downloading Python packages.

Declare Python dependencies in `pyproject.toml` and the corresponding Nix
packages in `default.nix` (runtime) or `flake.nix` (development tools). Exit and
re-enter `nix develop` after changing Nix dependencies. To refresh package
metadata or script entry points in an existing virtual environment, run:

```sh
python -m pip install --no-deps --no-build-isolation -e .
```

### Manual tests

These need hardware or large downloads, so CI and `nix flake check` skip them:

- `just test-gpu`: runs SAM 3D Body on `tests/data/kungfu.jpg` and compares the
  result with `tests/data/kungfu.pose.json`. Needs the model weights.
  `just regenerate-pose-fixture` rewrites the fixture after an intended change.
- `just test-blender`: generates a rig from Rigify's human metarig in headless
  Blender (from the locked nixpkgs), applies the fixture through the add-on's
  import operator, and checks every bone's direction and twist.

### Updating flake inputs

```sh
nix flake update
just check-cuda-cache
```

`check-cuda-cache` checks that the locked CUDA PyTorch builds are on
`cache.nixos-cuda.org`. If any are missing, keep the previous `flake.lock`.

## Python compatibility

The minimum Python version is 3.13, the oldest with CUDA PyTorch on
`cache.nixos-cuda.org` in the locked nixpkgs.

Black's target controls the syntax it writes; it does not check compatibility.
Mypy and pyright target the minimum version to check standard-library use.
Pyright also checks syntax compatibility, including syntax mypy can miss.

`nix build` runs unit tests on nixpkgs' default Python, and `checks.python-minimum`
runs them on the minimum version. That catches runtime differences, such as eager
annotation evaluation, that type checking alone does not detect.

Runtime dependency floors match the minor versions tested by the locked nixpkgs.
Keep mypy unpinned in the dev extras to match Nix's version.

## Nix command isolation

The command built by `nix build` runs Python in [isolated mode (`-I`)](https://docs.python.org/3/using/cmdline.html#cmdoption-I).
It uses the packaged dependencies and ignores inherited `PYTHONPATH`,
`PYTHONHOME`, user site-packages, and the script directory for imports. Python
leaves the environment variables available to application code and subprocesses.

Development shells, editable installs, and library imports use the active Python
environment. For plugins deliberately loaded through `PYTHONPATH`, remove the
`postInstall` block that adds `-I` in `default.nix` and adapt
`tests/test_nix_cli.py` to the intended plugin behavior.

`nix flake check` tests the installed command with conflicting Python settings
through `checks.nix-cli`. To run those tests directly after `nix build`:

```sh
nix develop -c env MANIKIN_NIX_EXECUTABLE="$PWD/result/bin/manikin" python -m pytest tests/test_nix_cli.py
```
