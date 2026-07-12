import sys
import types

from PIL import Image

from svtracker.capture.ocr_reader import (
    classify_active_player,
    count_lit_pips,
    parse_int_text,
    parse_pp_text,
    pip_is_lit,
)
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


def _install_fake_pytesseract(monkeypatch, error_cls):
    fake_pytesseract_submodule = types.ModuleType("pytesseract.pytesseract")
    fake_pytesseract_submodule.TesseractNotFoundError = error_cls

    fake_pytesseract = types.ModuleType("pytesseract")
    fake_pytesseract.pytesseract = fake_pytesseract_submodule

    def _raise_not_found(*_args, **_kwargs):
        raise error_cls("tesseract is not installed or it's not in your PATH")

    fake_pytesseract.image_to_string = _raise_not_found
    monkeypatch.setitem(sys.modules, "pytesseract", fake_pytesseract)
    monkeypatch.setitem(sys.modules, "pytesseract.pytesseract", fake_pytesseract_submodule)


def test_ocr_digits_string_warns_once_when_tesseract_binary_missing(monkeypatch, caplog):
    from svtracker.capture import ocr_reader

    class FakeTesseractNotFoundError(Exception):
        pass

    _install_fake_pytesseract(monkeypatch, FakeTesseractNotFoundError)
    monkeypatch.setattr(ocr_reader, "_warned_no_tesseract_binary", False)

    with caplog.at_level("WARNING"):
        assert ocr_reader._ocr_digits_string(object()) is None
        assert ocr_reader._ocr_digits_string(object()) is None

    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert "Tesseract本体が見つかりません" in warnings[0].message


def _pip(color: tuple[int, int, int]) -> Image.Image:
    return Image.new("RGB", (20, 22), color)


def test_pip_is_lit_ep_gold_and_dark():
    # 実フレーム採取色: 点灯EP=(206,180,76) / 消灯=(95,88,72)
    assert pip_is_lit(_pip((206, 180, 76)), "ep")
    assert not pip_is_lit(_pip((95, 88, 72)), "ep")


def test_pip_is_lit_sep_purple_and_dark():
    # 実フレーム採取色: 点灯SEP=(178,151,214) / 消灯=(83,70,95)
    assert pip_is_lit(_pip((178, 151, 214)), "sep")
    assert not pip_is_lit(_pip((83, 70, 95)), "sep")


def test_pip_ep_color_does_not_count_as_sep():
    assert not pip_is_lit(_pip((206, 180, 76)), "sep")
    assert not pip_is_lit(_pip((178, 151, 214)), "ep")


def test_count_lit_pips_counts_only_lit():
    pips = [_pip((206, 180, 76)), _pip((95, 88, 72)), _pip((210, 185, 80))]
    assert count_lit_pips(pips, "ep") == 2
    assert count_lit_pips([], "ep") == 0
