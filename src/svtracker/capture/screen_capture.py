"""mss を使った画面キャプチャと、config/regions.json に基づく領域切り出し."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import mss
from PIL import Image

from svtracker.capture.window_finder import WindowRect, find_game_window

logger = logging.getLogger(__name__)


@dataclass
class MonitorInfo:
    index: int  # ScreenCapture(monitor_index=...) / Settings.monitor_index に渡す値
    left: int
    top: int
    width: int
    height: int

    @property
    def is_virtual_combined(self) -> bool:
        """mssの慣習で index=0 は全モニタを結合した仮想領域を指す."""
        return self.index == 0


def list_monitors() -> list[MonitorInfo]:
    """キャプチャ対象として選べるモニタの一覧を返す(index=0は全モニタ結合)."""
    with mss.mss() as sct:
        return [
            MonitorInfo(index=i, left=m["left"], top=m["top"], width=m["width"], height=m["height"])
            for i, m in enumerate(sct.monitors)
        ]


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


# 複数枠を持つ領域(手札・盤面)、単一矩形の領域、単一座標(ピクセル判定用)の領域。
# GUIのキャリブレーション画面もこの一覧を使って編集対象を出し分ける。
RECT_LIST_REGIONS = [
    "self_hand",
    "self_board",
    "opponent_board",
    # クレスト枠(リーダー横の丸スロット、自分=画面左下・相手=画面右上に各4つ)。任意設定。
    "self_crest_slots",
    "opponent_crest_slots",
]
RECT_SINGLE_REGIONS = [
    "turn_indicator",
    "self_pp",
    "opponent_pp",
    "self_life",
    "opponent_life",
    "self_extra_pp",
    "self_ep",
    "opponent_ep",
    "self_sep",
    "opponent_sep",
    # バトルログ用カウンタ(コンボ数・手札枚数・デッキ残り・墓場枚数)。任意設定。
    "combo_count",
    "self_hand_count",
    "opponent_hand_count",
    "self_deck_count",
    "opponent_deck_count",
    "self_cemetery_count",
    "opponent_cemetery_count",
]
POINT_REGIONS = ["active_player_pixel"]


class RegionSet:
    """名前付き矩形領域(hand/board/turn indicatorなど)の集合."""

    def __init__(self, regions: Optional[dict] = None):
        self._regions: dict = regions if regions is not None else {}

    @classmethod
    def load(cls, path: Path) -> "RegionSet":
        raw = json.loads(path.read_text(encoding="utf-8"))
        raw.pop("_comment", None)
        raw.pop("resolution", None)
        return cls(raw)

    def save(self, path: Path) -> None:
        """slots(list-of-rects)・single(rect)・point の3種類の形が混在するため、
        構造を仮定せず再帰的にlist化してJSONへ書き出す."""
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {name: self._to_plain(value) for name, value in self._regions.items()}
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _to_plain(value):
        if isinstance(value, (list, tuple)):
            return [RegionSet._to_plain(v) for v in value]
        return value

    def set_slots(self, name: str, rects: list[tuple[int, int, int, int]]) -> None:
        self._regions[name] = [list(r) for r in rects]

    def add_slot(self, name: str, rect: tuple[int, int, int, int]) -> None:
        self._regions.setdefault(name, []).append(list(rect))

    def remove_last_slot(self, name: str) -> None:
        if self._regions.get(name):
            self._regions[name].pop()

    def set_single(self, name: str, rect: tuple[int, int, int, int]) -> None:
        self._regions[name] = list(rect)

    def set_point(self, name: str, xy: tuple[int, int]) -> None:
        self._regions[name] = list(xy)

    def clear(self, name: str) -> None:
        self._regions.pop(name, None)

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
