"""連続するフレームの認識結果(手札/盤面のカードID群・進化ポイント・ライフ・ターン数)を
比較して、「カードがプレイされた」「進化した」「盤面のユニットが消えた」「ライフが変化した」
「ターンが終わった」等のアクションを検出する.ゲーム内バトルログ相当の情報を蓄積する狙い。

画面認識は毎フレーム完璧ではない(誤検出・見逃し)前提のため、
検出ロジックはシンプルな差分ベースに留めている。
"""
from __future__ import annotations

from typing import Optional

from svtracker.game.models import Action, ActionType, Player

# 進化・超進化はゲームルール上、序盤のターンでは発生し得ない。進化ポイント(EP)/
# 超進化ポイント(SEP)のピクセル読み取りは画面演出(紫/金の光・エフェクト)でチラつき
# やすく、対戦開始直後(ターン1)に「進化した」「超進化した」と誤検出する事例が実機ログで
# 確認された。実際に進化が可能になるのはおおよそ中盤以降のため、それより早いターンの
# 減少検知はOCR/ピクセルのノイズとみなして無視する(下限ターン)。
EVOLVE_MIN_TURN = 4
SUPER_EVOLVE_MIN_TURN = 5


class EventDetector:
    def __init__(self) -> None:
        self._prev_self_hand: set[str] = set()
        self._prev_self_board: set[str] = set()
        self._prev_opponent_board: set[str] = set()
        self._prev_self_ep: Optional[int] = None
        self._prev_opponent_ep: Optional[int] = None
        self._prev_self_sep: Optional[int] = None
        self._prev_opponent_sep: Optional[int] = None
        self._prev_self_life: Optional[int] = None
        self._prev_opponent_life: Optional[int] = None
        self._prev_self_crest_count: Optional[int] = None
        self._prev_opponent_crest_count: Optional[int] = None
        self._prev_turn: Optional[int] = None
        self._prev_active_player: Optional[Player] = None

    def update(
        self,
        turn: int,
        self_hand_ids: list[str | None],
        self_board_ids: list[str | None],
        opponent_board_ids: list[str | None],
        self_ep: Optional[int] = None,
        opponent_ep: Optional[int] = None,
        self_sep: Optional[int] = None,
        opponent_sep: Optional[int] = None,
        self_life: Optional[int] = None,
        opponent_life: Optional[int] = None,
        self_crest_count: Optional[int] = None,
        opponent_crest_count: Optional[int] = None,
        active_player: Optional[Player] = None,
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

        # 盤面から消えたカード = 破壊/除去/バウンスなどで盤面を離れたとみなす
        # (区別まではしない。手札に戻った場合との判別はできないため簡易的な検出)。
        left_self_board = self._prev_self_board - cur_self_board
        for card_id in left_self_board:
            actions.append(
                Action(turn=turn, player=Player.SELF, action_type=ActionType.UNIT_DESTROYED, card_id=card_id)
            )
        left_opponent_board = self._prev_opponent_board - cur_opponent_board
        for card_id in left_opponent_board:
            actions.append(
                Action(
                    turn=turn, player=Player.OPPONENT, action_type=ActionType.UNIT_DESTROYED, card_id=card_id
                )
            )

        actions.extend(
            self._detect_point_drop(
                turn, Player.SELF, self_ep, "_prev_self_ep", ActionType.EVOLVE, EVOLVE_MIN_TURN
            )
        )
        actions.extend(
            self._detect_point_drop(
                turn, Player.OPPONENT, opponent_ep, "_prev_opponent_ep", ActionType.EVOLVE, EVOLVE_MIN_TURN
            )
        )
        actions.extend(
            self._detect_point_drop(
                turn, Player.SELF, self_sep, "_prev_self_sep", ActionType.SUPER_EVOLVE, SUPER_EVOLVE_MIN_TURN
            )
        )
        actions.extend(
            self._detect_point_drop(
                turn,
                Player.OPPONENT,
                opponent_sep,
                "_prev_opponent_sep",
                ActionType.SUPER_EVOLVE,
                SUPER_EVOLVE_MIN_TURN,
            )
        )
        actions.extend(self._detect_life_change(turn, Player.SELF, self_life, "_prev_self_life"))
        actions.extend(self._detect_life_change(turn, Player.OPPONENT, opponent_life, "_prev_opponent_life"))
        actions.extend(
            self._detect_crest_change(turn, Player.SELF, self_crest_count, "_prev_self_crest_count")
        )
        actions.extend(
            self._detect_crest_change(turn, Player.OPPONENT, opponent_crest_count, "_prev_opponent_crest_count")
        )
        actions.extend(self._detect_turn_change(turn, active_player))

        self._prev_self_hand = cur_self_hand
        self._prev_self_board = cur_self_board
        self._prev_opponent_board = cur_opponent_board
        return actions

    def _detect_point_drop(
        self,
        turn: int,
        player: Player,
        observed: Optional[int],
        prev_attr: str,
        action_type: ActionType,
        min_turn: int = 0,
    ) -> list[Action]:
        """ポイント表示の減少を検出してアクションにする.

        ゲームUIでは進化ポイント(黄色)と超進化ポイント(紫)が別々のカウンターとして
        表示されるため、EP減少=進化、SEP減少=超進化としてそれぞれ独立に検出する。
        フレーム間で2以上減った場合も1回のアクションとして記録する(1秒間隔の監視で
        2回連続して行うことは稀で、OCRの読み飛ばしの可能性の方が高いため)。

        観測できていない(None)フレームやポイント増加(ターン開始時の付与)は無視する。
        最初の観測時は基準値が無いため比較せず、次回以降の減少検知の基準にするだけ。

        min_turn より前のターンでの減少は、ゲームルール上あり得ない進化/超進化であり
        ピクセル読み取りのノイズとみなして無視する(基準値の更新だけは行い、以降の
        正しい減少検知に備える)。
        """
        actions: list[Action] = []
        prev = getattr(self, prev_attr)
        if observed is not None and prev is not None and observed < prev and turn >= min_turn:
            actions.append(Action(turn=turn, player=player, action_type=action_type))
        if observed is not None:
            setattr(self, prev_attr, observed)
        return actions

    def _detect_life_change(
        self, turn: int, player: Player, observed_life: Optional[int], prev_attr: str
    ) -> list[Action]:
        """ライフの増減(被ダメージ/回復)を検出する。最初の観測時は基準値が無いため比較しない."""
        actions: list[Action] = []
        prev_life = getattr(self, prev_attr)
        if observed_life is not None and prev_life is not None and observed_life != prev_life:
            delta = observed_life - prev_life
            actions.append(
                Action(
                    turn=turn,
                    player=player,
                    action_type=ActionType.LIFE_CHANGE,
                    detail=f"{delta:+d} (life={observed_life})",
                )
            )
        if observed_life is not None:
            setattr(self, prev_attr, observed_life)
        return actions

    def _detect_crest_change(
        self, turn: int, player: Player, observed_count: Optional[int], prev_attr: str
    ) -> list[Action]:
        """クレスト枠の占有数の増減を検出する。最初の観測時は基準値が無いため比較しない."""
        actions: list[Action] = []
        prev = getattr(self, prev_attr)
        if observed_count is not None and prev is not None and observed_count != prev:
            delta = observed_count - prev
            actions.append(
                Action(
                    turn=turn,
                    player=player,
                    action_type=ActionType.CREST_CHANGE,
                    detail=f"{delta:+d} (計{observed_count})",
                )
            )
        if observed_count is not None:
            setattr(self, prev_attr, observed_count)
        return actions

    def _detect_turn_change(self, turn: int, active_player: Optional[Player]) -> list[Action]:
        """ターン数が変化したら、直前まで手番だったプレイヤーのターン終了として記録する.

        手番情報(active_player)が無い場合は誰のターンだったか特定できないため記録しない。
        """
        actions: list[Action] = []
        if self._prev_turn is not None and turn != self._prev_turn and self._prev_active_player is not None:
            actions.append(
                Action(turn=self._prev_turn, player=self._prev_active_player, action_type=ActionType.END_TURN)
            )
        self._prev_turn = turn
        if active_player is not None:
            self._prev_active_player = active_player
        return actions

    def reset(self) -> None:
        self.__init__()
