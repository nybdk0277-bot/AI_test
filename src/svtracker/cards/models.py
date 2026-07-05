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
    # カードセット(弾)番号。ローテーション対象判定に使う。取得元から分からなければNone
    # (Noneのカードはローテーション判定で除外せず、常に対象に含める=安全側のフォールバック)。
    card_set_id: Optional[int] = None
    # 効果由来のPP/進化ポイント関連ステータス。公式サイトAPIには構造化された効果データが
    # 無いため常に0(=効果なし扱い)で取得され、`import-cards`のCSVで手動指定した場合のみ
    # 値が入る。アドバイス機能(prediction/advisor.py)で利用。
    max_pp_boost: int = 0  # プレイすると永続的にPP上限が+Nされる
    pp_recover: int = 0  # プレイするとそのターンのPPが+N回復する
    ep_recover: int = 0  # プレイすると進化ポイントが+N回復する

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
            "card_set_id": self.card_set_id,
            "max_pp_boost": self.max_pp_boost,
            "pp_recover": self.pp_recover,
            "ep_recover": self.ep_recover,
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
            card_set_id=data.get("card_set_id"),
            max_pp_boost=int(data.get("max_pp_boost") or 0),
            pp_recover=int(data.get("pp_recover") or 0),
            ep_recover=int(data.get("ep_recover") or 0),
        )
