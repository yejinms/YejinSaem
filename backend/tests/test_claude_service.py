"""Tests for Claude image encoding helpers."""

import random
from pathlib import Path

from PIL import Image

from services.claude_service import MAX_ANTHROPIC_IMAGE_BYTES, encode_image_for_api


def test_encode_image_for_api_compresses_large_jpeg(tmp_path):
    image_path = tmp_path / "large.jpg"
    pixels = bytes(random.getrandbits(8) for _ in range(5000 * 4000 * 3))
    Image.frombytes("RGB", (5000, 4000), pixels).save(image_path, format="JPEG", quality=95)

    assert image_path.stat().st_size > MAX_ANTHROPIC_IMAGE_BYTES

    data, media_type = encode_image_for_api(str(image_path))

    assert media_type == "image/jpeg"
    assert len(data) <= MAX_ANTHROPIC_IMAGE_BYTES


def test_encode_image_for_api_keeps_small_png(tmp_path):
    image_path = tmp_path / "small.png"
    Image.new("RGB", (200, 200), color=(10, 20, 30)).save(image_path, format="PNG")

    data, media_type = encode_image_for_api(str(image_path))

    assert media_type == "image/png"
    assert data == Path(image_path).read_bytes()
