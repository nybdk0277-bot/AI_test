"""Mouse pointer tracking core logic.

Tracks the position of a mouse cursor across the frames of a screen-recording
video using template matching. The user selects a crop of the cursor icon
from the first frame; that crop is then searched for in a window around the
previously known position on each subsequent frame (falling back to a
full-frame search when the local search loses confidence).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import cv2
import numpy as np

# Confidence (normalized cross-correlation score) below which a local search
# is considered lost and a full-frame search is attempted instead.
CONFIDENCE_THRESHOLD = 0.55


@dataclass
class TrackPoint:
    frame_idx: int
    time_sec: float
    x: float  # cursor center, in pixels
    y: float
    confidence: float


class VideoInfo:
    def __init__(self, path: str):
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            raise IOError(f"動画ファイルを開けませんでした: {path}")
        self.path = path
        self.frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()

    def read_frame(self, index: int) -> Optional[np.ndarray]:
        cap = cv2.VideoCapture(self.path)
        cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = cap.read()
        cap.release()
        return frame if ok else None


class CursorTracker:
    """Tracks a user-selected cursor template through a video."""

    def __init__(self, video: VideoInfo):
        self.video = video
        self.template_gray: Optional[np.ndarray] = None
        self.template_size: tuple[int, int] = (0, 0)  # (w, h)

    def set_template(self, frame: np.ndarray, bbox: tuple[int, int, int, int]) -> None:
        """bbox is (x, y, w, h) in pixel coordinates on `frame`."""
        x, y, w, h = bbox
        if w <= 2 or h <= 2:
            raise ValueError("選択範囲が小さすぎます")
        crop = frame[y:y + h, x:x + w]
        self.template_gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        self.template_size = (w, h)

    def _search(self, gray: np.ndarray, region: tuple[int, int, int, int]) -> tuple[float, float, float]:
        """Search for the template inside `region` = (x0, y0, x1, y1) of `gray`.

        Returns (center_x, center_y, confidence) in full-frame coordinates.
        """
        x0, y0, x1, y1 = region
        tw, th = self.template_size
        window = gray[y0:y1, x0:x1]
        if window.shape[0] < th or window.shape[1] < tw:
            return 0.0, 0.0, -1.0
        result = cv2.matchTemplate(window, self.template_gray, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        cx = x0 + max_loc[0] + tw / 2.0
        cy = y0 + max_loc[1] + th / 2.0
        return cx, cy, max_val

    def track(
        self,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> list[TrackPoint]:
        if self.template_gray is None:
            raise RuntimeError("先にカーソルのテンプレートを設定してください")

        cap = cv2.VideoCapture(self.video.path)
        points: list[TrackPoint] = []
        tw, th = self.template_size
        margin = max(tw, th) * 4
        last_xy: Optional[tuple[float, float]] = None
        frame_idx = 0
        total = self.video.frame_count or 1

        while True:
            if cancel_check and cancel_check():
                break
            ok, frame = cap.read()
            if not ok:
                break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            h, w = gray.shape[:2]

            cx = cy = conf = None
            if last_xy is not None:
                x0 = max(0, int(last_xy[0] - margin))
                y0 = max(0, int(last_xy[1] - margin))
                x1 = min(w, int(last_xy[0] + margin))
                y1 = min(h, int(last_xy[1] + margin))
                cx, cy, conf = self._search(gray, (x0, y0, x1, y1))

            if last_xy is None or conf is None or conf < CONFIDENCE_THRESHOLD:
                cx, cy, conf = self._search(gray, (0, 0, w, h))

            if conf is not None and conf >= 0 and cx is not None:
                last_xy = (cx, cy)
            elif last_xy is not None:
                cx, cy = last_xy
                conf = 0.0
            else:
                cx, cy, conf = 0.0, 0.0, 0.0

            points.append(TrackPoint(
                frame_idx=frame_idx,
                time_sec=frame_idx / self.video.fps,
                x=cx,
                y=cy,
                confidence=conf,
            ))

            frame_idx += 1
            if progress_callback:
                progress_callback(frame_idx, total)

        cap.release()
        return points
