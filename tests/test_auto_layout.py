import pytest

from svtracker.capture.auto_layout import interpolate_row


def test_interpolate_row_extends_evenly_spaced_rects_from_two_samples():
    rects = [(100, 900, 90, 130), (200, 900, 90, 130)]

    result = interpolate_row(rects, count=5)

    assert result == [
        (100, 900, 90, 130),
        (200, 900, 90, 130),
        (300, 900, 90, 130),
        (400, 900, 90, 130),
        (500, 900, 90, 130),
    ]


def test_interpolate_row_averages_spacing_from_multiple_samples():
    # 100, 100+90=190, 190+110=300 -> spacings 90 and 110, average 100
    rects = [(100, 0, 80, 120), (190, 0, 80, 120), (300, 0, 80, 120)]

    result = interpolate_row(rects, count=4)

    xs = [r[0] for r in result]
    assert xs == [100, 200, 300, 400]


def test_interpolate_row_handles_diagonal_rows():
    rects = [(0, 0, 50, 50), (10, 5, 50, 50)]

    result = interpolate_row(rects, count=3)

    assert result == [(0, 0, 50, 50), (10, 5, 50, 50), (20, 10, 50, 50)]


def test_interpolate_row_requires_at_least_two_samples():
    with pytest.raises(ValueError):
        interpolate_row([(0, 0, 10, 10)], count=5)


def test_interpolate_row_requires_positive_count():
    with pytest.raises(ValueError):
        interpolate_row([(0, 0, 10, 10), (10, 0, 10, 10)], count=0)
