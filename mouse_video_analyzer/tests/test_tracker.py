import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.tracker import CursorTracker, VideoInfo  # noqa: E402

WIDTH, HEIGHT, FPS, N_FRAMES = 320, 240, 30.0, 60
CURSOR_SIZE = 16


def make_synthetic_video(path: str) -> list[tuple[int, int]]:
    """Writes a synthetic video with a bright square cursor moving in a
    straight line over a static textured background; returns ground-truth
    centers. The background is deliberately low-entropy so lossy video
    compression doesn't destroy the cursor shape used for template matching.
    """
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(path, fourcc, FPS, (WIDTH, HEIGHT))
    base = np.full((HEIGHT, WIDTH, 3), 60, dtype=np.uint8)
    for gx in range(0, WIDTH, 20):
        cv2.line(base, (gx, 0), (gx, HEIGHT), (90, 90, 90), 1)
    for gy in range(0, HEIGHT, 20):
        cv2.line(base, (0, gy), (WIDTH, gy), (90, 90, 90), 1)

    centers = []
    for i in range(N_FRAMES):
        frame = base.copy()
        cx = 20 + i * 4
        cy = 20 + i * 3
        half = CURSOR_SIZE // 2
        # A bordered, asymmetric marker (not a flat fill) so normalized
        # cross-correlation has real texture/variance to lock onto.
        cv2.rectangle(frame, (cx - half, cy - half), (cx + half, cy + half), (255, 255, 255), -1)
        cv2.rectangle(frame, (cx - half, cy - half), (cx + half, cy + half), (0, 0, 0), 2)
        cv2.line(frame, (cx - half, cy - half), (cx + half, cy + half), (0, 0, 0), 2)
        writer.write(frame)
        centers.append((cx, cy))
    writer.release()
    return centers


def test_cursor_tracker_follows_synthetic_cursor(tmp_path):
    video_path = str(tmp_path / "synthetic.mp4")
    centers = make_synthetic_video(video_path)

    video = VideoInfo(video_path)
    assert video.frame_count == N_FRAMES

    first_frame = video.read_frame(0)
    cx0, cy0 = centers[0]
    bbox = (cx0 - CURSOR_SIZE // 2, cy0 - CURSOR_SIZE // 2, CURSOR_SIZE, CURSOR_SIZE)

    tracker = CursorTracker(video)
    tracker.set_template(first_frame, bbox)
    points = tracker.track()

    assert len(points) == N_FRAMES
    # Allow a few pixels of slack; the tracker should stay close to ground truth.
    for p, (gx, gy) in zip(points, centers):
        assert abs(p.x - gx) <= 3
        assert abs(p.y - gy) <= 3
