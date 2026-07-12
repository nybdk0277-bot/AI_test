import random

from PIL import Image

from svtracker.capture.crest_reader import count_occupied_slots, slot_is_occupied


def _flat_dark_slot() -> Image.Image:
    """空のクレスト枠を模した、暗くのっぺりした画像(実測: 明るさ45-67 / ばらつき15-18)."""
    img = Image.new("RGB", (70, 70), (50, 40, 35))
    rng = random.Random(42)
    for x in range(0, 70, 3):
        for y in range(0, 70, 3):
            noise = rng.randint(-10, 10)
            img.putpixel((x, y), (50 + noise, 40 + noise, 35 + noise))
    return img


def _bright_icon_slot() -> Image.Image:
    """クレストアイコンを模した、明るく色のばらつきが大きい画像(実測: 明るさ117 / ばらつき62)."""
    img = Image.new("RGB", (70, 70))
    rng = random.Random(7)
    for x in range(70):
        for y in range(70):
            img.putpixel((x, y), (rng.randint(30, 250), rng.randint(30, 250), rng.randint(30, 250)))
    return img


def test_flat_dark_slot_is_not_occupied():
    assert not slot_is_occupied(_flat_dark_slot())


def test_bright_varied_slot_is_occupied():
    assert slot_is_occupied(_bright_icon_slot())


def test_count_occupied_slots_mixed():
    slots = [_flat_dark_slot(), _bright_icon_slot(), _flat_dark_slot(), _bright_icon_slot()]
    assert count_occupied_slots(slots) == 2


def test_count_occupied_slots_empty_list():
    assert count_occupied_slots([]) == 0
