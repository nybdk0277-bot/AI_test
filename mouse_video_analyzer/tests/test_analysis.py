import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.analysis import compute_heatmap, compute_speeds, detect_clicks, export_csv  # noqa: E402
from app.tracker import TrackPoint  # noqa: E402


def make_points():
    points = []
    t = 0.0
    # Moves fast for 10 frames, then stays still for 10 frames (a "click").
    for i in range(10):
        points.append(TrackPoint(frame_idx=i, time_sec=t, x=i * 20.0, y=0.0, confidence=1.0))
        t += 1 / 30
    still_x = points[-1].x
    for i in range(10, 20):
        points.append(TrackPoint(frame_idx=i, time_sec=t, x=still_x, y=0.0, confidence=1.0))
        t += 1 / 30
    return points


def test_compute_speeds_length_matches_points():
    points = make_points()
    speeds = compute_speeds(points)
    assert len(speeds) == len(points)
    assert speeds[0] == 0.0
    assert speeds[5] > 0


def test_detect_clicks_finds_dwell_after_movement():
    points = make_points()
    speeds = compute_speeds(points)
    clicks = detect_clicks(points, speeds)
    assert len(clicks) == 1
    assert clicks[0].frame_idx == 10


def test_compute_heatmap_shape():
    points = make_points()
    heat = compute_heatmap(points, width=300, height=50)
    assert heat.shape == (50, 300, 3)


def test_export_csv_writes_file(tmp_path):
    points = make_points()
    speeds = compute_speeds(points)
    out = tmp_path / "out.csv"
    export_csv(points, speeds, str(out))
    content = out.read_text(encoding="utf-8-sig")
    assert "frame" in content.splitlines()[0]
    assert len(content.splitlines()) == len(points) + 1
