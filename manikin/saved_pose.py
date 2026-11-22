"""Write a saved pose: the photo, pose.json, and an overlay image."""

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw

from manikin.photo import Photo
from manikin.pose import Pose, pose_file, preview_edges

OVERLAY_MAX_SIZE = 1600


def save_pose(
    *,
    out_dir: Path,
    photo: Photo,
    pose: Pose,
    name: str,
    now: datetime,
    backend: str,
    manikin_version: str,
) -> Path:
    """Save into a new directory under `out_dir` and return its path.

    Files are written to a hidden temporary directory first, so a saved pose
    is either complete or absent.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    target = _unused_dir(out_dir, saved_pose_dir_name(name=name, now=now))
    staging = out_dir / f".{target.name}.partial"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir()
    try:
        (staging / f"photo.{photo.extension}").write_bytes(photo.data)
        document = pose_file(pose, backend=backend, manikin_version=manikin_version)
        (staging / "pose.json").write_text(json.dumps(document, indent=2) + "\n")
        overlay_image(photo.image, pose).save(staging / "overlay.png")
        staging.rename(target)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return target


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


def _unused_dir(out_dir: Path, name: str) -> Path:
    candidate = out_dir / name
    suffix = 2
    while candidate.exists():
        candidate = out_dir / f"{name}-{suffix}"
        suffix += 1
    return candidate
