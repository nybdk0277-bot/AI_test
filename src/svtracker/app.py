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
from svtracker.capture.stability import StableValue
from svtracker.config import Settings
from svtracker.game.event_detector import EventDetector
from svtracker.game.match_tracker import MatchTracker
from svtracker.game.models import Action, ActionType, BoardUnit, GameFormat, Player
from svtracker.prediction.advisor import recommend_actions
from svtracker.prediction.predictor import predict_opponent_next_actions
from svtracker.storage.match_log import MatchLog

logger = logging.getLogger(__name__)

# OCR誤読の棄却に使う妥当範囲(実戦ログで life=204 等の誤読が観測されたため)。
MAX_PLAUSIBLE_LIFE = 40
MAX_PLAUSIBLE_PP = 10
MAX_PLAUSIBLE_TURN = 40
# カードが一度も認識できていない場合に診断ログを出すフレーム間隔。
RECOGNITION_DIAG_INTERVAL = 30


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

        # 1フレーム限りの誤読で状態が動かないよう、変化は2フレーム連続で確定させる。
        self._stable: dict[str, StableValue] = {
            name: StableValue(required=2)
            for name in (
                "turn", "self_life", "opponent_life", "opponent_pp",
            )
        }
        # 進化/超進化ピップ(◆)とクレスト枠は、紫/金の光やエフェクトの重なりで数秒
        # チラつくことがあり、2フレームでは誤検出(特にターン開始直後の偽の「進化」)が
        # 残るため、より長い3フレーム確定にする。
        for name in ("self_ep", "opponent_ep", "self_sep", "opponent_sep", "self_crest", "opponent_crest"):
            self._stable[name] = StableValue(required=3)
        # カード認識の診断用(一度も認識できていない場合に案内を出す)
        self._step_count = 0
        self._recognized_any_card = False
        self._min_match_distance: Optional[int] = None
        # プレイ表示(プレイ時に画面中央へ出る完全なカード)の直前の認識結果。
        # 同じカードが表示され続けている間に重複記録しないためのもの。
        self._last_reveal: dict[str, Optional[str]] = {}
        # プレイ表示の時間的安定を測るための「連続で最有力だったカードと回数」。
        # ゆるい閾値でも、規定フレーム連続で同じカードが最有力なら本物のプレイとみなす。
        self._reveal_candidate_id: Optional[str] = None
        self._reveal_candidate_frames: int = 0
        # 診断ログを同じ候補で繰り返さないための直近ログ済みキー。
        self._reveal_diag_last: Optional[tuple[str, int]] = None

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
            candidates = self.matcher.match(crop, top_k=1)
            if not candidates:
                results.append(None)
                continue
            best = candidates[0]
            if self._min_match_distance is None or best.distance < self._min_match_distance:
                self._min_match_distance = best.distance
            if best.distance <= self.matcher.max_distance:
                self._recognized_any_card = True
                results.append(best.card.card_id)
            else:
                results.append(None)
        return results

    def dump_recognition_debug(self, out_dir) -> "Path":
        """現在の画面を1枚キャプチャし、各カード枠の切り出し画像と最有力候補を保存する.

        「枠がカードに合っているか」「合っているのに一致しないのか」を目視で切り分ける
        ための診断用。out_dir 直下に crop画像(手札/盤面の各スロット)と summary.txt
        (スロットごとの最有力候補カード名とpHash距離)を書き出し、そのディレクトリを返す。
        """
        from pathlib import Path

        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        # 古い診断結果が混ざらないよう、既存のcrop_*.pngは消してから書き出す
        for old in out.glob("crop_*.png"):
            old.unlink()

        frame = self.capture.grab()
        frame.save(out / "full_frame.png")
        lines = [
            f"カードDB枚数: {len(self.database)}",
            f"match_max_distance(認識閾値): {self.matcher.max_distance}",
            "pHash距離は0が完全一致、大きいほど別物(16x16なら最大256、128前後で無関係)。",
            "距離が大きい場合はまず crop_*.png を開き、カードの絵柄が正しく写っているか確認してください。",
            "",
        ]
        if self.regions is None:
            lines.append("regions.json が未設定です。")
        else:
            for region_name in ("self_hand", "self_board", "opponent_board"):
                crops = self.regions.crop_named_slots(frame, region_name)
                lines.append(f"[{region_name}] {len(crops)}枠")
                for i, crop in enumerate(crops):
                    fname = f"crop_{region_name}_{i + 1}.png"
                    crop.save(out / fname)
                    results = self.matcher.match(crop, top_k=1)
                    if results:
                        best = results[0]
                        lines.append(f"  {fname}: 最有力={best.card.name} 距離={best.distance}")
                    else:
                        lines.append(f"  {fname}: 候補なし(カードDBにpHash画像が無い)")
                lines.append("")
            rect = self.regions.single("play_reveal")
            if rect is None:
                lines.append("[play_reveal] 未設定")
            else:
                crop = self.regions.crop(frame, rect)
                crop.save(out / "crop_play_reveal.png")
                results = self.matcher.match(crop, top_k=1)
                if results:
                    best = results[0]
                    lines.append(
                        f"[play_reveal] crop_play_reveal.png: 最有力={best.card.name} 距離={best.distance}"
                    )
                    lines.append(
                        "  ※ このcropに『プレイ中の中央の大型カード』が写っているか確認してください。"
                        "写っていて距離が大きい場合のみ枠位置がズレています。"
                    )
                else:
                    lines.append("[play_reveal] crop_play_reveal.png: 候補なし")
                lines.append("")
        (out / "summary.txt").write_text("\n".join(lines), encoding="utf-8")
        logger.info("認識デバッグを保存しました: %s", out)
        return out

    def _detect_play_reveals(self, frame, turn: int) -> list[Action]:
        """プレイ時に画面「中央」へ大きく表示される「完全なカード」を照合してプレイを検出する.

        手札は扇状に傾き、盤面は枚数で位置が変わり中央寄せされるため固定枠での照合が
        効きにくいのに対し、プレイ表示は「平面・正立・大型・固定位置」で公式カード画像と
        同じ構図なので、pHash照合が最も効く場所(実対戦動画で確認)。
        自分・相手どちらのプレイでも同じ中央位置(play_reveal)に出るので枠は1つにまとめ、
        「今出したのが自分か相手か」は手番(active_player)で判定する。手番が不明なときは
        相手プレイとして扱う(統計の主目的は相手のプレイ把握のため)。同じカードが表示され
        続けている間は1回だけ記録する。
        """
        rect = self.regions.single("play_reveal")
        if rect is None:
            return []
        crop = self.regions.crop(frame, rect)
        candidates = self.matcher.match(crop, top_k=1)
        if not candidates:
            return []
        best = candidates[0]
        if self._min_match_distance is None or best.distance < self._min_match_distance:
            self._min_match_distance = best.distance

        # 診断: 閾値を超えていても、正しいカードを捉えているかを確認できるよう最有力候補を
        # ログに出す(同じ候補・同程度の距離での繰り返しは抑制)。ユーザーがこのログを見て
        # 「正しいカード名が出ている」なら reveal_max_distance を上げれば実用化できる、
        # 「デタラメ」ならpHash方式では限界、と切り分けられる。
        diag = self.settings.reveal_diagnostic_distance
        if diag > 0 and best.distance <= diag:
            key = (best.card.card_id, best.distance // 5)
            if key != self._reveal_diag_last:
                self._reveal_diag_last = key
                logger.info(
                    "プレイ表示の最有力候補: %s (pHash距離=%s / 記録閾値 reveal_max_distance=%s)",
                    best.card.name,
                    best.distance,
                    self.settings.reveal_max_distance,
                )

        # 記録の可否はゆるい閾値 reveal_max_distance で判定する。
        if best.distance > self.settings.reveal_max_distance:
            self._reveal_candidate_id = None
            self._reveal_candidate_frames = 0
            self._last_reveal["play_reveal"] = None
            return []

        # 時間的安定の確認: 同じカードが連続で最有力になったフレーム数を数え、
        # reveal_confirm_frames に達して初めて本物のプレイとして記録する。
        if best.card.card_id == self._reveal_candidate_id:
            self._reveal_candidate_frames += 1
        else:
            self._reveal_candidate_id = best.card.card_id
            self._reveal_candidate_frames = 1
        if self._reveal_candidate_frames < max(1, self.settings.reveal_confirm_frames):
            return []

        self._recognized_any_card = True
        if self._last_reveal.get("play_reveal") == best.card.card_id:
            return []
        self._last_reveal["play_reveal"] = best.card.card_id
        player = self.tracker.state.active_player or Player.OPPONENT
        return [
            Action(
                turn=turn,
                player=player,
                action_type=ActionType.PLAY_CARD,
                card_id=best.card.card_id,
                detail=f"プレイ表示から認識(距離{best.distance})",
            )
        ]

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
            if observed_turn is not None and 1 <= observed_turn <= MAX_PLAUSIBLE_TURN:
                confirmed = self._stable["turn"].update(observed_turn)
                # ターンは対戦中に戻らないため、進む方向の変化のみ反映する(誤読対策)。
                if confirmed is not None and confirmed > self.tracker.state.turn:
                    self.tracker.sync_turn(confirmed, active_player)
                    return

        if active_player is not None:
            self.tracker.state.active_player = active_player

    @staticmethod
    def _plausible_pp(pp: Optional[tuple[int, int]]) -> Optional[tuple[int, int]]:
        """PP読み取り値の妥当性チェック。「現在<=最大<=10」を満たさない誤読を棄却する."""
        if pp is None:
            return None
        current, maximum = pp
        if 1 <= maximum <= MAX_PLAUSIBLE_PP and 0 <= current <= maximum:
            return pp
        return None

    def _sync_pp_and_life(self, frame) -> None:
        pp_rect = self.regions.single("self_pp")
        if pp_rect is not None:
            pp = self._plausible_pp(ocr_reader.read_pp(self.regions.crop(frame, pp_rect)))
            if pp is not None:
                self.tracker.set_pp(*pp)

        # 相手PPは画面右上に「PP 6 /9」形式で常時表示されている(実対戦動画で確認)。
        opponent_pp_rect = self.regions.single("opponent_pp")
        if opponent_pp_rect is not None:
            observed = self._plausible_pp(ocr_reader.read_pp(self.regions.crop(frame, opponent_pp_rect)))
            confirmed = self._stable["opponent_pp"].update(observed)
            if confirmed is not None:
                self.tracker.set_opponent_pp(*confirmed)

        extra_pp_rect = self.regions.single("self_extra_pp")
        if extra_pp_rect is not None:
            extra_pp = ocr_reader.read_extra_pp(self.regions.crop(frame, extra_pp_rect))
            if extra_pp is not None:
                self.tracker.set_extra_pp(extra_pp)

        self_ep = self._stable["self_ep"].update(
            self._read_points(frame, pips_name="self_ep_pips", digit_name="self_ep", kind="ep")
        )
        opponent_ep = self._stable["opponent_ep"].update(
            self._read_points(frame, pips_name="opponent_ep_pips", digit_name="opponent_ep", kind="ep")
        )
        if self_ep is not None or opponent_ep is not None:
            self.tracker.set_ep(
                self_ep if self_ep is not None else self.tracker.state.self_ep,
                opponent_ep if opponent_ep is not None else self.tracker.state.opponent_ep,
            )

        # 超進化ポイント(SEP)。ゲームUIでは進化ポイント(金)とは別の紫のピップ。
        self_sep = self._stable["self_sep"].update(
            self._read_points(frame, pips_name="self_sep_pips", digit_name="self_sep", kind="sep")
        )
        opponent_sep = self._stable["opponent_sep"].update(
            self._read_points(frame, pips_name="opponent_sep_pips", digit_name="opponent_sep", kind="sep")
        )
        if self_sep is not None or opponent_sep is not None:
            self.tracker.set_sep(
                self_sep if self_sep is not None else self.tracker.state.self_sep,
                opponent_sep if opponent_sep is not None else self.tracker.state.opponent_sep,
            )

        def read_plausible_life(name: str) -> Optional[int]:
            rect = self.regions.single(name)
            if rect is None:
                return None
            value = ocr_reader.read_life(self.regions.crop(frame, rect))
            # 実戦で life=204 等の誤読が観測されたため、妥当範囲外は棄却する
            if value is None or not 0 <= value <= MAX_PLAUSIBLE_LIFE:
                return None
            return value

        self_life = self._stable["self_life"].update(read_plausible_life("self_life"))
        opponent_life = self._stable["opponent_life"].update(read_plausible_life("opponent_life"))
        if self_life is not None or opponent_life is not None:
            self.tracker.set_life(
                self_life if self_life is not None else self.tracker.state.self_life,
                opponent_life if opponent_life is not None else self.tracker.state.opponent_life,
            )

    def _read_points(self, frame, pips_name: str, digit_name: str, kind: str) -> Optional[int]:
        """EP/SEPの残数を読む。ピップ枠(実UI向け)があれば点灯数を数え、
        無ければ数字OCR領域(数字表示のUI向け)にフォールバックする."""
        pip_crops = self.regions.crop_named_slots(frame, pips_name)
        if pip_crops:
            return ocr_reader.count_lit_pips(pip_crops, kind)
        rect = self.regions.single(digit_name)
        if rect is not None:
            return ocr_reader.read_evolution_points(self.regions.crop(frame, rect))
        return None

    def _sync_crest_slots(self, frame) -> None:
        """クレスト枠(丸スロット)の占有数を明るさ/ばらつき判定で数える(任意設定領域)."""
        from svtracker.capture import crest_reader

        def count_region(name: str) -> Optional[int]:
            slots = self.regions.crop_named_slots(frame, name)
            if not slots:
                return None
            return crest_reader.count_occupied_slots(slots)

        self.tracker.set_crest_counts(
            self_crest_count=self._stable["self_crest"].update(count_region("self_crest_slots")),
            opponent_crest_count=self._stable["opponent_crest"].update(count_region("opponent_crest_slots")),
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
        self._step_count += 1

        self._sync_turn_and_active_player(frame)
        self._sync_pp_and_life(frame)
        self._sync_battle_log_counts(frame)
        self._sync_crest_slots(frame)

        # 先攻プレイヤーの記録: ターン1で手番が判明していれば、その手番側が先攻。
        # (手番判定ピクセルをキャリブレーションしている場合のみ埋まる)
        if (
            self.match_log is not None
            and self.match_id is not None
            and self.tracker.state.turn <= 1
            and self.tracker.state.active_player is not None
        ):
            self.match_log.set_first_player(self.match_id, self.tracker.state.active_player.value)

        # 実UIにはターン数の常時表示が無い(実対戦動画で確認)ため、PP最大値(自分/相手の
        # 大きい方)をターン数の下限として使う。turn_indicator が読めている場合はそちらが優先
        # (sync_turnは値が進む方向にしか更新しないためOCR値と競合しない)。
        max_pp_estimate = max(self.tracker.state.self_max_pp, self.tracker.state.opponent_max_pp)
        if max_pp_estimate > self.tracker.state.turn:
            self.tracker.sync_turn(max_pp_estimate)

        self_hand_ids = self._recognize_slots(frame, "self_hand")
        self_board_ids = self._recognize_slots(frame, "self_board")
        opponent_board_ids = self._recognize_slots(frame, "opponent_board")

        if not self._recognized_any_card and self._step_count % RECOGNITION_DIAG_INTERVAL == 0:
            logger.warning(
                "手札/盤面のカードがまだ一度も認識できていません(これまでの最小pHash距離=%s、"
                "認識閾値 match_max_distance=%s)。距離が閾値よりやや大きいだけなら "
                "settings.json の match_max_distance を上げると認識される可能性があります。"
                "距離が大幅に大きい場合は、キャリブレーションの手札/盤面枠がカードの絵柄部分と"
                "ずれていないか、カードDBの画像が古くないかを確認してください。",
                self._min_match_distance,
                self.matcher.max_distance,
            )

        self._infer_clans(Player.SELF, [*self_hand_ids, *self_board_ids])
        self._infer_clans(Player.OPPONENT, opponent_board_ids)

        # 盤面枠の画像照合が効いた場合のみ盤面を上書きする。効かない場合(実UIでは
        # オーラ演出でpHash照合がほぼ不可能なことを実測済み)は、プレイ検出からの
        # 推定盤面(add_inferred_unit)を保持する。
        visual_self_board = self._build_board_units(self_board_ids)
        if visual_self_board:
            self.tracker.set_self_board(visual_self_board)
        visual_opponent_board = self._build_board_units(opponent_board_ids)
        if visual_opponent_board:
            self.tracker.set_opponent_board(visual_opponent_board)

        turn = self.tracker.current_turn or 1
        reveal_actions = self._detect_play_reveals(frame, turn)
        # プレイ表示から相手クラスも自動判別できる(盤面認識より確実)
        self._infer_clans(Player.OPPONENT, [a.card_id for a in reveal_actions if a.player == Player.OPPONENT])
        self._infer_clans(Player.SELF, [a.card_id for a in reveal_actions if a.player == Player.SELF])

        new_actions = reveal_actions + self.event_detector.update(
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
            self_crest_count=self.tracker.state.self_crest_count,
            opponent_crest_count=self.tracker.state.opponent_crest_count,
            active_player=self.tracker.state.active_player,
        )

        # プレイ表示と手札/盤面差分の両方が同じプレイを検出した場合の二重記録を防ぐ
        # (同ターン・同プレイヤー・同カードのPLAY_CARDは最初の1件だけ通す)
        seen_plays = {
            (a.player, a.card_id, a.turn)
            for a in self.tracker.actions
            if a.action_type == ActionType.PLAY_CARD
        }
        deduped: list[Action] = []
        for action in new_actions:
            if action.action_type == ActionType.PLAY_CARD and action.card_id:
                key = (action.player, action.card_id, action.turn)
                if key in seen_plays:
                    continue
                seen_plays.add(key)
            deduped.append(action)
        new_actions = deduped

        # このフレームの局面スナップショットを、この後記録する全アクションに紐づける
        # (何ターン目・何PP・盤面何体…でそのカードを出したか、を後から考察できるように)
        situation = self.tracker.situation_snapshot()

        for action in new_actions:
            card = self.database.get(action.card_id) if action.card_id else None
            if card:
                action.card_name = card.name
            if action.context is None:
                action.context = situation
            self.tracker.record_action(action)
            # トークン(効果生成カード)のプレイ表示は、プレイ判断ではなく生成元カードの
            # プレイの結果なので、統計DBには記録しない(生成元カード自身のプレイだけを数える)。
            is_token_play = (
                action.action_type == ActionType.PLAY_CARD and card is not None and card.is_token
            )
            if self.match_log is not None and self.match_id is not None and not is_token_play:
                self.match_log.log_action(self.match_id, action)
            if action.action_type == ActionType.PLAY_CARD:
                label = "を生成(トークン)" if is_token_play else "をプレイ"
                logger.info(
                    "[turn %s] %s が %s%s", action.turn, action.player.value, action.card_name or action.card_id, label
                )
                # プレイ/生成されたフォロワーは盤面に出たとみなして推定盤面に追加する
                # (盤面の画像照合は演出の重なりで機能しないため、履歴からの推定で代替)
                if (
                    card is not None
                    and card.card_type == "フォロワー"
                    and card.base_atk is not None
                    and card.base_hp is not None
                ):
                    self.tracker.add_inferred_unit(
                        action.player,
                        BoardUnit(card_id=card.card_id, name=card.name, atk=card.base_atk, hp=card.base_hp),
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
            elif action.action_type == ActionType.CREST_CHANGE:
                logger.info("[turn %s] %s のクレストが変化: %s", action.turn, action.player.value, action.detail)

        if any(a.player == Player.OPPONENT for a in new_actions):
            # 相手PPを直接読めていればそれを使う(相手ターン中の残りPP=次に出せるカードの上限)。
            # 読めていなければNoneを渡し、predictor側のターン数/実測プレイからの推定に任せる。
            observed_opponent_pp = (
                self.tracker.state.opponent_max_pp if self.tracker.state.opponent_max_pp > 0 else None
            )
            predictions = predict_opponent_next_actions(
                self.tracker,
                self.database,
                self.match_log,
                opponent_available_pp=observed_opponent_pp,
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
