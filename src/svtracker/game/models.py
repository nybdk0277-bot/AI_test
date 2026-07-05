"""対戦記録用のデータモデル."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Player(str, Enum):
    SELF = "self"
    OPPONENT = "opponent"


class GameFormat(str, Enum):
    ROTATION = "rotation"
    UNLIMITED = "unlimited"


class ActionType(str, Enum):
    PLAY_CARD = "play_card"
    ATTACK = "attack"
    EVOLVE = "evolve"
    SUPER_EVOLVE = "super_evolve"
    END_TURN = "end_turn"
    ABILITY = "ability"
    UNIT_DESTROYED = "unit_destroyed"  # 盤面上のフォロワーが消滅した(破壊/除去/バウンスなど区別しない)
    LIFE_CHANGE = "life_change"  # ライフが変化した(被ダメージ/回復。detailに増減幅を記録)
    UNKNOWN = "unknown"


@dataclass
class Action:
    turn: int
    player: Player
    action_type: ActionType
    card_id: Optional[str] = None
    card_name: Optional[str] = None
    detail: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "turn": self.turn,
            "player": self.player.value,
            "action_type": self.action_type.value,
            "card_id": self.card_id,
            "card_name": self.card_name,
            "detail": self.detail,
            "timestamp": self.timestamp,
        }


@dataclass
class BoardUnit:
    """盤面上のフォロワー1体の現在状態（アドバイス計算用）."""

    card_id: str
    name: str
    atk: int
    hp: int
    can_attack: bool = True
    evolved: bool = False
