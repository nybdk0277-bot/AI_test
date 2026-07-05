"""ターン数・PP・ライフ・手番表示など、UI上の文字/色を読み取るユーティリティ.

数字OCR(pytesseract)を使う部分と、そこから値を取り出す純粋なパース関数を分けている。
パース関数・色判定関数はTesseract本体が無くてもテストできる。
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from PIL import Image

from svtracker.game.models import Player

logger = logging.getLogger(__name__)

_warned_no_pytesseract = False
_warned_no_tesseract_binary = False


def _ocr_digits_string(image: Image.Image) -> Optional[str]:
    """画像から数字主体の文字列を読み取る。pytesseract/Tesseract本体が無ければ None."""
    global _warned_no_pytesseract, _warned_no_tesseract_binary
    try:
        import pytesseract
    except ImportError:
        if not _warned_no_pytesseract:
            logger.warning(
                "pytesseract が見つかりません。`pip install -e \".[ocr]\"` と "
                "Tesseract本体のインストールが必要です。ターン/PP/ライフの自動読み取りは無効になります。"
            )
            _warned_no_pytesseract = True
        return None

    config = "--psm 7 -c tessedit_char_whitelist=0123456789/"
    try:
        return pytesseract.image_to_string(image, config=config)
    except pytesseract.pytesseract.TesseractNotFoundError:
        # pytesseract本体(パッケージ)はあるが、Tesseractの実行ファイルが未インストール/
        # PATH未設定。毎フレーム発生しうるため、_warned_no_pytesseract と同様に一度だけ警告する。
        if not _warned_no_tesseract_binary:
            logger.warning(
                "Tesseract本体が見つかりません。インストールしてPATHを通すか、README記載の"
                "手順を確認してください。ターン/PP/ライフの自動読み取りは無効になります。"
            )
            _warned_no_tesseract_binary = True
        return None
    except Exception:
        logger.exception("OCR読み取りに失敗しました")
        return None


def parse_int_text(text: Optional[str]) -> Optional[int]:
    """OCR結果の文字列から最初の整数を取り出す."""
    if not text:
        return None
    match = re.search(r"\d+", text)
    if not match:
        return None
    return int(match.group())


def parse_pp_text(text: Optional[str]) -> Optional[tuple[int, int]]:
    """"3/6" のような "現在/最大" 形式のPP表記を (current, maximum) に変換する."""
    if not text:
        return None
    match = re.search(r"(\d+)\s*/\s*(\d+)", text)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def read_turn_number(image: Image.Image) -> Optional[int]:
    return parse_int_text(_ocr_digits_string(image))


def read_life(image: Image.Image) -> Optional[int]:
    return parse_int_text(_ocr_digits_string(image))


def read_pp(image: Image.Image) -> Optional[tuple[int, int]]:
    return parse_pp_text(_ocr_digits_string(image))


def read_extra_pp(image: Image.Image) -> Optional[int]:
    """持ち越し分のエクストラPP(0〜2)表示を読み取る."""
    return parse_int_text(_ocr_digits_string(image))


def read_evolution_points(image: Image.Image) -> Optional[int]:
    """残り進化ポイント表示を読み取る."""
    return parse_int_text(_ocr_digits_string(image))


def sample_pixel_color(image: Image.Image, xy: tuple[int, int]) -> tuple[int, int, int]:
    pixel = image.convert("RGB").getpixel(xy)
    return pixel[0], pixel[1], pixel[2]


def classify_active_player(
    color: tuple[int, int, int],
    self_color: tuple[int, int, int],
    opponent_color: tuple[int, int, int],
    max_distance: float = 60.0,
) -> Optional[Player]:
    """特定ピクセルの色を、自分/相手の手番を示す基準色と比較して手番を判定する.

    SVWBのUIは手番によって特定パーツの色/ハイライトが変わるため、
    その座標(config/regions.jsonの`active_player_pixel`)を基準色と比較する方式。
    OCRよりフォント依存が無く軽量。
    """
    dist_self = _color_distance(color, self_color)
    dist_opponent = _color_distance(color, opponent_color)
    best_distance = min(dist_self, dist_opponent)
    if best_distance > max_distance:
        return None
    return Player.SELF if dist_self <= dist_opponent else Player.OPPONENT


def _color_distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5
