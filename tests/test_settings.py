from svtracker.config import Settings


def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    settings = Settings()
    settings.self_turn_color = (10, 20, 30)
    settings.opponent_turn_color = (40, 50, 60)
    settings.capture_interval_sec = 2.5

    settings.save(path)
    loaded = Settings.load(path)

    assert loaded.self_turn_color == (10, 20, 30)
    assert loaded.opponent_turn_color == (40, 50, 60)
    assert loaded.capture_interval_sec == 2.5


def test_load_without_file_returns_defaults(tmp_path):
    loaded = Settings.load(tmp_path / "does_not_exist.json")

    assert loaded.self_turn_color == (255, 215, 0)
    assert loaded.game_format == "unlimited"
    assert loaded.rotation_min_card_set_id is None


def test_save_and_load_round_trip_includes_format_settings(tmp_path):
    path = tmp_path / "settings.json"
    settings = Settings()
    settings.game_format = "rotation"
    settings.rotation_min_card_set_id = 42

    settings.save(path)
    loaded = Settings.load(path)

    assert loaded.game_format == "rotation"
    assert loaded.rotation_min_card_set_id == 42
