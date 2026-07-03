"""進行中の対戦状態(ターン・盤面・手札・アクション履歴)を保持する."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from svtracker.game.models import Action, ActionType, BoardUnit, GameFormat, Player


@dataclass
class MatchState:
    turn: int = 0
    active_player: Optional[Player] = None
    self_clan: str = ""
    opponent_clan: str = ""
    game_format: GameFormat = GameFormat.UNLIMITED
    self_life: int = 20
    opponent_life: int = 20
    self_pp: int = 0
    self_max_pp: int = 0
    self_extra_pp: int = 0  # 使わなかったPPを持ち越すエクストラPP(最大2)
    self_ep: int = 0  # 自分の進化ポイント(残り回数)
    opponent_ep: int = 0  # 相手の進化ポイント(残り回数)
    self_hand_card_ids: set[str] = field(default_factory=set)
    self_board: list[BoardUnit] = field(default_factory=list)
    opponent_board: list[BoardUnit] = field(default_factory=list)
    opponent_revealed_card_ids: set[str] = field(default_factory=set)


class MatchTracker:
    """1試合分の状態を管理する。試合終了後は storage.MatchLog に保存する想定."""

    def __init__(
        self, self_clan: str = "", opponent_clan: str = "", game_format: GameFormat = GameFormat.UNLIMITED
    ):
        self.state = MatchState(self_clan=self_clan, opponent_clan=opponent_clan, game_format=game_format)
        self.actions: list[Action] = []

    @property
    def current_turn(self) -> int:
        return self.state.turn

    def advance_turn(self, active_player: Player) -> None:
        self.state.turn += 1
        self.state.active_player = active_player

    def sync_turn(self, observed_turn: int, active_player: Optional[Player] = None) -> bool:
        """OCR等で読み取った実際のターン数と状態を同期する。

        フレームごとに呼ばれる想定なので、値が変化した時だけ更新し、
        変化したかどうかを返す(呼び出し側はTrueの時だけターン変化イベントを扱えばよい)。
        """
        changed = observed_turn != self.state.turn
        if changed:
            self.state.turn = observed_turn
        if active_player is not None:
            self.state.active_player = active_player
        return changed

    def record_action(self, action: Action) -> None:
        self.actions.append(action)
        if action.player == Player.OPPONENT and action.card_id:
            self.state.opponent_revealed_card_ids.add(action.card_id)
        if action.action_type == ActionType.END_TURN and action.player == Player.SELF:
            pass  # ターン送りは advance_turn 側で扱う

    def history(self, player: Optional[Player] = None) -> list[Action]:
        if player is None:
            return list(self.actions)
        return [a for a in self.actions if a.player == player]

    def opponent_hand_size_estimate(self) -> Optional[int]:
        """相手の手札枚数は直接観測できないため None を基本とする。
        (将来 OCR 等で手札枚数表示を読めれば埋める拡張ポイント)"""
        return None

    def set_self_board(self, units: list[BoardUnit]) -> None:
        self.state.self_board = units

    def set_opponent_board(self, units: list[BoardUnit]) -> None:
        self.state.opponent_board = units

    def set_pp(self, current: int, maximum: int) -> None:
        self.state.self_pp = current
        self.state.self_max_pp = maximum

    def set_extra_pp(self, extra_pp: int) -> None:
        self.state.self_extra_pp = extra_pp

    def set_ep(self, self_ep: int, opponent_ep: int) -> None:
        self.state.self_ep = self_ep
        self.state.opponent_ep = opponent_ep

    def infer_clan(self, player: Player, clan: str) -> bool:
        """認識できたカードの実際のクラスから、そのプレイヤーのクラスを推測する.

        ニュートラルはどのクラスのデッキにも入るため判定材料にならず無視する。
        デッキは単一クラス固定なので、一度判明したら上書きしない。
        クラスが新たに判明した場合のみ True を返す(呼び出し側でログ/DB更新の
        トリガーに使う)。
        """
        if not clan or clan == "ニュートラル":
            return False
        current = self.state.self_clan if player == Player.SELF else self.state.opponent_clan
        if current:
            return False
        if player == Player.SELF:
            self.state.self_clan = clan
        else:
            self.state.opponent_clan = clan
        return True

    def set_life(self, self_life: int, opponent_life: int) -> None:
        self.state.self_life = self_life
        self.state.opponent_life = opponent_life
