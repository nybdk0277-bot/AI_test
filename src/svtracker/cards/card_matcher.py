"""キャプチャした画像領域を、カードマスタDBと照合してカードを特定する."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import imagehash
from PIL import Image

from svtracker.cards.card_database import CardDatabase
from svtracker.cards.hashing import compute_phash
from svtracker.cards.models import Card


@dataclass
class MatchResult:
    card: Card
    distance: int
    confidence: float  # 0.0-1.0, 1.0が完全一致


class CardMatcher:
    """知覚ハッシュ(pHash)のハミング距離でカードを特定する.

    画面キャプチャは撮影条件(解像度・圧縮・アニメーション)によって
    公式画像と完全一致しないため、テンプレートマッチングではなく
    多少のズレに強いpHashを採用している。
    """

    def __init__(self, database: CardDatabase, hash_size: int = 16, max_distance: int = 14):
        self.database = database
        self.hash_size = hash_size
        self.max_distance = max_distance
        self._index: dict[str, imagehash.ImageHash] = {}
        self.reindex()

    def reindex(self) -> None:
        self._index = {}
        for card in self.database.all():
            if card.phash:
                self._index[card.card_id] = imagehash.hex_to_hash(card.phash)

    def match(self, image: Image.Image, top_k: int = 3) -> list[MatchResult]:
        if not self._index:
            return []
        query_hash = compute_phash(image, hash_size=self.hash_size)
        max_bits = self.hash_size * self.hash_size
        scored: list[tuple[str, int]] = []
        for card_id, ref_hash in self._index.items():
            distance = query_hash - ref_hash
            scored.append((card_id, distance))
        scored.sort(key=lambda pair: pair[1])

        results: list[MatchResult] = []
        for card_id, distance in scored[:top_k]:
            card = self.database.get(card_id)
            if card is None:
                continue
            confidence = max(0.0, 1.0 - distance / max_bits)
            results.append(MatchResult(card=card, distance=distance, confidence=confidence))
        return results

    def best_match(self, image: Image.Image) -> Optional[MatchResult]:
        """最有力候補を返す。距離が閾値を超える(=自信がない)場合は None."""
        results = self.match(image, top_k=1)
        if not results:
            return None
        best = results[0]
        if best.distance > self.max_distance:
            return None
        return best
