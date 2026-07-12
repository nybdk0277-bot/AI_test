"""スクリーンショットを表示し、クリック&ドラッグで矩形/クリックで座標を拾えるCanvas.

キャリブレーション画面の中核部品。実画面の解像度そのままだとウィンドウに収まらないため、
キャンバスの現在サイズに合わせて縦横比を維持したまま縮小し(self._scale)、中央に表示する。
クリック/ドラッグ座標は表示オフセット(レターボックス分)を差し引いて実画像座標に変換して
呼び出し元へ返す。ウィンドウのリサイズにも追従する。
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from PIL import Image, ImageTk


class RegionCanvas(ttk.Frame):
    def __init__(self, parent, max_width: int = 900, max_height: int = 650):
        super().__init__(parent)
        self.max_width = max_width
        self.max_height = max_height
        self.canvas = tk.Canvas(self, width=max_width, height=max_height, bg="#202020")
        self.canvas.pack(fill="both", expand=True)

        self._pil_image: Optional[Image.Image] = None
        self._photo: Optional[ImageTk.PhotoImage] = None
        self._scale = 1.0
        self._offset = (0, 0)  # レターボックス(中央寄せ)のオフセット(表示座標系)
        self._mode = "rect"  # "rect" または "point"
        self._drag_start: Optional[tuple[int, int]] = None

        self._overlay_rects: list[tuple[int, int, int, int, str, str]] = []
        self._overlay_points: list[tuple[int, int, str, str]] = []

        self.on_rect_drawn: Optional[Callable[[int, int, int, int], None]] = None
        self.on_point_picked: Optional[Callable[[int, int], None]] = None

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Configure>", self._on_canvas_resized)

    def set_image(self, image: Image.Image) -> None:
        self._pil_image = image
        self._render()

    def _on_canvas_resized(self, _event) -> None:
        self._render()

    def _render(self) -> None:
        if self._pil_image is None:
            return
        # キャンバスの実サイズ(まだ描画前で1x1のことがあるため、その場合は既定サイズを使う)
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if cw <= 1 or ch <= 1:
            cw, ch = self.max_width, self.max_height

        w, h = self._pil_image.size
        # 縦横で同一の縮小率(=縦横比を厳密に維持)。拡大はしない(ぼやけ防止)。
        self._scale = min(cw / w, ch / h, 1.0)
        disp_w, disp_h = max(1, int(w * self._scale)), max(1, int(h * self._scale))
        self._offset = ((cw - disp_w) // 2, (ch - disp_h) // 2)

        displayed = self._pil_image.resize((disp_w, disp_h))
        self._photo = ImageTk.PhotoImage(displayed)
        self.canvas.delete("all")
        self.canvas.create_image(self._offset[0], self._offset[1], anchor="nw", image=self._photo, tags="bg")
        self._redraw_overlays()

    def set_mode(self, mode: str) -> None:
        assert mode in ("rect", "point")
        self._mode = mode

    def set_overlays(
        self,
        rects: Optional[list[tuple[int, int, int, int, str, str]]] = None,
        points: Optional[list[tuple[int, int, str, str]]] = None,
    ) -> None:
        """rects: (x, y, w, h, label, color) のリスト。points: (x, y, label, color) のリスト。"""
        self._overlay_rects = rects or []
        self._overlay_points = points or []
        self._redraw_overlays()

    def _redraw_overlays(self) -> None:
        if self._pil_image is None:
            return
        self.canvas.delete("overlay")
        ox, oy = self._offset
        for x, y, w, h, label, color in self._overlay_rects:
            sx, sy = ox + x * self._scale, oy + y * self._scale
            sw, sh = w * self._scale, h * self._scale
            self.canvas.create_rectangle(sx, sy, sx + sw, sy + sh, outline=color, width=2, tags="overlay")
            if label:
                self.canvas.create_text(sx + 2, sy + 2, text=label, anchor="nw", fill=color, tags="overlay")
        for x, y, label, color in self._overlay_points:
            sx, sy = ox + x * self._scale, oy + y * self._scale
            r = 5
            self.canvas.create_oval(sx - r, sy - r, sx + r, sy + r, outline=color, width=2, tags="overlay")
            if label:
                self.canvas.create_text(sx + 8, sy - 8, text=label, anchor="w", fill=color, tags="overlay")

    def _to_real(self, x: int, y: int) -> tuple[int, int]:
        """表示座標→実画像座標。レターボックスのオフセットを差し引き、画像範囲内にクランプする."""
        rx = int((x - self._offset[0]) / self._scale)
        ry = int((y - self._offset[1]) / self._scale)
        if self._pil_image is not None:
            w, h = self._pil_image.size
            rx = min(max(rx, 0), w - 1)
            ry = min(max(ry, 0), h - 1)
        return rx, ry

    def _on_press(self, event) -> None:
        if self._pil_image is None:
            return
        if self._mode == "point":
            rx, ry = self._to_real(event.x, event.y)
            if self.on_point_picked:
                self.on_point_picked(rx, ry)
            return
        self._drag_start = (event.x, event.y)
        self.canvas.delete("drag")
        self.canvas.create_rectangle(event.x, event.y, event.x, event.y, outline="#00ffcc", width=2, tags="drag")

    def _on_drag(self, event) -> None:
        if self._mode != "rect" or self._drag_start is None:
            return
        x0, y0 = self._drag_start
        self.canvas.coords("drag", x0, y0, event.x, event.y)

    def _on_release(self, event) -> None:
        if self._mode != "rect" or self._drag_start is None:
            return
        x0, y0 = self._drag_start
        self._drag_start = None
        self.canvas.delete("drag")

        left, top = min(x0, event.x), min(y0, event.y)
        width, height = abs(event.x - x0), abs(event.y - y0)
        if width < 3 or height < 3:
            return  # 誤クリック(ドラッグなし)は無視

        rx, ry = self._to_real(left, top)
        rx2, ry2 = self._to_real(left + width, top + height)
        rw, rh = rx2 - rx, ry2 - ry
        if rw < 1 or rh < 1:
            return
        if self.on_rect_drawn:
            self.on_rect_drawn(rx, ry, rw, rh)
