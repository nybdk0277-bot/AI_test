"""カード名テキスト(OCR結果)からカードを特定する、あいまい照合ユーティリティ.

プレイ時に画面中央へ大きく表示される「プレイ表示」の上部にはカード名が明瞭な文字で
出る。カードの絵柄をpHashで照合する方式はゲーム内描画(光・アニメ絵・エフェクト)と
公式静止画の差が大きく実用にならないことを実機で確認したため、代わりにこの名前を
OCRで読み、DBのカード名と照合してカードを特定する。

OCRは誤読(濁点・長音・中黒の欠落、記号の混入など)が避けられないため、完全一致では
なく正規化した上での類似度(difflib)で最も近いカードを返す。
"""
from __future__ import annotations

from difflib import SequenceMatcher
from typing import Optional

from svtracker.cards.card_database import CardDatabase
from svtracker.cards.models import Card

# 正規化時に取り除く記号(中黒・スペース・各種括弧など、OCRで揺れやすく意味を持たないもの)。
# 長音符 ー は名前の一部なので除去しない(下でOCRの揺れを吸収する)。
_STRIP_CHARS = set(" 　・･·.。、,／/「」『』【】()()[]")
# 長音符と紛らわしい文字(漢数字の一・ハイフン各種・波ダッシュ・縦棒など)は、OCRの揺れを
# 吸収するため全て長音符 ー に寄せてから比較する。
_LONG_VOWEL_LIKE = "一-‐‑‒–—―ｰ|｜~〜～─＿"


def normalize_name(text: str) -> str:
    """照合用にカード名を正規化する(不要記号除去・長音符の揺れ統一・英字小文字化)."""
    out: list[str] = []
    for ch in text:
        if ch in _STRIP_CHARS or ch.isspace():
            continue
        if ch in _LONG_VOWEL_LIKE:
            out.append("ー")
        else:
            out.append(ch.lower())
    return "".join(out)


def similarity(a: str, b: str) -> float:
    """正規化した2つの名前の類似度(0.0〜1.0)."""
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


class NameMatcher:
    """カードDBの名前を正規化して保持し、OCRテキストに最も近いカードを返す."""

    def __init__(self, database: CardDatabase):
        # (正規化名, Card) のリスト。同名カードもあり得るのでdictにはしない。
        self._entries: list[tuple[str, Card]] = [
            (normalize_name(c.name), c) for c in database.all() if c.name
        ]

    def match(self, text: Optional[str], min_ratio: float = 0.6) -> Optional[tuple[Card, float]]:
        """OCRテキストに最も近いカードと類似度を返す。閾値未満/候補なしは None.

        正規化後の文字数が1文字以下のテキストは、短すぎて誤一致しやすいので照合しない。
        """
        if not text:
            return None
        query = normalize_name(text)
        if len(query) < 2:
            return None
        best: Optional[tuple[Card, float]] = None
        for norm, card in self._entries:
            if not norm:
                continue
            ratio = SequenceMatcher(None, query, norm).ratio()
            if best is None or ratio > best[1]:
                best = (card, ratio)
        if best is None or best[1] < min_ratio:
            return None
        return best
