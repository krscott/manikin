import io
import json
import os
from datetime import datetime
from pathlib import Path

from PIL import Image

from manikin.photo import Photo, PhotoError, decode_photo
from manikin.pose import Pose
from manikin.saved_pose import SaveError, save_pose, saved_pose_dir_name, slugify

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


def test_decode_accepts_mpo_jpeg() -> None:
    # JPEGs with embedded extra images (e.g. HDR gain maps) open as MPO.
    buffer = io.BytesIO()
    frames = [Image.new("RGB", (8, 6), "red"), Image.new("RGB", (4, 3), "blue")]
    frames[0].save(buffer, format="MPO", save_all=True, append_images=frames[1:])
    photo = decode_photo(buffer.getvalue())
    assert isinstance(photo, Photo)
    assert photo.extension == "jpg"
    assert photo.image.size == (8, 6)


def test_decode_rejects_truncated(jpeg_bytes: bytes) -> None:
    result = decode_photo(jpeg_bytes[: len(jpeg_bytes) // 2])
    assert isinstance(result, PhotoError)
    assert "could not be read" in result.message


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
        saved = save_pose(
            out_dir=tmp_path / "poses",
            photo=photo,
            pose=sample_pose,
            name="kick",
            now=NOW,
            backend="test",
            manikin_version="1.2.3",
        )
        assert isinstance(saved, Path), saved
        return saved

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
    umask = os.umask(0)
    os.umask(umask)
    assert first.stat().st_mode & 0o777 == 0o777 & ~umask


def test_save_error(tmp_path: Path, sample_pose: Pose, jpeg_bytes: bytes) -> None:
    photo = decode_photo(jpeg_bytes)
    assert isinstance(photo, Photo)
    blocker = tmp_path / "file"
    blocker.write_text("")
    result = save_pose(
        out_dir=blocker / "poses",
        photo=photo,
        pose=sample_pose,
        name="",
        now=NOW,
        backend="test",
        manikin_version="1.2.3",
    )
    assert isinstance(result, SaveError)
    assert str(blocker / "poses") in result.message
