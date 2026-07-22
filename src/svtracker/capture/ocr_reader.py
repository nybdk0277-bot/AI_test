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
_warned_no_jpn_lang = False


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


def read_card_name(image: Image.Image, lang: str = "jpn") -> Optional[str]:
    """カード名(日本語テキスト)を1行として読み取る。pytesseract/本体/言語データが無ければ None.

    プレイ表示の上部に出るカード名バナーをOCRする用途。数字OCRと違い日本語の言語データ
    (jpn.traineddata)が必要。--psm 7 は「画像全体を1行のテキストとして扱う」指定。
    """
    global _warned_no_pytesseract, _warned_no_tesseract_binary, _warned_no_jpn_lang
    try:
        import pytesseract
    except ImportError:
        if not _warned_no_pytesseract:
            logger.warning(
                "pytesseract が見つかりません。`pip install -e \".[ocr]\"` と "
                "Tesseract本体+日本語データ(jpn)のインストールが必要です。カード名OCRは無効になります。"
            )
            _warned_no_pytesseract = True
        return None

    try:
        text = pytesseract.image_to_string(image, lang=lang, config="--psm 7")
    except pytesseract.pytesseract.TesseractNotFoundError:
        if not _warned_no_tesseract_binary:
            logger.warning(
                "Tesseract本体が見つかりません。インストールしてPATHを通してください。カード名OCRは無効になります。"
            )
            _warned_no_tesseract_binary = True
        return None
    except Exception as exc:  # 言語データ未導入(jpn.traineddata が無い)等
        if "jpn" in str(exc).lower() or "language" in str(exc).lower() or "traineddata" in str(exc).lower():
            if not _warned_no_jpn_lang:
                logger.warning(
                    "Tesseractの日本語データ(jpn.traineddata)が見つかりません。Tesseractインストール時に"
                    "日本語(Japanese)を追加するか、tessdataにjpn.traineddataを配置してください。"
                    "カード名OCRは無効になります。"
                )
                _warned_no_jpn_lang = True
            return None
        logger.exception("カード名OCRに失敗しました")
        return None

    text = text.strip()
    return text or None


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


def read_count(image: Image.Image) -> Optional[int]:
    """手札枚数・デッキ残り・墓場枚数・コンボ数などの整数カウンタ表示を読み取る."""
    return parse_int_text(_ocr_digits_string(image))


# 実対戦動画のフレームから採取した点灯ピップの色。EP=金(≈206,180,76)、SEP=紫(≈178,151,214)。
# 消灯ピップは暗色(≈83-95,70-88,72-95)。ピップはオーブ(それ自体が金/紫)の上に重なって
# 表示されるため「領域全体から塊を数える」方式は使えず、ピップ1個ずつを小さな枠として
# キャリブレーションし、枠内の点灯色ピクセル比率で点灯/消灯を判定する。
# 実フレームでの比率: 点灯=0.59〜0.83 / 消灯=0.07〜0.39(閾値0.5で明確に分離)。
PIP_LIT_FRACTION_THRESHOLD = 0.5


def _is_lit_ep_pixel(r: int, g: int, b: int) -> bool:
    return r >= 150 and g >= 110 and b <= 140 and (r + g) - 2 * b >= 60


def _is_lit_sep_pixel(r: int, g: int, b: int) -> bool:
    return b >= 150 and r >= 110 and b - g >= 30


def pip_is_lit(pip_image: Image.Image, kind: str) -> bool:
    """進化ポイント(kind="ep")/超進化ポイント(kind="sep")のピップ1個の点灯判定."""
    is_lit = _is_lit_ep_pixel if kind == "ep" else _is_lit_sep_pixel
    rgb = pip_image.convert("RGB")
    width, height = rgb.size
    if width == 0 or height == 0:
        return False
    pixels = rgb.load()
    lit = sum(1 for x in range(width) for y in range(height) if is_lit(*pixels[x, y]))
    return lit / (width * height) >= PIP_LIT_FRACTION_THRESHOLD


def count_lit_pips(pip_images: list[Image.Image], kind: str) -> int:
    """ピップ枠(1個ずつキャリブレーションした小さな矩形)の点灯数を数える."""
    return sum(1 for img in pip_images if pip_is_lit(img, kind))


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
