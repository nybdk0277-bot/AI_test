import json

from svtracker.capture.screen_capture import RegionSet


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
