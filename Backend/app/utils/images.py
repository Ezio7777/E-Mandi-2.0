"""Server-side image validation: magic bytes + Pillow header parse + dimension/pixel limits."""
from dataclasses import dataclass
from io import BytesIO

from PIL import Image, UnidentifiedImageError

ALLOWED_TYPES: dict[str, str] = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
_PIL_FORMAT = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
MAX_PIXELS = 40_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS  # Pillow raises DecompressionBombError beyond 2x this


class InvalidImage(ValueError):
    pass


@dataclass(frozen=True)
class ImageInfo:
    content_type: str
    width: int
    height: int


def ext_for(content_type: str) -> str:
    try:
        return ALLOWED_TYPES[content_type]
    except KeyError as exc:
        raise InvalidImage("Unsupported image type. Allowed: JPEG, PNG, WebP") from exc


def _magic_type(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def sniff_image(data: bytes, *, min_dim: int, max_dim: int) -> ImageInfo:
    magic = _magic_type(data)
    if magic is None:
        raise InvalidImage("File is not a supported image (JPEG, PNG or WebP)")
    try:
        with Image.open(BytesIO(data)) as img:
            fmt, (w, h) = img.format, img.size
            img.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError) as exc:
        raise InvalidImage("Image file is corrupt or unreadable") from exc
    if _PIL_FORMAT.get(fmt or "") != magic:
        raise InvalidImage("Image content does not match its file signature")
    if min(w, h) < min_dim:
        raise InvalidImage(f"Image is too small (minimum {min_dim}px on the shorter side)")
    if max(w, h) > max_dim or w * h > MAX_PIXELS:
        raise InvalidImage("Image dimensions are too large")
    return ImageInfo(magic, w, h)
