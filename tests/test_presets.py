from svtracker.capture.presets import (
    PRESET_BASE_HEIGHT,
    PRESET_BASE_WIDTH,
    preset_region_set,
)


def test_preset_at_base_resolution_matches_base_coordinates():
    rs = preset_region_set(PRESET_BASE_WIDTH, PRESET_BASE_HEIGHT)
    # 基準解像度ではスケール1.0なので座標がそのまま入る
    assert rs.single("self_pp") == (1660, 630, 210, 55)
    assert rs.point("active_player_pixel") == (1740, 470)
    ep_pips = rs.slots("self_ep_pips")
    assert ep_pips[0] == (810, 784, 20, 22)


def test_preset_scales_to_half_resolution():
    rs = preset_region_set(PRESET_BASE_WIDTH // 2, PRESET_BASE_HEIGHT // 2)
    x, y, w, h = rs.single("self_pp")
    assert (x, y, w, h) == (830, 315, 105, 28)
    px, py = rs.point("active_player_pixel")
    assert (px, py) == (870, 235)


def test_preset_includes_all_card_and_ui_regions():
    rs = preset_region_set(PRESET_BASE_WIDTH, PRESET_BASE_HEIGHT)
    assert len(rs.slots("self_hand")) == 5
    assert len(rs.slots("self_board")) == 5
    assert len(rs.slots("opponent_board")) == 5
    for name in ("self_life", "opponent_life", "self_pp", "opponent_pp", "combo_count"):
        assert rs.single(name) is not None
    for name in ("self_crest_slots", "opponent_crest_slots", "self_ep_pips", "opponent_sep_pips"):
        assert rs.slots(name)
