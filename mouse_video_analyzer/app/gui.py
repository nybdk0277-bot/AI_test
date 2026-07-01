"""PySide6 desktop GUI for the mouse-pointer video analyzer."""
from __future__ import annotations

import os

import cv2
import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRect, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QImage, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSlider,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .analysis import (
    ClickEvent,
    compute_heatmap,
    compute_speeds,
    detect_clicks,
    export_clicks_csv,
    export_csv,
    render_trajectory_video,
)
from .tracker import CursorTracker, TrackPoint, VideoInfo


def bgr_to_qimage(frame: np.ndarray) -> QImage:
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    h, w, _ = rgb.shape
    return QImage(rgb.data, w, h, rgb.strides[0], QImage.Format.Format_RGB888).copy()


class FrameReader:
    """Sequential-friendly video frame reader (keeps one capture handle open)."""

    def __init__(self, path: str):
        self.cap = cv2.VideoCapture(path)
        self.pos = -1

    def get(self, idx: int):
        if idx != self.pos + 1:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = self.cap.read()
        self.pos = idx if ok else self.pos
        return frame if ok else None

    def release(self):
        self.cap.release()


class FrameView(QLabel):
    """Displays a video frame and lets the user drag out a rectangle (ROI)."""

    roi_selected = Signal(QRect)

    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(480, 320)
        self.setStyleSheet("background-color: #202020;")
        self.original_frame: np.ndarray | None = None
        self.scale = 1.0
        self.offset = QPoint(0, 0)
        self.pix_size = (0, 0)
        self.roi_enabled = False
        self.drag_start: QPoint | None = None
        self.drag_current: QPoint | None = None
        self.selected_rect: QRect | None = None

    def set_frame(self, frame_bgr: np.ndarray):
        self.original_frame = frame_bgr
        self.update()

    def set_roi_mode(self, enabled: bool):
        self.roi_enabled = enabled
        self.drag_start = None
        self.drag_current = None
        self.update()

    def _to_image_point(self, pos: QPoint) -> QPoint:
        if self.scale == 0:
            return QPoint(0, 0)
        ix = int((pos.x() - self.offset.x()) / self.scale)
        iy = int((pos.y() - self.offset.y()) / self.scale)
        h, w = self.original_frame.shape[:2]
        ix = max(0, min(w - 1, ix))
        iy = max(0, min(h - 1, iy))
        return QPoint(ix, iy)

    def mousePressEvent(self, event):
        if not self.roi_enabled or self.original_frame is None:
            return
        self.drag_start = self._to_image_point(event.position().toPoint())
        self.drag_current = self.drag_start

    def mouseMoveEvent(self, event):
        if not self.roi_enabled or self.drag_start is None:
            return
        self.drag_current = self._to_image_point(event.position().toPoint())
        self.update()

    def mouseReleaseEvent(self, event):
        if not self.roi_enabled or self.drag_start is None:
            return
        self.drag_current = self._to_image_point(event.position().toPoint())
        rect = QRect(self.drag_start, self.drag_current).normalized()
        self.drag_start = None
        if rect.width() > 2 and rect.height() > 2:
            self.selected_rect = rect
            self.roi_selected.emit(rect)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        if self.original_frame is None:
            super().paintEvent(event)
            return
        h, w = self.original_frame.shape[:2]
        qimg = bgr_to_qimage(self.original_frame)
        pix = QPixmap.fromImage(qimg)
        target = self.size()
        scaled = pix.scaled(target, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        self.scale = scaled.width() / w if w else 1.0
        self.pix_size = (scaled.width(), scaled.height())
        self.offset = QPoint((target.width() - scaled.width()) // 2,
                              (target.height() - scaled.height()) // 2)
        painter.drawPixmap(self.offset, scaled)

        def to_widget(p: QPoint) -> QPoint:
            return QPoint(int(p.x() * self.scale) + self.offset.x(),
                           int(p.y() * self.scale) + self.offset.y())

        if self.selected_rect is not None:
            painter.setPen(QPen(Qt.GlobalColor.green, 2))
            r = self.selected_rect
            painter.drawRect(QRect(to_widget(r.topLeft()), to_widget(r.bottomRight())))
        if self.drag_start is not None and self.drag_current is not None:
            painter.setPen(QPen(Qt.GlobalColor.yellow, 2, Qt.PenStyle.DashLine))
            r = QRect(self.drag_start, self.drag_current).normalized()
            painter.drawRect(QRect(to_widget(r.topLeft()), to_widget(r.bottomRight())))


class SpeedChart(QWidget):
    """Simple line chart of cursor speed over time, with click markers."""

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(180)
        self.speeds: list[float] = []
        self.clicks: list[ClickEvent] = []

    def set_data(self, speeds: list[float], clicks: list[ClickEvent]):
        self.speeds = speeds
        self.clicks = clicks
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), Qt.GlobalColor.white)
        if not self.speeds:
            return
        w, h = self.width(), self.height()
        max_speed = max(self.speeds) or 1.0
        n = len(self.speeds)

        painter.setPen(QPen(Qt.GlobalColor.magenta, 1))
        for e in self.clicks:
            x = int(e.frame_idx / max(1, n - 1) * w)
            painter.drawLine(x, 0, x, h)

        painter.setPen(QPen(Qt.GlobalColor.blue, 2))
        poly = QPolygonF()
        for i, s in enumerate(self.speeds):
            x = i / max(1, n - 1) * w
            y = h - (s / max_speed) * (h - 10) - 5
            poly.append(QPointF(x, y))
        painter.drawPolyline(poly)


class TrackWorker(QThread):
    progress = Signal(int, int)
    finished_ok = Signal(list)
    failed = Signal(str)

    def __init__(self, tracker: CursorTracker):
        super().__init__()
        self.tracker = tracker
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        try:
            points = self.tracker.track(
                progress_callback=lambda i, t: self.progress.emit(i, t),
                cancel_check=lambda: self._cancel,
            )
            self.finished_ok.emit(points)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class RenderWorker(QThread):
    progress = Signal(int, int)
    finished_ok = Signal(str)
    failed = Signal(str)

    def __init__(self, video, points, clicks, output_path):
        super().__init__()
        self.video = video
        self.points = points
        self.clicks = clicks
        self.output_path = output_path

    def run(self):
        try:
            render_trajectory_video(
                self.video, self.points, self.clicks, self.output_path,
                progress_callback=lambda i, t: self.progress.emit(i, t),
            )
            self.finished_ok.emit(self.output_path)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("マウス操作解析ツール")
        self.resize(1150, 780)

        self.video: VideoInfo | None = None
        self.tracker: CursorTracker | None = None
        self.reader: FrameReader | None = None
        self.points: list[TrackPoint] = []
        self.speeds: list[float] = []
        self.clicks: list[ClickEvent] = []
        self.heatmap_img: np.ndarray | None = None
        self.current_frame_idx = 0
        self.track_worker: TrackWorker | None = None
        self.render_worker: RenderWorker | None = None

        self.play_timer = QTimer(self)
        self.play_timer.timeout.connect(self._advance_frame)

        self._build_ui()
        self._build_menu()
        self._update_actions_enabled()

    # ---------------------------------------------------------------- UI --
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        toolbar = QHBoxLayout()
        self.btn_open = QPushButton("動画を開く")
        self.btn_open.clicked.connect(self.open_video)
        self.btn_select_roi = QPushButton("① カーソル範囲を選択")
        self.btn_select_roi.setCheckable(True)
        self.btn_select_roi.toggled.connect(self._on_roi_toggle)
        self.btn_track = QPushButton("② 解析開始")
        self.btn_track.clicked.connect(self.start_tracking)
        self.progress = QProgressBar()
        toolbar.addWidget(self.btn_open)
        toolbar.addWidget(self.btn_select_roi)
        toolbar.addWidget(self.btn_track)
        toolbar.addWidget(self.progress, stretch=1)
        root.addLayout(toolbar)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, stretch=1)

        # --- Preview tab ---
        preview_tab = QWidget()
        pv_layout = QVBoxLayout(preview_tab)
        self.frame_view = FrameView()
        self.frame_view.roi_selected.connect(self._on_roi_selected)
        pv_layout.addWidget(self.frame_view, stretch=1)

        scrub_row = QHBoxLayout()
        self.btn_play = QPushButton("再生")
        self.btn_play.clicked.connect(self._toggle_play)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.valueChanged.connect(self._on_slider_changed)
        self.lbl_time = QLabel("00:00 / 00:00")
        scrub_row.addWidget(self.btn_play)
        scrub_row.addWidget(self.slider, stretch=1)
        scrub_row.addWidget(self.lbl_time)
        pv_layout.addLayout(scrub_row)
        self.tabs.addTab(preview_tab, "プレビュー")

        # --- Heatmap tab ---
        heat_tab = QWidget()
        heat_layout = QVBoxLayout(heat_tab)
        self.heat_label = QLabel("解析後に表示されます")
        self.heat_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heat_layout.addWidget(self.heat_label, stretch=1)
        self.tabs.addTab(heat_tab, "ヒートマップ")

        # --- Stats tab ---
        stats_tab = QWidget()
        stats_layout = QVBoxLayout(stats_tab)
        stats_layout.addWidget(QLabel("速度の推移 (縦のピンク線はクリック/操作の候補)"))
        self.speed_chart = SpeedChart()
        stats_layout.addWidget(self.speed_chart)
        stats_layout.addWidget(QLabel("検出されたクリック/操作候補"))
        self.click_table = QTableWidget(0, 4)
        self.click_table.setHorizontalHeaderLabels(["フレーム", "時刻(秒)", "X", "Y"])
        stats_layout.addWidget(self.click_table, stretch=1)
        self.tabs.addTab(stats_tab, "統計")

    def _build_menu(self):
        menu = self.menuBar().addMenu("エクスポート")
        self.act_csv = QAction("軌跡データをCSV保存...", self)
        self.act_csv.triggered.connect(self.export_track_csv)
        self.act_click_csv = QAction("クリック一覧をCSV保存...", self)
        self.act_click_csv.triggered.connect(self.export_click_csv)
        self.act_heatmap = QAction("ヒートマップを画像保存...", self)
        self.act_heatmap.triggered.connect(self.export_heatmap)
        self.act_video = QAction("軌跡つき動画を書き出し...", self)
        self.act_video.triggered.connect(self.export_trajectory_video)
        for a in (self.act_csv, self.act_click_csv, self.act_heatmap, self.act_video):
            menu.addAction(a)

    def _update_actions_enabled(self):
        has_video = self.video is not None
        has_track = bool(self.points)
        self.btn_select_roi.setEnabled(has_video)
        self.btn_track.setEnabled(has_video and self.tracker is not None
                                   and self.tracker.template_gray is not None)
        self.slider.setEnabled(has_video)
        self.btn_play.setEnabled(has_video)
        for a in (self.act_csv, self.act_click_csv, self.act_heatmap, self.act_video):
            a.setEnabled(has_track)

    # ------------------------------------------------------------ Video --
    def open_video(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "動画を選択", "", "動画ファイル (*.mp4 *.avi *.mov *.mkv *.webm);;すべてのファイル (*)")
        if not path:
            return
        try:
            self.video = VideoInfo(path)
        except IOError as exc:
            QMessageBox.critical(self, "エラー", str(exc))
            return
        self.tracker = CursorTracker(self.video)
        self.points = []
        self.speeds = []
        self.clicks = []
        self.heatmap_img = None
        if self.reader:
            self.reader.release()
        self.reader = FrameReader(path)
        self.slider.setRange(0, max(0, self.video.frame_count - 1))
        self.slider.setValue(0)
        self.current_frame_idx = 0
        self._show_frame(0)
        self.heat_label.setText("解析後に表示されます")
        self.speed_chart.set_data([], [])
        self.click_table.setRowCount(0)
        self._update_actions_enabled()

    def _show_frame(self, idx: int):
        if self.reader is None:
            return
        frame = self.reader.get(idx)
        if frame is None:
            return
        frame = frame.copy()
        if self.points:
            trail = self.points[max(0, idx - 60):idx + 1]
            for j in range(1, len(trail)):
                p0, p1 = trail[j - 1], trail[j]
                cv2.line(frame, (int(p0.x), int(p0.y)), (int(p1.x), int(p1.y)), (0, 255, 255), 2)
            if idx < len(self.points):
                p = self.points[idx]
                cv2.circle(frame, (int(p.x), int(p.y)), 6, (0, 0, 255), -1)
        self.frame_view.set_frame(frame)
        total_s = (self.video.frame_count / self.video.fps) if self.video else 0
        cur_s = idx / self.video.fps if self.video else 0
        self.lbl_time.setText(f"{self._fmt_time(cur_s)} / {self._fmt_time(total_s)}")

    @staticmethod
    def _fmt_time(sec: float) -> str:
        m, s = divmod(int(sec), 60)
        return f"{m:02d}:{s:02d}"

    def _on_slider_changed(self, value: int):
        self.current_frame_idx = value
        self._show_frame(value)

    def _toggle_play(self):
        if self.play_timer.isActive():
            self.play_timer.stop()
            self.btn_play.setText("再生")
        else:
            interval = int(1000 / self.video.fps) if self.video else 33
            self.play_timer.start(max(15, interval))
            self.btn_play.setText("一時停止")

    def _advance_frame(self):
        if self.video is None:
            return
        idx = self.current_frame_idx + 1
        if idx >= self.video.frame_count:
            self.play_timer.stop()
            self.btn_play.setText("再生")
            return
        self.slider.setValue(idx)

    # --------------------------------------------------------- ROI/template
    def _on_roi_toggle(self, checked: bool):
        self.frame_view.set_roi_mode(checked)
        if checked:
            self.slider.setValue(0)
            self._show_frame(0)

    def _on_roi_selected(self, rect: QRect):
        if self.tracker is None or self.frame_view.original_frame is None:
            return
        bbox = (rect.x(), rect.y(), rect.width(), rect.height())
        try:
            self.tracker.set_template(self.frame_view.original_frame, bbox)
        except ValueError as exc:
            QMessageBox.warning(self, "選択エラー", str(exc))
            return
        self.btn_select_roi.setChecked(False)
        self._update_actions_enabled()

    # ------------------------------------------------------------ Track --
    def start_tracking(self):
        if self.tracker is None or self.tracker.template_gray is None:
            QMessageBox.information(self, "確認", "先にカーソル範囲を選択してください")
            return
        self.btn_track.setEnabled(False)
        self.progress.setValue(0)
        self.track_worker = TrackWorker(self.tracker)
        self.track_worker.progress.connect(self._on_track_progress)
        self.track_worker.finished_ok.connect(self._on_track_done)
        self.track_worker.failed.connect(self._on_track_failed)
        self.track_worker.start()

    def _on_track_progress(self, done: int, total: int):
        self.progress.setMaximum(total)
        self.progress.setValue(done)

    def _on_track_done(self, points: list[TrackPoint]):
        self.points = points
        self.speeds = compute_speeds(points)
        self.clicks = detect_clicks(points, self.speeds)
        self.heatmap_img = compute_heatmap(points, self.video.width, self.video.height)

        self.speed_chart.set_data(self.speeds, self.clicks)
        self.click_table.setRowCount(len(self.clicks))
        for row, e in enumerate(self.clicks):
            self.click_table.setItem(row, 0, QTableWidgetItem(str(e.frame_idx)))
            self.click_table.setItem(row, 1, QTableWidgetItem(f"{e.time_sec:.2f}"))
            self.click_table.setItem(row, 2, QTableWidgetItem(f"{e.x:.0f}"))
            self.click_table.setItem(row, 3, QTableWidgetItem(f"{e.y:.0f}"))

        qimg = bgr_to_qimage(self.heatmap_img)
        self.heat_label.setPixmap(QPixmap.fromImage(qimg).scaled(
            self.heat_label.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))

        self.btn_track.setEnabled(True)
        self._update_actions_enabled()
        self._show_frame(self.current_frame_idx)
        QMessageBox.information(self, "完了", f"解析が完了しました。クリック候補: {len(self.clicks)}件")

    def _on_track_failed(self, message: str):
        self.btn_track.setEnabled(True)
        QMessageBox.critical(self, "解析エラー", message)

    # ------------------------------------------------------------ Export --
    def export_track_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "軌跡CSVを保存", "trajectory.csv", "CSV (*.csv)")
        if path:
            export_csv(self.points, self.speeds, path)

    def export_click_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "クリックCSVを保存", "clicks.csv", "CSV (*.csv)")
        if path:
            export_clicks_csv(self.clicks, path)

    def export_heatmap(self):
        if self.heatmap_img is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "ヒートマップを保存", "heatmap.png", "PNG (*.png)")
        if path:
            cv2.imwrite(path, self.heatmap_img)

    def export_trajectory_video(self):
        path, _ = QFileDialog.getSaveFileName(self, "軌跡つき動画を保存", "trajectory.mp4", "MP4 (*.mp4)")
        if not path:
            return
        self.progress.setValue(0)
        self.render_worker = RenderWorker(self.video, self.points, self.clicks, path)
        self.render_worker.progress.connect(self._on_track_progress)
        self.render_worker.finished_ok.connect(
            lambda p: QMessageBox.information(self, "完了", f"書き出しました: {p}"))
        self.render_worker.failed.connect(lambda m: QMessageBox.critical(self, "エラー", m))
        self.render_worker.start()

    def closeEvent(self, event):
        if self.reader:
            self.reader.release()
        super().closeEvent(event)
