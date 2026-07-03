import json
from unittest.mock import MagicMock, patch

from svtracker.capture.screen_capture import RegionSet, list_monitors


def test_add_and_remove_slot():
    regions = RegionSet()

    regions.add_slot("self_hand", (10, 20, 30, 40))
    regions.add_slot("self_hand", (50, 60, 30, 40))

    assert regions.slots("self_hand") == [(10, 20, 30, 40), (50, 60, 30, 40)]

    regions.remove_last_slot("self_hand")

    assert regions.slots("self_hand") == [(10, 20, 30, 40)]


def test_remove_last_slot_on_empty_is_noop():
    regions = RegionSet()

    regions.remove_last_slot("self_hand")

    assert regions.slots("self_hand") == []


def test_set_single_and_point():
    regions = RegionSet()

    regions.set_single("turn_indicator", (1, 2, 3, 4))
    regions.set_point("active_player_pixel", (100, 200))

    assert regions.single("turn_indicator") == (1, 2, 3, 4)
    assert regions.point("active_player_pixel") == (100, 200)


def test_clear_removes_region():
    regions = RegionSet()
    regions.set_single("turn_indicator", (1, 2, 3, 4))

    regions.clear("turn_indicator")

    assert regions.single("turn_indicator") is None


def test_save_and_load_round_trip(tmp_path):
    regions = RegionSet()
    regions.add_slot("self_hand", (10, 20, 30, 40))
    regions.set_single("turn_indicator", (1, 2, 3, 4))
    regions.set_point("active_player_pixel", (100, 200))

    path = tmp_path / "regions.json"
    regions.save(path)

    loaded = RegionSet.load(path)

    assert loaded.slots("self_hand") == [(10, 20, 30, 40)]
    assert loaded.single("turn_indicator") == (1, 2, 3, 4)
    assert loaded.point("active_player_pixel") == (100, 200)


def test_save_writes_plain_lists(tmp_path):
    regions = RegionSet()
    regions.add_slot("self_hand", (10, 20, 30, 40))
    path = tmp_path / "regions.json"

    regions.save(path)

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw == {"self_hand": [[10, 20, 30, 40]]}


def test_list_monitors_wraps_mss_monitor_dicts():
    fake_sct = MagicMock()
    fake_sct.monitors = [
        {"left": 0, "top": 0, "width": 3840, "height": 1080},  # index 0: 全モニタ結合
        {"left": 0, "top": 0, "width": 1920, "height": 1080},
        {"left": 1920, "top": 0, "width": 1920, "height": 1080},
    ]
    fake_sct.__enter__.return_value = fake_sct
    fake_sct.__exit__.return_value = False

    with patch("svtracker.capture.screen_capture.mss.mss", return_value=fake_sct):
        monitors = list_monitors()

    assert len(monitors) == 3
    assert monitors[0].index == 0
    assert monitors[0].is_virtual_combined is True
    assert monitors[1].index == 1
    assert monitors[1].width == 1920
    assert monitors[1].is_virtual_combined is False
    assert monitors[2].left == 1920
