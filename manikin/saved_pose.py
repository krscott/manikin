"""Write a saved pose: the photo, pose.json, and an overlay image."""

import errno
import itertools
import json
import re
import secrets
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw

from manikin.photo import Photo
from manikin.pose import Pose, pose_file, preview_edges

OVERLAY_MAX_SIZE = 1600


@dataclass(frozen=True)
class SaveError:
    message: str


def save_pose(
    *,
    out_dir: Path,
    photo: Photo,
    pose: Pose,
    name: str,
    now: datetime,
    backend: str,
    manikin_version: str,
) -> Path | SaveError:
    """Save into a new directory under `out_dir` and return its path.

    Files are written to a hidden temporary directory first, so a saved pose
    is either complete or absent.
    """
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        # A random hidden name; unlike tempfile.mkdtemp, mkdir honours the umask.
        staging = out_dir / f".partial-{secrets.token_hex(8)}"
        staging.mkdir()
    except OSError as e:
        return SaveError(f"Cannot write to {out_dir}: {e.strerror or e}")
    try:
        (staging / f"photo.{photo.extension}").write_bytes(photo.data)
        document = pose_file(pose, backend=backend, manikin_version=manikin_version)
        (staging / "pose.json").write_text(json.dumps(document, indent=2) + "\n")
        overlay_image(photo.image, pose).save(staging / "overlay.png")
        return _claim(staging, out_dir, saved_pose_dir_name(name=name, now=now))
    except OSError as e:
        return SaveError(f"Cannot save the pose in {out_dir}: {e.strerror or e}")
    finally:
        shutil.rmtree(staging, ignore_errors=True)  # Gone after a successful claim.


def saved_pose_dir_name(*, name: str, now: datetime) -> str:
    stamp = now.strftime("%Y%m%d-%H%M%S")
    slug = slugify(name)
    return f"{stamp}-{slug}" if slug else stamp


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:60].rstrip("-")


def overlay_image(image: Image.Image, pose: Pose) -> Image.Image:
    overlay = image.copy()
    overlay.thumbnail((OVERLAY_MAX_SIZE, OVERLAY_MAX_SIZE))
    scale = overlay.width / pose.image_size[0]
    radius = max(2, round(overlay.width / 200))
    draw = ImageDraw.Draw(overlay)
    points = {
        joint: (x * scale, y * scale) for joint, (x, y) in pose.image_points.items()
    }
    for head, tail in preview_edges():
        color = _side_color(head.value + tail.value)
        draw.line([points[head], points[tail]], fill=color, width=radius)
    for joint, (x, y) in points.items():
        draw.ellipse(
            (x - radius, y - radius, x + radius, y + radius),
            fill=_side_color(joint.value),
            outline="black",
        )
    return overlay


def _side_color(name: str) -> str:
    if ".L" in name:
        return "#3b82f6"  # Subject's left: blue.
    if ".R" in name:
        return "#f97316"  # Subject's right: orange.
    return "#e5e7eb"


def _claim(staging: Path, out_dir: Path, name: str) -> Path:
    """Rename `staging` to `name`, or `name-2`, `name-3`, ... if that is taken.

    Renaming onto an existing non-empty directory fails atomically, so
    concurrent saves with the same name cannot overwrite each other.
    """
    for suffix in itertools.count(1):
        target = out_dir / (name if suffix == 1 else f"{name}-{suffix}")
        if target.exists():
            continue  # Also skips empty directories, which rename would replace.
        try:
            staging.rename(target)
            return target
        except OSError as e:
            if e.errno not in (errno.EEXIST, errno.ENOTEMPTY):
                raise
    raise AssertionError("unreachable")
