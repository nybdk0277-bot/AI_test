"""Derived analysis on top of raw cursor track points.

- speed over time
- click / dwell detection (heuristic: cursor moves, then stops for a while)
- position heatmap
- CSV export
- trajectory-overlay video rendering
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from typing import Callable, Optional

import cv2
import numpy as np

from .tracker import TrackPoint, VideoInfo

MOVING_SPEED_PX_S = 40.0    # above this, the cursor is considered "moving"
STOPPED_SPEED_PX_S = 15.0   # below this, the cursor is considered "stopped"
MIN_DWELL_SEC = 0.15        # minimum stop duration to count as a click/dwell event


@dataclass
class ClickEvent:
    frame_idx: int
    time_sec: float
    x: float
    y: float
    dwell_sec: float


def compute_speeds(points: list[TrackPoint]) -> list[float]:
    """Pixel/second speed for each point (first point has speed 0)."""
    speeds = [0.0]
    for prev, cur in zip(points, points[1:]):
        dt = cur.time_sec - prev.time_sec
        if dt <= 0:
            speeds.append(0.0)
            continue
        dist = ((cur.x - prev.x) ** 2 + (cur.y - prev.y) ** 2) ** 0.5
        speeds.append(dist / dt)
    return speeds


def detect_clicks(points: list[TrackPoint], speeds: list[float]) -> list[ClickEvent]:
    """Heuristic dwell detector: a click/operation candidate is a period where
    the cursor was moving and then comes to rest for at least MIN_DWELL_SEC.
    """
    events: list[ClickEvent] = []
    n = len(points)
    i = 0
    was_moving = False
    while i < n:
        if speeds[i] <= STOPPED_SPEED_PX_S:
            start = i
            while i < n and speeds[i] <= STOPPED_SPEED_PX_S:
                i += 1
            end = i - 1
            dwell = points[end].time_sec - points[start].time_sec
            if was_moving and dwell >= MIN_DWELL_SEC:
                mid = points[start]
                events.append(ClickEvent(
                    frame_idx=mid.frame_idx,
                    time_sec=mid.time_sec,
                    x=mid.x,
                    y=mid.y,
                    dwell_sec=dwell,
                ))
            was_moving = False
        else:
            if speeds[i] >= MOVING_SPEED_PX_S:
                was_moving = True
            i += 1
    return events


def compute_heatmap(points: list[TrackPoint], width: int, height: int) -> np.ndarray:
    """Returns a BGR heatmap image (uint8) of cursor dwell density."""
    accum = np.zeros((height, width), dtype=np.float32)
    for p in points:
        x, y = int(p.x), int(p.y)
        if 0 <= x < width and 0 <= y < height:
            accum[y, x] += 1.0
    accum = cv2.GaussianBlur(accum, (0, 0), sigmaX=15)
    if accum.max() > 0:
        accum = accum / accum.max()
    heat_u8 = (accum * 255).astype(np.uint8)
    return cv2.applyColorMap(heat_u8, cv2.COLORMAP_JET)


def export_csv(points: list[TrackPoint], speeds: list[float], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["frame", "time_sec", "x", "y", "confidence", "speed_px_s"])
        for p, s in zip(points, speeds):
            writer.writerow([p.frame_idx, f"{p.time_sec:.3f}", f"{p.x:.1f}", f"{p.y:.1f}",
                              f"{p.confidence:.3f}", f"{s:.1f}"])


def export_clicks_csv(events: list[ClickEvent], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["frame", "time_sec", "x", "y", "dwell_sec"])
        for e in events:
            writer.writerow([e.frame_idx, f"{e.time_sec:.3f}", f"{e.x:.1f}", f"{e.y:.1f}",
                              f"{e.dwell_sec:.3f}"])


def render_trajectory_video(
    video: VideoInfo,
    points: list[TrackPoint],
    clicks: list[ClickEvent],
    output_path: str,
    trail_len: int = 60,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> None:
    cap = cv2.VideoCapture(video.path)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(output_path, fourcc, video.fps, (video.width, video.height))
    click_by_frame = {e.frame_idx: e for e in clicks}

    idx = 0
    total = video.frame_count or 1
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        start = max(0, idx - trail_len)
        trail = points[start:idx + 1]
        for j in range(1, len(trail)):
            p0, p1 = trail[j - 1], trail[j]
            cv2.line(frame, (int(p0.x), int(p0.y)), (int(p1.x), int(p1.y)), (0, 255, 255), 2)
        if idx < len(points):
            p = points[idx]
            cv2.circle(frame, (int(p.x), int(p.y)), 6, (0, 0, 255), -1)
        if idx in click_by_frame:
            e = click_by_frame[idx]
            cv2.circle(frame, (int(e.x), int(e.y)), 16, (255, 0, 255), 3)
        writer.write(frame)
        idx += 1
        if progress_callback:
            progress_callback(idx, total)

    cap.release()
    writer.release()
