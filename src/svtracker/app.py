"""画面キャプチャ→カード認識→対戦記録→予測/アドバイス を繋ぐメインループ."""
from __future__ import annotations

import logging
import time
from typing import Callable, Optional

from svtracker.cards.card_database import CardDatabase
from svtracker.cards.card_matcher import CardMatcher
from svtracker.cards.models import Card
from svtracker.cards.name_matcher import NameMatcher
from svtracker.capture import ocr_reader
from svtracker.capture.screen_capture import RegionSet, ScreenCapture
from svtracker.capture.stability import StableValue
from svtracker.config import Settings
from svtracker.game.match_tracker import MatchTracker
from svtracker.game.models import Action, ActionType, GameFormat, Player
from svtracker.storage.match_log import MatchLog

logger = logging.getLogger(__name__)

# OCR誤読の棄却に使う妥当範囲。
MAX_PLAUSIBLE_PP = 10
MAX_PLAUSIBLE_TURN = 40


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
        self.name_matcher = NameMatcher(self.database)
        self.regions = RegionSet.load(settings.regions_path) if settings.regions_path.exists() else None
        self.capture = ScreenCapture(
            monitor_index=settings.monitor_index, window_title_hint=settings.window_title_hint
        )
        if game_format == GameFormat.ROTATION and settings.rotation_min_card_set_id is None:
            logger.warning(
                "ローテーション形式が選択されていますが rotation_min_card_set_id が未設定のため、"
                "カードプールの絞り込みは行われません(実質アンリミテッドと同じ結果になります)。"
            )
        self.tracker = MatchTracker(self_clan=self_clan, opponent_clan=opponent_clan, game_format=game_format)

        self.match_log = MatchLog(settings.match_db_path) if enable_match_log else None
        self.match_id: Optional[int] = None
        if self.match_log is not None:
            self.match_id = self.match_log.start_match(self_clan, opponent_clan)

        # 1フレーム限りの誤読で状態が動かないよう、変化は2フレーム連続で確定させる。
        # (統計の文脈に使うターン・相手PPのみ。ライフ/EP/SEP/クレスト等の読み取りは
        #  誤検出ノイズが多く監視から削除した)
        self._stable: dict[str, StableValue] = {
            name: StableValue(required=2)
            for name in (
                "turn", "opponent_pp", "opponent_max_pp",
            )
        }
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
        # 名前OCR経路の時間的確認(連続で同じカードに一致した回数)と診断ログ抑制。
        self._reveal_name_candidate_id: Optional[str] = None
        self._reveal_name_candidate_frames: int = 0
        self._reveal_name_diag_last: Optional[str] = None

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

            name_rect = self.regions.single("play_reveal_name")
            if name_rect is None:
                lines.append("[play_reveal_name] 未設定(カード名OCRの枠。プリセット自動適用で入ります)")
            else:
                name_crop = self.regions.crop(frame, name_rect)
                name_crop.save(out / "crop_play_reveal_name.png")
                best_card, best_ratio, raw = self._read_reveal_name(frame)
                if raw:
                    if best_card is not None and best_ratio >= self.settings.reveal_name_min_ratio:
                        lines.append(
                            f"[play_reveal_name] OCR='{raw}' → {best_card.name} (一致度={best_ratio:.2f})"
                        )
                    else:
                        lines.append(
                            f"[play_reveal_name] OCR='{raw}' → 一致なし"
                            f"(最有力={best_card.name if best_card else '?'} 一致度={best_ratio:.2f})"
                        )
                else:
                    lines.append(
                        "[play_reveal_name] OCR結果なし(Tesseract本体+日本語データ jpn が必要。"
                        "crop_play_reveal_name.png にカード名がくっきり写っているか確認)"
                    )
                lines.append("")
        (out / "summary.txt").write_text("\n".join(lines), encoding="utf-8")
        logger.info("認識デバッグを保存しました: %s", out)
        return out

    def _detect_play_reveals(self, frame, turn: int) -> list[Action]:
        """プレイ表示(中央の大型カード)からプレイを検出する.

        主経路は「カード名バナーのOCR→DB名照合」(reveal_use_name_ocr)。ゲーム内の
        カード描画は光・アニメ絵・エフェクトで公式静止画とpHash距離が大きく、絵柄照合は
        実機で実用にならなかったため、明瞭な文字であるカード名を読む方式を既定にする。
        名前OCRが使えない(枠未設定/Tesseract未導入/一致せず)ときは、従来のpHash経路
        (ゆるい閾値 reveal_max_distance)にフォールバックする。
        """
        if self.settings.reveal_use_name_ocr:
            name_actions = self._detect_play_reveal_by_name(frame, turn)
            if name_actions:
                return name_actions
        return self._detect_play_reveal_by_phash(frame, turn)

    def _read_reveal_name(self, frame) -> tuple[Optional[Card], float, Optional[str]]:
        """プレイ表示のカード名バナー領域を帯状にスライドOCRし、最良一致を返す.

        バナーの縦位置はプレイ演出の進行で数十pxぶれる(実対戦動画で確認)ため、設定枠
        (縦に余裕を持たせた帯)の中を、枠高の約4割の高さの帯を約2割刻みでずらしながら
        1行OCR(--psm 7)し、DB名とのあいまい一致度が最も高い帯の結果を採用する。
        戻り値は (カード, 一致度, 生テキスト)。読めなければ (None, 0.0, None)。
        """
        rect = self.regions.single("play_reveal_name")
        if rect is None:
            return None, 0.0, None
        x, y, w, h = rect
        band_h = max(24, round(h * 0.4))
        step = max(8, round(h * 0.2))
        best_card: Optional[Card] = None
        best_ratio = 0.0
        best_raw: Optional[str] = None
        offset = 0
        while offset + band_h <= h + step:
            band_y = y + min(offset, max(0, h - band_h))
            crop = self.regions.crop(frame, (x, band_y, w, band_h))
            raw = ocr_reader.read_card_name(crop)
            offset += step
            if not raw:
                continue
            matched = self.name_matcher.match(raw, min_ratio=0.0)
            if matched is not None and matched[1] > best_ratio:
                best_card, best_ratio, best_raw = matched[0], matched[1], raw
        return best_card, best_ratio, best_raw

    def _detect_play_reveal_by_name(self, frame, turn: int) -> list[Action]:
        """プレイ表示のカード名バナーをOCRし、DB名とあいまい照合してプレイを検出する.

        誤検出(何も出ていないのに背景の帯OCRが偶然カード名に一致する)を防ぐため、
        同じカードが reveal_confirm_frames 連続で一致して初めて記録する。本物のプレイ表示は
        1〜2秒出続けるので連続一致するが、背景の偶然一致は毎フレーム別カードに化けるため
        弾ける。重複記録は _last_reveal で防ぐ。自分/相手は手番で判定。
        """
        if self.regions.single("play_reveal_name") is None:
            return []
        best_card, best_ratio, raw = self._read_reveal_name(frame)
        matched_ok = (
            raw is not None
            and best_card is not None
            and best_ratio >= self.settings.reveal_name_min_ratio
        )

        # 診断ログ: 読めた生テキストと照合結果(同じ生テキストの繰り返しは抑制)。
        if raw is not None and raw != self._reveal_name_diag_last:
            self._reveal_name_diag_last = raw
            if matched_ok:
                logger.info(
                    "プレイ表示の名前OCR: '%s' → %s (一致度=%.2f)", raw, best_card.name, best_ratio
                )
            elif best_card is not None and best_ratio >= 0.4:
                # 完全なゴミ(無関係なUI文字)まで毎回出すとうるさいので、それなりに
                # 近い候補があった場合だけ「一致なし」を知らせる
                logger.info(
                    "プレイ表示の名前OCR: '%s' → 一致なし(最有力=%s 一致度=%.2f < min_ratio=%.2f)",
                    raw,
                    best_card.name,
                    best_ratio,
                    self.settings.reveal_name_min_ratio,
                )

        # 連続一致カウント(同じカードが連続した回数を数える)
        if matched_ok and best_card.card_id == self._reveal_name_candidate_id:
            self._reveal_name_candidate_frames += 1
        elif matched_ok:
            self._reveal_name_candidate_id = best_card.card_id
            self._reveal_name_candidate_frames = 1
        else:
            self._reveal_name_candidate_id = None
            self._reveal_name_candidate_frames = 0
            self._last_reveal["play_reveal_name"] = None
            return []

        # 規定フレーム数連続で同じカードに一致するまでは記録しない(単発の偶然一致を弾く)
        if self._reveal_name_candidate_frames < max(1, self.settings.reveal_confirm_frames):
            return []

        card = best_card
        self._recognized_any_card = True
        if self._last_reveal.get("play_reveal_name") == card.card_id:
            return []
        self._last_reveal["play_reveal_name"] = card.card_id
        player = self.tracker.state.active_player or Player.OPPONENT
        return [
            Action(
                turn=turn,
                player=player,
                action_type=ActionType.PLAY_CARD,
                card_id=card.card_id,
                detail=f"プレイ表示の名前OCRから認識(一致度{best_ratio:.2f})",
            )
        ]

    def _detect_play_reveal_by_phash(self, frame, turn: int) -> list[Action]:
        """プレイ表示の絵柄をpHash照合してプレイを検出する(名前OCRのフォールバック).

        自分・相手どちらのプレイでも同じ中央位置(play_reveal)に出るので枠は1つにまとめ、
        「今出したのが自分か相手か」は手番(active_player)で判定する。手番が不明なときは
        相手プレイとして扱う。同じカードが表示され続けている間は1回だけ記録する。
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

    def _sync_pp(self, frame) -> None:
        """自分/相手のPP表示を読み取る(統計のシチュエーション記録とターン推定に使う).

        ライフ・EP/SEP・クレスト・各種カウンタの読み取りは、実機で誤検出が多くノイズに
        しかならなかったため監視から削除した(ユーザー要望)。PPはターン推定
        (最大PP=ターン数の下限)と「何PPでそのカードが出たか」の記録に必要なため残す。
        """
        pp_rect = self.regions.single("self_pp")
        if pp_rect is not None:
            pp = self._plausible_pp(ocr_reader.read_pp(self.regions.crop(frame, pp_rect)))
            if pp is not None:
                self.tracker.set_pp(*pp)

        # 相手PPは画面右上に「PP n /m」形式で常時表示されている(実対戦動画で確認)。
        opponent_pp_rect = self.regions.single("opponent_pp")
        if opponent_pp_rect is not None:
            crop = self.regions.crop(frame, opponent_pp_rect)
            raw = ocr_reader._ocr_digits_string(crop)
            observed = self._plausible_pp(ocr_reader.parse_pp_text(raw))
            confirmed = self._stable["opponent_pp"].update(observed)
            if confirmed is not None:
                self.tracker.set_opponent_pp(*confirmed)
            else:
                # 現在/最大の両方は読めなくても、最大PPだけ拾えればターン推定に使う
                # (装飾数字OCRで先頭桁が落ちて "/m" だけ読めることがあるため)。
                # 単発の誤読で最大PP=ターンが過大にならないよう2フレーム確定+単調増加に限る。
                max_pp = ocr_reader.parse_pp_max_text(raw)
                if max_pp is None or not 1 <= max_pp <= MAX_PLAUSIBLE_PP:
                    max_pp = None
                confirmed_max = self._stable["opponent_max_pp"].update(max_pp)
                if confirmed_max is not None and confirmed_max > self.tracker.state.opponent_max_pp:
                    self.tracker.set_opponent_pp(self.tracker.state.opponent_pp, confirmed_max)

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
        """1フレーム分の処理: キャプチャ→カードプレイ認識→統計記録.

        監視で行うのは「プレイされたカードの認識と記録」だけに絞っている。
        進化/超進化・ライフ変化・盤面ユニット消失・クレスト変化などのイベント検出、
        予測・アドバイス表示は、実機でOCR/ピクセル読み取りの誤検出が多くノイズにしか
        ならなかったため監視から削除した(ユーザー要望)。ターン・手番・PPだけは、
        統計のシチュエーション(「何ターン目/何PPでそのカードが出たか」「先攻/後攻」)に
        必要なため読み取りを続ける。
        """
        if self.regions is None:
            logger.error("regions.json が未設定です。config/regions.example.json を参考に作成してください。")
            return

        frame = self.capture.grab()
        self._step_count += 1

        # 統計の文脈(ターン数・先攻後攻・PP)に必要な読み取りのみ行う
        self._sync_turn_and_active_player(frame)
        self._sync_pp(frame)

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

        turn = self.tracker.current_turn or 1
        new_actions = self._detect_play_reveals(frame, turn)
        # プレイ表示からクラスを自動判別できる(デッキは単一クラス固定のため1枚で確定)
        self._infer_clans(Player.OPPONENT, [a.card_id for a in new_actions if a.player == Player.OPPONENT])
        self._infer_clans(Player.SELF, [a.card_id for a in new_actions if a.player == Player.SELF])

        # 同ターン・同プレイヤー・同カードのPLAY_CARDは最初の1件だけ通す(重複記録防止)
        seen_plays = {
            (a.player, a.card_id, a.turn)
            for a in self.tracker.actions
            if a.action_type == ActionType.PLAY_CARD
        }
        deduped: list[Action] = []
        for action in new_actions:
            if action.card_id:
                key = (action.player, action.card_id, action.turn)
                if key in seen_plays:
                    continue
                seen_plays.add(key)
            deduped.append(action)
        new_actions = deduped

        # このフレームの局面スナップショットを、この後記録する全アクションに紐づける
        # (何ターン目・何PP…でそのカードを出したか、を後から考察できるように)
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
            is_token_play = card is not None and card.is_token
            if self.match_log is not None and self.match_id is not None and not is_token_play:
                self.match_log.log_action(self.match_id, action)
            label = "を生成(トークン)" if is_token_play else "をプレイ"
            # 記録された文脈(ターン/PP)をそのままログに出し、統計に紐づく情報を確認できるようにする
            pp_note = ""
            if self.tracker.state.opponent_max_pp > 0:
                pp_note = f" / 相手PP {self.tracker.state.opponent_pp}/{self.tracker.state.opponent_max_pp}"
            logger.info(
                "[turn %s] %s が %s%s%s",
                action.turn,
                action.player.value,
                action.card_name or action.card_id,
                label,
                pp_note,
            )

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
