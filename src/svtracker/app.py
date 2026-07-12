"""画面キャプチャ→カード認識→対戦記録→予測/アドバイス を繋ぐメインループ."""
from __future__ import annotations

import logging
import time
from typing import Callable, Optional

from svtracker.cards.card_database import CardDatabase
from svtracker.cards.card_matcher import CardMatcher
from svtracker.cards.models import Card
from svtracker.capture import ocr_reader
from svtracker.capture.screen_capture import RegionSet, ScreenCapture
from svtracker.config import Settings
from svtracker.game.event_detector import EventDetector
from svtracker.game.match_tracker import MatchTracker
from svtracker.game.models import ActionType, BoardUnit, GameFormat, Player
from svtracker.prediction.advisor import recommend_actions
from svtracker.prediction.predictor import predict_opponent_next_actions
from svtracker.storage.match_log import MatchLog

logger = logging.getLogger(__name__)


class MonitorApp:
    def __init__(
        self,
        settings: Settings,
        self_clan: str = "",
        opponent_clan: str = "",
        game_format: GameFormat = GameFormat.UNLIMITED,
        enable_match_log: bool = True,
    ):
        self.settings = settings
        settings.ensure_dirs()

        self.database = CardDatabase.load(settings.card_db_path)
        if len(self.database) == 0:
            logger.warning(
                "カードDBが空です。先に `svtracker fetch-cards` または `svtracker import-cards` を実行してください。"
            )
        self.matcher = CardMatcher(
            self.database, hash_size=settings.hash_size, max_distance=settings.match_max_distance
        )
        self.regions = RegionSet.load(settings.regions_path) if settings.regions_path.exists() else None
        self.capture = ScreenCapture(
            monitor_index=settings.monitor_index, window_title_hint=settings.window_title_hint
        )
        if game_format == GameFormat.ROTATION and settings.rotation_min_card_set_id is None:
            logger.warning(
                "ローテーション形式が選択されていますが rotation_min_card_set_id が未設定のため、"
                "カードプールの絞り込みは行われません(実質アンリミテッドと同じ結果になります)。"
            )
        self.event_detector = EventDetector()
        self.tracker = MatchTracker(self_clan=self_clan, opponent_clan=opponent_clan, game_format=game_format)

        self.match_log = MatchLog(settings.match_db_path) if enable_match_log else None
        self.match_id: Optional[int] = None
        if self.match_log is not None:
            self.match_id = self.match_log.start_match(self_clan, opponent_clan)

    def close(self) -> None:
        self.capture.close()
        if self.match_log is not None:
            self.match_log.close()

    def end_match(self, result: str = "unknown") -> None:
        """対戦結果("win"/"loss"/"unknown")を記録して対戦ログを確定する.

        画面から自動判定はしないため、GUI/CLI側でユーザーに確認したタイミングで呼ぶ想定。
        """
        if self.match_log is not None and self.match_id is not None:
            self.match_log.end_match(self.match_id, result)

    def _recognize_slots(self, frame, region_name: str) -> list[Optional[str]]:
        if self.regions is None:
            return []
        results = []
        for crop in self.regions.crop_named_slots(frame, region_name):
            match = self.matcher.best_match(crop)
            results.append(match.card.card_id if match else None)
        return results

    def _build_board_units(self, card_ids: list[Optional[str]]) -> list[BoardUnit]:
        """認識できたカードIDから盤面ユニットを組み立てる.

        現状は基礎ステータス(カードマスタの base_atk/base_hp)をそのまま使うだけで、
        バフ/デバフや疲労状態は画面から読み取っていないため反映されない
        (can_attack は常にTrue、evolved は常にFalse)。より正確にするには
        UI上のATK/HP表示のOCRや進化アイコン検出が別途必要。
        """
        units: list[BoardUnit] = []
        for card_id in card_ids:
            if not card_id:
                continue
            card: Optional[Card] = self.database.get(card_id)
            if card is None or card.base_atk is None or card.base_hp is None:
                continue
            units.append(BoardUnit(card_id=card.card_id, name=card.name, atk=card.base_atk, hp=card.base_hp))
        return units

    def _sync_turn_and_active_player(self, frame) -> None:
        """OCRとピクセル色判定でターン数・手番を読み取り、trackerに反映する."""
        turn_rect = self.regions.single("turn_indicator")
        active_player: Optional[Player] = None

        pixel_xy = self.regions.point("active_player_pixel")
        if pixel_xy is not None:
            color = ocr_reader.sample_pixel_color(frame, pixel_xy)
            active_player = ocr_reader.classify_active_player(
                color,
                self_color=self.settings.self_turn_color,
                opponent_color=self.settings.opponent_turn_color,
                max_distance=self.settings.active_player_color_max_distance,
            )

        if turn_rect is not None:
            observed_turn = ocr_reader.read_turn_number(self.regions.crop(frame, turn_rect))
            if observed_turn is not None:
                self.tracker.sync_turn(observed_turn, active_player)
                return

        if active_player is not None:
            self.tracker.state.active_player = active_player

    def _sync_pp_and_life(self, frame) -> None:
        pp_rect = self.regions.single("self_pp")
        if pp_rect is not None:
            pp = ocr_reader.read_pp(self.regions.crop(frame, pp_rect))
            if pp is not None:
                self.tracker.set_pp(*pp)

        extra_pp_rect = self.regions.single("self_extra_pp")
        if extra_pp_rect is not None:
            extra_pp = ocr_reader.read_extra_pp(self.regions.crop(frame, extra_pp_rect))
            if extra_pp is not None:
                self.tracker.set_extra_pp(extra_pp)

        self_ep_rect = self.regions.single("self_ep")
        opponent_ep_rect = self.regions.single("opponent_ep")
        self_ep = (
            ocr_reader.read_evolution_points(self.regions.crop(frame, self_ep_rect))
            if self_ep_rect is not None
            else None
        )
        opponent_ep = (
            ocr_reader.read_evolution_points(self.regions.crop(frame, opponent_ep_rect))
            if opponent_ep_rect is not None
            else None
        )
        if self_ep is not None or opponent_ep is not None:
            self.tracker.set_ep(
                self_ep if self_ep is not None else self.tracker.state.self_ep,
                opponent_ep if opponent_ep is not None else self.tracker.state.opponent_ep,
            )

        # 超進化ポイント(SEP)。ゲームUIでは進化ポイント(黄色)とは別の紫のカウンター。
        self_sep_rect = self.regions.single("self_sep")
        opponent_sep_rect = self.regions.single("opponent_sep")
        self_sep = (
            ocr_reader.read_evolution_points(self.regions.crop(frame, self_sep_rect))
            if self_sep_rect is not None
            else None
        )
        opponent_sep = (
            ocr_reader.read_evolution_points(self.regions.crop(frame, opponent_sep_rect))
            if opponent_sep_rect is not None
            else None
        )
        if self_sep is not None or opponent_sep is not None:
            self.tracker.set_sep(
                self_sep if self_sep is not None else self.tracker.state.self_sep,
                opponent_sep if opponent_sep is not None else self.tracker.state.opponent_sep,
            )

        self_life_rect = self.regions.single("self_life")
        opponent_life_rect = self.regions.single("opponent_life")
        self_life = (
            ocr_reader.read_life(self.regions.crop(frame, self_life_rect)) if self_life_rect is not None else None
        )
        opponent_life = (
            ocr_reader.read_life(self.regions.crop(frame, opponent_life_rect))
            if opponent_life_rect is not None
            else None
        )
        if self_life is not None or opponent_life is not None:
            self.tracker.set_life(
                self_life if self_life is not None else self.tracker.state.self_life,
                opponent_life if opponent_life is not None else self.tracker.state.opponent_life,
            )

    def _sync_battle_log_counts(self, frame) -> None:
        """コンボ数・手札枚数・デッキ残り・墓場枚数のカウンタ表示を読み取る(任意設定領域).

        いずれもキャリブレーションで領域を指定していなければスキップされる。
        """
        def read_region(name: str) -> Optional[int]:
            rect = self.regions.single(name)
            if rect is None:
                return None
            return ocr_reader.read_count(self.regions.crop(frame, rect))

        self.tracker.set_battle_log_counts(
            combo_count=read_region("combo_count"),
            self_hand_count=read_region("self_hand_count"),
            opponent_hand_count=read_region("opponent_hand_count"),
            self_deck_count=read_region("self_deck_count"),
            opponent_deck_count=read_region("opponent_deck_count"),
            self_cemetery_count=read_region("self_cemetery_count"),
            opponent_cemetery_count=read_region("opponent_cemetery_count"),
        )

    def _infer_clans(self, player: Player, card_ids: list[Optional[str]]) -> None:
        """認識できたカード(ニュートラル以外)からそのプレイヤーのクラスを自動判別する.

        デッキは単一クラス固定なので、非ニュートラルカードが1枚でも認識できれば
        判別できる。既に判明済み(手動入力含む)なら上書きしない。
        """
        for card_id in card_ids:
            if not card_id:
                continue
            card = self.database.get(card_id)
            if card is None:
                continue
            if self.tracker.infer_clan(player, card.clan):
                logger.info("%s のクラスを自動判別しました: %s", player.value, card.clan)
                if self.match_log is not None and self.match_id is not None:
                    if player == Player.SELF:
                        self.match_log.update_match_clans(self.match_id, self_clan=card.clan)
                    else:
                        self.match_log.update_match_clans(self.match_id, opponent_clan=card.clan)
                return

    def step(self) -> None:
        """1フレーム分の処理: キャプチャ→認識→差分検出→記録→予測/アドバイス表示."""
        if self.regions is None:
            logger.error("regions.json が未設定です。config/regions.example.json を参考に作成してください。")
            return

        frame = self.capture.grab()

        self._sync_turn_and_active_player(frame)
        self._sync_pp_and_life(frame)
        self._sync_battle_log_counts(frame)

        self_hand_ids = self._recognize_slots(frame, "self_hand")
        self_board_ids = self._recognize_slots(frame, "self_board")
        opponent_board_ids = self._recognize_slots(frame, "opponent_board")

        self._infer_clans(Player.SELF, [*self_hand_ids, *self_board_ids])
        self._infer_clans(Player.OPPONENT, opponent_board_ids)

        self.tracker.set_self_board(self._build_board_units(self_board_ids))
        self.tracker.set_opponent_board(self._build_board_units(opponent_board_ids))

        turn = self.tracker.current_turn or 1
        new_actions = self.event_detector.update(
            turn,
            self_hand_ids,
            self_board_ids,
            opponent_board_ids,
            self_ep=self.tracker.state.self_ep,
            opponent_ep=self.tracker.state.opponent_ep,
            self_sep=self.tracker.state.self_sep,
            opponent_sep=self.tracker.state.opponent_sep,
            self_life=self.tracker.state.self_life,
            opponent_life=self.tracker.state.opponent_life,
            active_player=self.tracker.state.active_player,
        )

        for action in new_actions:
            card = self.database.get(action.card_id) if action.card_id else None
            if card:
                action.card_name = card.name
            self.tracker.record_action(action)
            if self.match_log is not None and self.match_id is not None:
                self.match_log.log_action(self.match_id, action)
            if action.action_type == ActionType.PLAY_CARD:
                logger.info(
                    "[turn %s] %s が %s をプレイ", action.turn, action.player.value, action.card_name or action.card_id
                )
            elif action.action_type in (ActionType.EVOLVE, ActionType.SUPER_EVOLVE):
                label = "超進化" if action.action_type == ActionType.SUPER_EVOLVE else "進化"
                logger.info("[turn %s] %s が%sしました", action.turn, action.player.value, label)
            elif action.action_type == ActionType.UNIT_DESTROYED:
                logger.info(
                    "[turn %s] %s の %s が盤面から離れました(破壊/除去など)",
                    action.turn,
                    action.player.value,
                    action.card_name or action.card_id,
                )
            elif action.action_type == ActionType.LIFE_CHANGE:
                logger.info("[turn %s] %s のライフが変化: %s", action.turn, action.player.value, action.detail)
            elif action.action_type == ActionType.END_TURN:
                logger.info("[turn %s] %s のターンが終了しました", action.turn, action.player.value)

        if any(a.player == Player.OPPONENT for a in new_actions):
            predictions = predict_opponent_next_actions(
                self.tracker,
                self.database,
                self.match_log,
                rotation_min_card_set_id=self.settings.rotation_min_card_set_id,
            )
            for p in predictions[:3]:
                logger.info("予測: 相手は次に %s を使うかもしれません (score=%.2f, %s)", p.card.name, p.score, p.reason)

        self_hand_cards = [self.database.get(cid) for cid in self_hand_ids if cid]
        self_hand_cards = [c for c in self_hand_cards if c is not None]
        recs = recommend_actions(self.tracker, self_hand_cards, match_log=self.match_log)
        for rec in recs[:3]:
            logger.info("提案: %s - %s", rec.title, rec.detail)

    def run_forever(self, on_finish: Optional[Callable[[], str]] = None) -> None:
        """`on_finish` は監視終了時に呼ばれ、対戦結果("win"/"loss"/"unknown")を返す想定
        (CLIでのインタラクティブな確認などに使う)。省略時は "unknown" として記録する。"""
        try:
            while True:
                self.step()
                time.sleep(self.settings.capture_interval_sec)
        except KeyboardInterrupt:
            logger.info("停止します")
        finally:
            result = on_finish() if on_finish is not None else "unknown"
            self.end_match(result)
            self.close()
