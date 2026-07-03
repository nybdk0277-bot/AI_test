"""連続するフレームの認識結果(手札/盤面のカードID群・進化ポイント)を比較して、
「カードがプレイされた」「進化した」等のアクションを検出する.

画面認識は毎フレーム完璧ではない(誤検出・見逃し)前提のため、
検出ロジックはシンプルな差分ベースに留めている。
"""
from __future__ import annotations

from typing import Optional

from svtracker.game.models import Action, ActionType, Player


class EventDetector:
    def __init__(self) -> None:
        self._prev_self_hand: set[str] = set()
        self._prev_self_board: set[str] = set()
        self._prev_opponent_board: set[str] = set()
        self._prev_self_ep: Optional[int] = None
        self._prev_opponent_ep: Optional[int] = None

    def update(
        self,
        turn: int,
        self_hand_ids: list[str | None],
        self_board_ids: list[str | None],
        opponent_board_ids: list[str | None],
        self_ep: Optional[int] = None,
        opponent_ep: Optional[int] = None,
    ) -> list[Action]:
        actions: list[Action] = []

        cur_self_hand = {c for c in self_hand_ids if c}
        cur_self_board = {c for c in self_board_ids if c}
        cur_opponent_board = {c for c in opponent_board_ids if c}

        # 自分: 手札から消え、かつ新たに盤面に現れたカード = プレイした
        newly_on_self_board = cur_self_board - self._prev_self_board
        left_hand = self._prev_self_hand - cur_self_hand
        played_self = newly_on_self_board & left_hand
        for card_id in played_self:
            actions.append(
                Action(turn=turn, player=Player.SELF, action_type=ActionType.PLAY_CARD, card_id=card_id)
            )

        # 相手: 手札は見えないため、盤面に新規出現したカードをプレイとみなす
        played_opponent = cur_opponent_board - self._prev_opponent_board
        for card_id in played_opponent:
            actions.append(
                Action(turn=turn, player=Player.OPPONENT, action_type=ActionType.PLAY_CARD, card_id=card_id)
            )

        actions.extend(self._detect_evolution(turn, Player.SELF, self_ep, "_prev_self_ep"))
        actions.extend(self._detect_evolution(turn, Player.OPPONENT, opponent_ep, "_prev_opponent_ep"))

        self._prev_self_hand = cur_self_hand
        self._prev_self_board = cur_self_board
        self._prev_opponent_board = cur_opponent_board
        return actions

    def _detect_evolution(
        self, turn: int, player: Player, observed_ep: Optional[int], prev_attr: str
    ) -> list[Action]:
        """進化ポイントが減った分だけ進化/超進化とみなす(1減=進化、2減=超進化).

        観測できていない(None)フレームやEP増加(ターン開始時の付与)は無視する。
        最初の観測時は基準値が無いため比較せず、次回以降の減少検知の基準にするだけ。
        """
        actions: list[Action] = []
        prev_ep = getattr(self, prev_attr)
        if observed_ep is not None and prev_ep is not None and observed_ep < prev_ep:
            delta = prev_ep - observed_ep
            action_type = ActionType.SUPER_EVOLVE if delta >= 2 else ActionType.EVOLVE
            actions.append(Action(turn=turn, player=player, action_type=action_type))
        if observed_ep is not None:
            setattr(self, prev_attr, observed_ep)
        return actions

    def reset(self) -> None:
        self.__init__()
