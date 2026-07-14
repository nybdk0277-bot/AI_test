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

    db = CardDatabase()
    for seed, (card_id, name, clan) in enumerate(
        [("c1", "カード1", "エルフ"), ("c2", "カード2", "ロイヤル")], start=2
    ):
        card = Card(card_id=card_id, name=name, clan=clan, cost=2, card_type="フォロワー")
        card.phash = compute_phash_hex(_card_image(seed))
        db.add(card)
    db.save(settings.card_db_path)

    regions = RegionSet()
    regions.set_single("opponent_play_reveal", (10, 10, 128, 180))
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
