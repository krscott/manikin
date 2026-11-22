"""Decode uploaded photos into upright RGB images."""

import io
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

_EXTENSIONS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}


@dataclass(frozen=True, kw_only=True)
class Photo:
    data: bytes  # The uploaded bytes, saved unchanged.
    extension: str
    # Upright RGB image: EXIF orientation applied, matching how browsers show it.
    image: Image.Image


@dataclass(frozen=True)
class PhotoError:
    message: str


def decode_photo(data: bytes) -> Photo | PhotoError:
    try:
        with Image.open(io.BytesIO(data)) as opened:
            image_format = opened.format
            if image_format not in _EXTENSIONS:
                return _unsupported(image_format)
            upright = ImageOps.exif_transpose(opened).convert("RGB")
    except UnidentifiedImageError:
        return _unsupported(None)
    except Image.DecompressionBombError:
        return PhotoError("The photo has too many pixels")
    return Photo(data=data, extension=_EXTENSIONS[image_format], image=upright)


def _unsupported(image_format: str | None) -> PhotoError:
    found = f" ({image_format})" if image_format else ""
    return PhotoError(
        f"Unsupported image format{found}. Use JPEG, PNG, or WebP; "
        "if your phone saves HEIC, choose 'Most Compatible' in its camera settings."
    )
