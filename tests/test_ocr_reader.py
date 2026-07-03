from svtracker.capture.ocr_reader import classify_active_player, parse_int_text, parse_pp_text
from svtracker.game.models import Player


def test_parse_int_text_extracts_first_number():
    assert parse_int_text("ターン 12") == 12
    assert parse_int_text("3") == 3
    assert parse_int_text("") is None
    assert parse_int_text(None) is None
    assert parse_int_text("no digits here") is None


def test_parse_pp_text_extracts_current_and_max():
    assert parse_pp_text("3/6") == (3, 6)
    assert parse_pp_text(" 10 / 10 ") == (10, 10)
    assert parse_pp_text("garbage") is None
    assert parse_pp_text(None) is None


def test_classify_active_player_picks_closest_reference_color():
    self_color = (255, 215, 0)
    opponent_color = (200, 30, 30)

    assert classify_active_player((250, 210, 5), self_color, opponent_color) == Player.SELF
    assert classify_active_player((195, 35, 25), self_color, opponent_color) == Player.OPPONENT


def test_classify_active_player_returns_none_when_too_far_from_both():
    self_color = (255, 215, 0)
    opponent_color = (200, 30, 30)

    result = classify_active_player((0, 255, 255), self_color, opponent_color, max_distance=30)

    assert result is None
