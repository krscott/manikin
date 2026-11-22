import io
import json
from datetime import datetime
from pathlib import Path

from PIL import Image

from manikin.photo import Photo, PhotoError, decode_photo
from manikin.pose import Pose
from manikin.saved_pose import save_pose, saved_pose_dir_name, slugify

NOW = datetime(2026, 11, 21, 18, 30, 5)


def test_decode_applies_exif_orientation() -> None:
    buffer = io.BytesIO()
    exif = Image.Exif()
    exif[0x0112] = 6  # Rotate 90° clockwise to display.
    Image.new("RGB", (40, 20)).save(buffer, format="JPEG", exif=exif)
    photo = decode_photo(buffer.getvalue())
    assert isinstance(photo, Photo)
    assert photo.image.size == (20, 40)
    assert photo.extension == "jpg"


def test_decode_rejects_unsupported() -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4)).save(buffer, format="BMP")
    result = decode_photo(buffer.getvalue())
    assert isinstance(result, PhotoError) and "(BMP)" in result.message
    result = decode_photo(b"not an image")
    assert isinstance(result, PhotoError) and "Unsupported" in result.message


def test_dir_names() -> None:
    assert saved_pose_dir_name(name="", now=NOW) == "20261121-183005"
    assert (
        saved_pose_dir_name(name=" Sword Stance! ", now=NOW)
        == "20261121-183005-sword-stance"
    )
    assert slugify("../../etc") == "etc"


def test_save_pose(tmp_path: Path, sample_pose: Pose, jpeg_bytes: bytes) -> None:
    photo = decode_photo(jpeg_bytes)
    assert isinstance(photo, Photo)

    def save() -> Path:
        return save_pose(
            out_dir=tmp_path / "poses",
            photo=photo,
            pose=sample_pose,
            name="kick",
            now=NOW,
            backend="test",
            manikin_version="1.2.3",
        )

    first, second = save(), save()
    assert first.name == "20261121-183005-kick"
    assert second.name == "20261121-183005-kick-2"
    assert sorted(p.name for p in first.iterdir()) == [
        "overlay.png",
        "photo.jpg",
        "pose.json",
    ]
    assert (first / "photo.jpg").read_bytes() == jpeg_bytes
    assert json.loads((first / "pose.json").read_text())["backend"] == "test"
    assert Image.open(first / "overlay.png").size == (64, 48)
    assert not list((tmp_path / "poses").glob(".*"))
