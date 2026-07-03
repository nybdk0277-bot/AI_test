"""カードマスタDB（JSONファイルベース）の読み書き."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Optional

from svtracker.cards.models import Card


class CardDatabase:
    def __init__(self, cards: Optional[Iterable[Card]] = None):
        self._by_id: dict[str, Card] = {}
        for card in cards or []:
            self._by_id[card.card_id] = card

    def __len__(self) -> int:
        return len(self._by_id)

    def add(self, card: Card) -> None:
        self._by_id[card.card_id] = card

    def get(self, card_id: str) -> Optional[Card]:
        return self._by_id.get(str(card_id))

    def all(self) -> list[Card]:
        return list(self._by_id.values())

    def by_name(self, name: str) -> list[Card]:
        return [c for c in self._by_id.values() if c.name == name]

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = [c.to_dict() for c in self._by_id.values()]
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "CardDatabase":
        if not path.exists():
            return cls()
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(Card.from_dict(d) for d in raw)
