"""記録した対戦データをもとに、相手の次の行動(プレイするカード)を予測する.

厳密なゲームAIではなく、以下のヒューリスティックによるスコアリング:
  - 過去にそのクラス相手にそのターン前後でよく使われたカードか (履歴頻度)
  - 今対戦でまだ見せていないカードか (新規性: デッキ内に残っている可能性が高い)
  - 現在のPPで使えるコストかどうか (カーブ適合度)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from svtracker.cards.card_database import CardDatabase
from svtracker.cards.models import Card
from svtracker.game.match_tracker import MatchTracker
from svtracker.storage.match_log import MatchLog

FREQUENCY_WEIGHT = 0.6
NOVELTY_WEIGHT = 0.2
CURVE_FIT_WEIGHT = 0.2
NOVELTY_BONUS = 1.0  # まだ見せていないカードに与えるボーナス(重み計算前の生値)


@dataclass
class PredictedPlay:
    card: Card
    score: float
    reason: str


def predict_opponent_next_actions(
    tracker: MatchTracker,
    database: CardDatabase,
    match_log: Optional[MatchLog] = None,
    top_k: int = 5,
    opponent_available_pp: Optional[int] = None,
    pp_cap: int = 10,
) -> list[PredictedPlay]:
    state = tracker.state
    turn = max(1, tracker.current_turn)
    available_pp = opponent_available_pp if opponent_available_pp is not None else min(turn, pp_cap)
    opponent_clan = state.opponent_clan

    candidates = [
        c
        for c in database.all()
        if c.cost <= available_pp and (not opponent_clan or c.clan in (opponent_clan, "ニュートラル", ""))
    ]
    if not candidates:
        return []

    played_ids = state.opponent_revealed_card_ids

    scored: list[PredictedPlay] = []
    for card in candidates:
        freq = 0.0
        if match_log is not None and opponent_clan:
            freq = match_log.card_play_frequency(opponent_clan, card.card_id, turn)

        novelty = 0.0 if card.card_id in played_ids else NOVELTY_BONUS
        curve_fit = 1.0 - (abs(available_pp - card.cost) / max(1, pp_cap))

        score = FREQUENCY_WEIGHT * freq + NOVELTY_WEIGHT * novelty + CURVE_FIT_WEIGHT * curve_fit

        reasons = []
        if freq > 0:
            reasons.append(f"過去{freq:.0%}の対戦でターン{turn}前後に使用")
        if card.card_id not in played_ids:
            reasons.append("今対戦未使用")
        reasons.append(f"コスト{card.cost}(PP{available_pp}に適合)")

        scored.append(PredictedPlay(card=card, score=score, reason=" / ".join(reasons)))

    scored.sort(key=lambda p: p.score, reverse=True)
    return scored[:top_k]
