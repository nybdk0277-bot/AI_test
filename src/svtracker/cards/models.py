"""カード関連のデータモデル."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Card:
    """1枚のカードのマスタ情報."""

    card_id: str
    name: str
    clan: str  # 例: "エルフ", "ロイヤル", "ニュートラル" など
    cost: int
    card_type: str  # "フォロワー" / "スペル" / "アミュレット"
    rarity: str = ""
    image_path: Optional[str] = None
    phash: Optional[str] = None
    # フォロワーの場合の基礎ステータス（分かれば）。アドバイス機能で利用。
    base_atk: Optional[int] = None
    base_hp: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "card_id": self.card_id,
            "name": self.name,
            "clan": self.clan,
            "cost": self.cost,
            "card_type": self.card_type,
            "rarity": self.rarity,
            "image_path": self.image_path,
            "phash": self.phash,
            "base_atk": self.base_atk,
            "base_hp": self.base_hp,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Card":
        return cls(
            card_id=str(data["card_id"]),
            name=data["name"],
            clan=data.get("clan", ""),
            cost=int(data.get("cost", 0)),
            card_type=data.get("card_type", ""),
            rarity=data.get("rarity", ""),
            image_path=data.get("image_path"),
            phash=data.get("phash"),
            base_atk=data.get("base_atk"),
            base_hp=data.get("base_hp"),
        )
