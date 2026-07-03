"""連続するフレームの認識結果(手札/盤面のカードID群)を比較して、
「カードがプレイされた」等のアクションを検出する.

画面認識は毎フレーム完璧ではない(誤検出・見逃し)前提のため、
検出ロジックはシンプルな差分ベースに留めている。
"""
from __future__ import annotations

from svtracker.game.models import Action, ActionType, Player


class EventDetector:
    def __init__(self) -> None:
        self._prev_self_hand: set[str] = set()
        self._prev_self_board: set[str] = set()
        self._prev_opponent_board: set[str] = set()

    def update(
        self,
        turn: int,
        self_hand_ids: list[str | None],
        self_board_ids: list[str | None],
        opponent_board_ids: list[str | None],
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

        self._prev_self_hand = cur_self_hand
        self._prev_self_board = cur_self_board
        self._prev_opponent_board = cur_opponent_board
        return actions

    def reset(self) -> None:
        self.__init__()
