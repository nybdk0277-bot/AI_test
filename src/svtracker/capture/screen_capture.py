"""mss を使った画面キャプチャと、config/regions.json に基づく領域切り出し."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import mss
from PIL import Image

from svtracker.capture.window_finder import WindowRect, find_game_window

logger = logging.getLogger(__name__)


class ScreenCapture:
    def __init__(self, monitor_index: int = 1, window_title_hint: Optional[str] = None):
        self.monitor_index = monitor_index
        self.window_title_hint = window_title_hint
        self._sct = mss.mss()

    def grab(self) -> Image.Image:
        """ゲームウィンドウ（見つかれば）またはモニタ全体をキャプチャしてPIL Imageで返す."""
        rect = find_game_window(self.window_title_hint) if self.window_title_hint else None
        if rect is not None:
            bbox = {"left": rect.left, "top": rect.top, "width": rect.width, "height": rect.height}
        else:
            bbox = self._sct.monitors[self.monitor_index]
        raw = self._sct.grab(bbox)
        return Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

    def close(self) -> None:
        self._sct.close()

    def __enter__(self) -> "ScreenCapture":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


class RegionSet:
    """名前付き矩形領域(hand/board/turn indicatorなど)の集合."""

    def __init__(self, regions: dict):
        self._regions = regions

    @classmethod
    def load(cls, path: Path) -> "RegionSet":
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw.pop("_comment", None)
        raw.pop("resolution", None)
        return cls(raw)

    def slots(self, name: str) -> list[tuple[int, int, int, int]]:
        """複数枠(手札・盤面など)を [x, y, w, h] のリストで返す."""
        value = self._regions.get(name, [])
        return [tuple(r) for r in value]

    def single(self, name: str) -> Optional[tuple[int, int, int, int]]:
        value = self._regions.get(name)
        if value is None:
            return None
        return tuple(value)

    def point(self, name: str) -> Optional[tuple[int, int]]:
        """[x, y] 形式の単一座標(手番判定用ピクセルなど)を返す."""
        value = self._regions.get(name)
        if value is None:
            return None
        x, y = value
        return int(x), int(y)

    def crop(self, image: Image.Image, rect: tuple[int, int, int, int]) -> Image.Image:
        x, y, w, h = rect
        return image.crop((x, y, x + w, y + h))

    def crop_named_slots(self, image: Image.Image, name: str) -> list[Image.Image]:
        return [self.crop(image, rect) for rect in self.slots(name)]
