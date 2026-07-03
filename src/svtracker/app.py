"""画面キャプチャ→カード認識→対戦記録→予測/アドバイス を繋ぐメインループ."""
from __future__ import annotations

import logging
import time
from typing import Optional

from svtracker.cards.card_database import CardDatabase
from svtracker.cards.card_matcher import CardMatcher
from svtracker.capture.screen_capture import RegionSet, ScreenCapture
from svtracker.config import Settings
from svtracker.game.event_detector import EventDetector
from svtracker.game.match_tracker import MatchTracker
from svtracker.game.models import Player
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
        self.event_detector = EventDetector()
        self.tracker = MatchTracker(self_clan=self_clan, opponent_clan=opponent_clan)

        self.match_log = MatchLog(settings.match_db_path) if enable_match_log else None
        self.match_id: Optional[int] = None
        if self.match_log is not None:
            self.match_id = self.match_log.start_match(self_clan, opponent_clan)

    def close(self) -> None:
        self.capture.close()
        if self.match_log is not None:
            self.match_log.close()

    def _recognize_slots(self, frame, region_name: str) -> list[Optional[str]]:
        if self.regions is None:
            return []
        results = []
        for crop in self.regions.crop_named_slots(frame, region_name):
            match = self.matcher.best_match(crop)
            results.append(match.card.card_id if match else None)
        return results

    def step(self) -> None:
        """1フレーム分の処理: キャプチャ→認識→差分検出→記録→予測/アドバイス表示."""
        if self.regions is None:
            logger.error("regions.json が未設定です。config/regions.example.json を参考に作成してください。")
            return

        frame = self.capture.grab()
        self_hand_ids = self._recognize_slots(frame, "self_hand")
        self_board_ids = self._recognize_slots(frame, "self_board")
        opponent_board_ids = self._recognize_slots(frame, "opponent_board")

        turn = self.tracker.current_turn or 1
        new_actions = self.event_detector.update(turn, self_hand_ids, self_board_ids, opponent_board_ids)

        for action in new_actions:
            card = self.database.get(action.card_id) if action.card_id else None
            if card:
                action.card_name = card.name
            self.tracker.record_action(action)
            if self.match_log is not None and self.match_id is not None:
                self.match_log.log_action(self.match_id, action)
            logger.info(
                "[turn %s] %s が %s をプレイ", action.turn, action.player.value, action.card_name or action.card_id
            )

        if any(a.player == Player.OPPONENT for a in new_actions):
            predictions = predict_opponent_next_actions(self.tracker, self.database, self.match_log)
            for p in predictions[:3]:
                logger.info("予測: 相手は次に %s を使うかもしれません (score=%.2f, %s)", p.card.name, p.score, p.reason)

        self_hand_cards = [self.database.get(cid) for cid in self_hand_ids if cid]
        self_hand_cards = [c for c in self_hand_cards if c is not None]
        recs = recommend_actions(self.tracker, self_hand_cards)
        for rec in recs[:3]:
            logger.info("提案: %s - %s", rec.title, rec.detail)

    def run_forever(self) -> None:
        try:
            while True:
                self.step()
                time.sleep(self.settings.capture_interval_sec)
        except KeyboardInterrupt:
            logger.info("停止します")
        finally:
            if self.match_log is not None and self.match_id is not None:
                self.match_log.end_match(self.match_id, "unknown")
            self.close()
