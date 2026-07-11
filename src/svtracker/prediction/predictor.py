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
from svtracker.game.models import GameFormat
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
    rotation_min_card_set_id: Optional[int] = None,
) -> list[PredictedPlay]:
    state = tracker.state
    turn = max(1, tracker.current_turn)
    if opponent_available_pp is not None:
        available_pp = opponent_available_pp
    else:
        # 相手PPは画面から直接読めないためターン数から推定するが、ターンOCRが
        # 使えない環境(Tesseract未導入等)ではターンが1のまま進まず、予測が
        # 「1PPで出せるカード」に固定されてしまう。相手が既にプレイしたカードの
        # 最大コストは「相手が少なくともそれだけのPPを持っている」実測値なので、
        # 推定の下限として使う。
        available_pp = min(turn, pp_cap)
        max_played_cost = max(
            (card.cost for cid in state.opponent_revealed_card_ids if (card := database.get(cid)) is not None),
            default=0,
        )
        available_pp = min(pp_cap, max(available_pp, max_played_cost))
    opponent_clan = state.opponent_clan

    candidates = [
        c
        for c in database.all()
        if c.cost <= available_pp and (not opponent_clan or c.clan in (opponent_clan, "ニュートラル", ""))
    ]
    candidates = _filter_by_format(candidates, state.game_format, rotation_min_card_set_id)
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


def _filter_by_format(
    candidates: list[Card], game_format: GameFormat, rotation_min_card_set_id: Optional[int]
) -> list[Card]:
    """ローテーション選択時のみ、しきい値未満のカードセットのカードを候補から除外する.

    アンリミテッド選択時、またはしきい値が未設定の場合は絞り込みを行わない。
    card_set_id が不明(None)なカードは判定材料が無いため除外せず残す(安全側)。
    """
    if game_format != GameFormat.ROTATION or rotation_min_card_set_id is None:
        return candidates
    return [c for c in candidates if c.card_set_id is None or c.card_set_id >= rotation_min_card_set_id]
