"""プレイ表示(プレイ時に画面へ出る完全なカード)からのプレイ検出のテスト."""
from pathlib import Path
from unittest import mock

import pytest
from PIL import Image

from svtracker.app import MonitorApp
from svtracker.cards.card_database import CardDatabase
from svtracker.cards.hashing import compute_phash_hex
from svtracker.cards.models import Card
from svtracker.capture.screen_capture import RegionSet
from svtracker.config import Settings
from svtracker.game.models import ActionType, Player


def _card_image(seed: int) -> Image.Image:
    """カードごとに見た目が大きく異なるダミー画像を作る."""
    img = Image.new("RGB", (128, 180))
    px = img.load()
    for x in range(128):
        for y in range(180):
            px[x, y] = ((x * seed * 37) % 256, (y * (seed + 3) * 53) % 256, ((x + y) * seed) % 256)
    return img


@pytest.fixture()
def monitor_app(tmp_path: Path) -> MonitorApp:
    settings = Settings()
    settings.data_dir = tmp_path / "data"
    settings.cards_dir = tmp_path / "data" / "cards"
    settings.card_db_path = tmp_path / "data" / "cards" / "card_db.json"
    settings.match_db_path = tmp_path / "data" / "matches" / "m.db"
    settings.regions_path = tmp_path / "regions.json"
    # 既存テストは1呼び出し=1認識の意味で書かれているため、確認フレーム数は1にする
    # (時間的確認そのものは専用テストで検証する)。
    settings.reveal_confirm_frames = 1

    db = CardDatabase()
    for seed, (card_id, name, clan) in enumerate(
        [("c1", "カード1", "エルフ"), ("c2", "カード2", "ロイヤル")], start=2
    ):
        card = Card(card_id=card_id, name=name, clan=clan, cost=2, card_type="フォロワー")
        card.phash = compute_phash_hex(_card_image(seed))
        db.add(card)
    db.save(settings.card_db_path)

    regions = RegionSet()
    regions.set_single("play_reveal", (10, 10, 128, 180))
    regions.save(settings.regions_path)

    with mock.patch("svtracker.capture.screen_capture.ScreenCapture.__init__", return_value=None):
        app = MonitorApp(settings, enable_match_log=False)
    app.capture = mock.MagicMock()
    return app


def _frame_with(card_seed: int | None) -> Image.Image:
    frame = Image.new("RGB", (400, 300), (20, 20, 20))
    if card_seed is not None:
        frame.paste(_card_image(card_seed), (10, 10))
    return frame


def test_reveal_emits_play_once_and_resets_after_disappearing(monitor_app):
    frame_c1 = _frame_with(2)

    actions = monitor_app._detect_play_reveals(frame_c1, turn=3)
    assert len(actions) == 1
    assert actions[0].action_type == ActionType.PLAY_CARD
    assert actions[0].player == Player.OPPONENT
    assert actions[0].card_id == "c1"

    # 同じカードが表示され続けている間は再記録しない
    assert monitor_app._detect_play_reveals(frame_c1, turn=3) == []

    # 表示が消えてから再表示されたら(同カード連続プレイ)再度記録する
    assert monitor_app._detect_play_reveals(_frame_with(None), turn=3) == []
    actions = monitor_app._detect_play_reveals(frame_c1, turn=3)
    assert len(actions) == 1


def test_reveal_detects_card_change_without_gap(monitor_app):
    monitor_app._detect_play_reveals(_frame_with(2), turn=3)

    actions = monitor_app._detect_play_reveals(_frame_with(3), turn=3)

    assert len(actions) == 1
    assert actions[0].card_id == "c2"


def test_reveal_ignores_background_without_card(monitor_app):
    assert monitor_app._detect_play_reveals(_frame_with(None), turn=1) == []


def test_reveal_attributes_to_self_when_self_is_active(monitor_app):
    # 手番が自分なら中央のプレイ表示は自分のプレイとして記録する
    monitor_app.tracker.state.active_player = Player.SELF
    actions = monitor_app._detect_play_reveals(_frame_with(2), turn=3)
    assert len(actions) == 1
    assert actions[0].player == Player.SELF


def test_reveal_defaults_to_opponent_when_active_player_unknown(monitor_app):
    monitor_app.tracker.state.active_player = None
    actions = monitor_app._detect_play_reveals(_frame_with(2), turn=3)
    assert len(actions) == 1
    assert actions[0].player == Player.OPPONENT


def test_reveal_requires_consecutive_frames_to_confirm(monitor_app):
    # 確認フレーム数2: 同じカードが2フレーム連続で最有力になって初めて記録する。
    monitor_app.settings.reveal_confirm_frames = 2
    frame = _frame_with(2)
    # 1フレーム目は保留(記録しない)
    assert monitor_app._detect_play_reveals(frame, turn=3) == []
    # 2フレーム目で確定
    actions = monitor_app._detect_play_reveals(frame, turn=3)
    assert len(actions) == 1
    assert actions[0].card_id == "c1"


def test_reveal_rejects_single_frame_flicker(monitor_app):
    # 別カードが1フレームずつ交互に最有力になっても、連続確認が途切れるので記録しない。
    monitor_app.settings.reveal_confirm_frames = 2
    assert monitor_app._detect_play_reveals(_frame_with(2), turn=3) == []
    assert monitor_app._detect_play_reveals(_frame_with(3), turn=3) == []
    assert monitor_app._detect_play_reveals(_frame_with(2), turn=3) == []


def test_reveal_name_ocr_path_records_play(monitor_app):
    # 名前OCR経路: カード名バナーをOCRしてDB名に一致すればプレイとして記録する。
    monitor_app.settings.reveal_confirm_frames = 1
    monitor_app.regions.set_single("play_reveal_name", (10, 10, 100, 30))
    monitor_app.tracker.state.active_player = Player.OPPONENT
    frame = _frame_with(2)
    with mock.patch("svtracker.capture.ocr_reader.read_card_name", return_value="カード1"):
        actions = monitor_app._detect_play_reveals(frame, turn=5)
    assert len(actions) == 1
    assert actions[0].card_id == "c1"
    assert actions[0].player == Player.OPPONENT
    assert "名前OCR" in actions[0].detail


def test_reveal_name_ocr_tolerates_minor_ocr_error(monitor_app):
    monitor_app.settings.reveal_confirm_frames = 1
    monitor_app.regions.set_single("play_reveal_name", (10, 10, 100, 30))
    frame = _frame_with(2)
    # 「カード1」を「カ一ド1」(長音誤読)と読んでも一致する
    with mock.patch("svtracker.capture.ocr_reader.read_card_name", return_value="カ一ド1"):
        actions = monitor_app._detect_play_reveals(frame, turn=5)
    assert len(actions) == 1
    assert actions[0].card_id == "c1"


def test_reveal_name_ocr_falls_back_to_phash_when_unavailable(monitor_app):
    # OCRが使えない(None)ときは従来のpHash経路にフォールバックする。
    monitor_app.settings.reveal_confirm_frames = 1
    monitor_app.regions.set_single("play_reveal_name", (10, 10, 100, 30))
    frame = _frame_with(2)
    with mock.patch("svtracker.capture.ocr_reader.read_card_name", return_value=None):
        actions = monitor_app._detect_play_reveals(frame, turn=5)
    assert len(actions) == 1
    assert actions[0].card_id == "c1"  # pHashで一致


def test_reveal_name_ocr_requires_two_consecutive_frames(monitor_app):
    # 名前OCR経路も確認フレーム数2なら、同じカードが連続2回一致して初めて記録する。
    monitor_app.settings.reveal_confirm_frames = 2
    monitor_app.regions.set_single("play_reveal_name", (10, 10, 100, 30))
    frame = _frame_with(2)
    with mock.patch("svtracker.capture.ocr_reader.read_card_name", return_value="カード1"):
        assert monitor_app._detect_play_reveals(frame, turn=5) == []  # 1回目は保留
        actions = monitor_app._detect_play_reveals(frame, turn=5)  # 2回目で確定
    assert len(actions) == 1
    assert actions[0].card_id == "c1"


def test_reveal_name_ocr_single_frame_garbage_not_recorded(monitor_app):
    # 何も出ていない時に別カードへ1フレームずつ偶然一致しても、連続が途切れて記録しない。
    monitor_app.settings.reveal_confirm_frames = 2
    monitor_app.regions.set_single("play_reveal_name", (10, 10, 100, 30))
    # 背景フレーム(カード無し)なので、名前OCRが偶然一致してもpHashフォールバックは効かない
    frame = _frame_with(None)
    c1 = monitor_app.database.get("c1")
    c2 = monitor_app.database.get("c2")
    # 1フレームごとに別カードへ一致(偶然一致を模擬)。連続が途切れるので記録されない。
    seq = iter([(c1, 0.9, "カード1"), (c2, 0.9, "カード2"), (c1, 0.9, "カード1")])
    with mock.patch.object(monitor_app, "_read_reveal_name", side_effect=lambda *a, **k: next(seq)):
        assert monitor_app._detect_play_reveals(frame, turn=5) == []
        assert monitor_app._detect_play_reveals(frame, turn=5) == []
        assert monitor_app._detect_play_reveals(frame, turn=5) == []
