from io import BytesIO

import pytest
from app.utils.images import InvalidImage, sniff_image
from PIL import Image


def _img(fmt, size=(300, 300)):
    b = BytesIO()
    Image.new("RGB", size, "red").save(b, fmt)
    return b.getvalue()


@pytest.mark.parametrize(("fmt", "ct"), [("JPEG", "image/jpeg"), ("PNG", "image/png"), ("WEBP", "image/webp")])
def test_valid_formats(fmt, ct):
    info = sniff_image(_img(fmt), min_dim=200, max_dim=8000)
    assert (info.content_type, info.width, info.height) == (ct, 300, 300)


@pytest.mark.parametrize("data", [b"GIF89a" + b"0" * 100, b"", b"%PDF-1.4" + b"0" * 100, _img("GIF")])
def test_rejects_non_allowed(data):
    with pytest.raises(InvalidImage):
        sniff_image(data, min_dim=200, max_dim=8000)


def test_dimension_limits():
    with pytest.raises(InvalidImage):
        sniff_image(_img("PNG", (100, 100)), min_dim=200, max_dim=8000)
    with pytest.raises(InvalidImage):
        sniff_image(_img("PNG", (900, 300)), min_dim=200, max_dim=800)


def test_magic_matches_but_body_corrupt():
    with pytest.raises(InvalidImage):
        sniff_image(b"\x89PNG\r\n\x1a\n" + b"garbage" * 20, min_dim=1, max_dim=8000)
