"""画像 -> 知覚ハッシュ変換の共通ユーティリティ.

card_fetcher（DB構築時）と card_matcher（実行時の照合）の両方から使うため、
循環importを避けてここに切り出している。
"""
from __future__ import annotations

import imagehash
from PIL import Image


def compute_phash(image: Image.Image, hash_size: int = 16) -> imagehash.ImageHash:
    return imagehash.phash(image.convert("RGB"), hash_size=hash_size)


def compute_phash_hex(image: Image.Image, hash_size: int = 16) -> str:
    return str(compute_phash(image, hash_size=hash_size))
