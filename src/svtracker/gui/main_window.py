"""svtrackerのデスクトップGUI(Tkinter)。

シェル操作なしで「カードDB準備 → キャリブレーション → 監視 → 統計確認」ができるように、
CLI(svtracker.cli)が持つ機能をタブ形式で提供する。CLIとロジックは共通で、
svtracker.app.MonitorApp / svtracker.cards.card_fetcher などをそのまま呼ぶだけ。
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Optional

from svtracker.capture.screen_capture import POINT_REGIONS, RECT_LIST_REGIONS, RECT_SINGLE_REGIONS, RegionSet
from svtracker.cards.card_database import CardDatabase
from svtracker.config import Settings
from svtracker.game.models import GameFormat
from svtracker.gui.log_handler import QueueLogHandler
from svtracker.gui.region_canvas import RegionCanvas
from svtracker.storage.match_log import MatchLog
from svtracker.version import full_version

logger = logging.getLogger(__name__)

REGION_LABELS = {
    "self_hand": "自分の手札",
    "self_board": "自分の盤面",
    "opponent_board": "相手の盤面",
    "turn_indicator": "ターン表示",
    "self_pp": "自分のPP表示",
    "self_life": "自分のライフ表示",
    "opponent_life": "相手のライフ表示",
    "self_extra_pp": "自分のエクストラPP表示",
    "self_ep": "自分の進化ポイント表示(黄色)",
    "opponent_ep": "相手の進化ポイント表示(黄色)",
    "self_sep": "自分の超進化ポイント表示(紫)",
    "opponent_sep": "相手の超進化ポイント表示(紫)",
    "combo_count": "コンボ数(任意)",
    "self_hand_count": "自分の手札枚数(任意)",
    "opponent_hand_count": "相手の手札枚数(任意)",
    "self_deck_count": "自分のデッキ残り枚数(任意)",
    "opponent_deck_count": "相手のデッキ残り枚数(任意)",
    "self_cemetery_count": "自分の墓場枚数(任意)",
    "opponent_cemetery_count": "相手の墓場枚数(任意)",
    "active_player_pixel": "手番判定ピクセル",
}
REGION_COLORS = {
    "self_hand": "#33ccff",
    "self_board": "#33ff77",
    "opponent_board": "#ff5566",
    "turn_indicator": "#ffcc33",
    "self_pp": "#33ccff",
    "self_life": "#33ff77",
    "opponent_life": "#ff5566",
    "self_extra_pp": "#33aaff",
    "self_ep": "#ffdd55",
    "opponent_ep": "#ffaa33",
    "self_sep": "#aa66ff",
    "opponent_sep": "#dd66ff",
    "combo_count": "#66ddaa",
    "self_hand_count": "#88ccff",
    "opponent_hand_count": "#ff8888",
    "self_deck_count": "#88ccff",
    "opponent_deck_count": "#ff8888",
    "self_cemetery_count": "#cccccc",
    "opponent_cemetery_count": "#cccccc",
}
REGION_ORDER = RECT_LIST_REGIONS + RECT_SINGLE_REGIONS + POINT_REGIONS
DEFAULT_SLOT_COUNT = {"self_hand": 9, "self_board": 7, "opponent_board": 7}
GAME_FORMAT_LABELS = {"unlimited": "アンリミテッド", "rotation": "ローテーション"}
GAME_FORMAT_VALUES = {label: value for value, label in GAME_FORMAT_LABELS.items()}


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"svtracker {full_version()} - シャドウバース ワールズビヨンド 監視ツール")
        self.geometry("1150x780")
        self.minsize(900, 600)

        logger.info("svtracker %s", full_version())
        self.settings = Settings.load()
        self.settings.ensure_dirs()
        self.regions = (
            RegionSet.load(self.settings.regions_path) if self.settings.regions_path.exists() else RegionSet()
        )

        self.log_handler = QueueLogHandler()
        logging.getLogger().addHandler(self.log_handler)
        logging.getLogger().setLevel(logging.INFO)

        self.monitor_app = None
        self.monitor_thread: Optional[threading.Thread] = None
        self.monitor_stop_event = threading.Event()

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True)

        self.card_db_tab = CardDbTab(notebook, self)
        self.calibration_tab = CalibrationTab(notebook, self)
        self.monitor_tab = MonitorTab(notebook, self)
        self.stats_tab = StatsTab(notebook, self)

        notebook.add(self.card_db_tab, text="カードDB")
        notebook.add(self.calibration_tab, text="キャリブレーション")
        notebook.add(self.monitor_tab, text="監視")
        notebook.add(self.stats_tab, text="統計")

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(200, self._poll_log_queue)

    def run_in_background(self, fn: Callable, on_done: Optional[Callable] = None, on_error: Optional[Callable] = None) -> None:
        """GUIを固まらせないよう、fnを別スレッドで実行し、結果をメインスレッドへ戻す."""

        def worker():
            try:
                result = fn()
            except Exception as exc:  # noqa: BLE001 - GUIなのでエラーはダイアログで見せる
                logger.exception("バックグラウンド処理でエラーが発生しました")
                if on_error:
                    self.after(0, lambda: on_error(exc))
                else:
                    self.after(0, lambda: messagebox.showerror("エラー", str(exc)))
                return
            if on_done:
                self.after(0, lambda: on_done(result))

        threading.Thread(target=worker, daemon=True).start()

    def _poll_log_queue(self) -> None:
        lines = self.log_handler.drain()
        if lines:
            self.monitor_tab.append_log(lines)
        self.after(200, self._poll_log_queue)

    def _on_close(self) -> None:
        self.monitor_tab.stop_monitoring()
        self.destroy()


class CardDbTab(ttk.Frame):
    def __init__(self, parent, app: App):
        super().__init__(parent, padding=16)
        self.app = app

        self.count_var = tk.StringVar()
        ttk.Label(self, textvariable=self.count_var, font=("", 11, "bold")).pack(anchor="w", pady=(0, 4))

        # exe版はProgram Filesではなく%APPDATA%配下に保存されるため、保存先を明示して
        # 「インストール先のdataフォルダが空」という誤認を防ぐ。
        path_row = ttk.Frame(self)
        path_row.pack(fill="x", pady=(0, 12))
        ttk.Label(
            path_row,
            text=f"保存先: {self.app.settings.cards_dir}",
            foreground="#888",
        ).pack(side="left")
        ttk.Button(path_row, text="フォルダを開く", command=self._open_cards_dir).pack(side="left", padx=8)

        self.merge_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            self,
            text="既存のカードDBに追加する(上書きしない)",
            variable=self.merge_var,
        ).pack(anchor="w")
        ttk.Label(
            self,
            text=(
                "公式サイトのカード一覧にはトークンカード(効果で生成されるカード)が"
                "含まれないため、下の「ローカルから取り込み」でトークン用の画像+CSVを"
                "別途用意し、このチェックをONにして取り込むと公式データを消さずに追加できます。"
            ),
            foreground="#888",
            wraplength=500,
        ).pack(anchor="w", pady=(0, 12))

        ttk.Button(self, text="公式サイトから取得", command=self._fetch).pack(anchor="w", pady=4)
        ttk.Label(
            self,
            text="サイト構造の変化でうまく取得できない場合は、下の「ローカルから取り込み」をお使いください。",
            foreground="#888",
            wraplength=500,
        ).pack(anchor="w", pady=(0, 12))

        ttk.Button(self, text="ローカルの画像+CSVから取り込み", command=self._import).pack(anchor="w", pady=4)
        ttk.Label(
            self,
            text="CSVヘッダ: card_id,name,clan,cost,card_type,rarity,filename[,base_atk,base_hp,card_set_id]",
            foreground="#888",
        ).pack(anchor="w")

        self.status_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.status_var, foreground="#0a6").pack(anchor="w", pady=(16, 0))

        self._refresh_count()

    def _refresh_count(self) -> None:
        db = CardDatabase.load(self.app.settings.card_db_path)
        self.count_var.set(f"現在のカードDB: {len(db)} 枚")

    def _open_cards_dir(self) -> None:
        path = self.app.settings.cards_dir
        path.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform == "win32":
                os.startfile(str(path))  # noqa: S606 - 固定のローカルフォルダをExplorerで開くだけ
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception:  # noqa: BLE001
            logger.exception("フォルダを開けませんでした")
            messagebox.showerror("エラー", f"フォルダを開けませんでした:\n{path}")

    def _fetch(self) -> None:
        self.status_var.set("公式サイトから取得中...(数分かかる場合があります)")

        merge = self.merge_var.get()

        def work():
            from svtracker.cards.card_fetcher import fetch_from_official_site

            db = fetch_from_official_site(
                base_url=self.app.settings.official_site_base,
                images_dir=self.app.settings.cards_dir,
                hash_size=self.app.settings.hash_size,
            )
            if merge and self.app.settings.card_db_path.exists():
                existing = CardDatabase.load(self.app.settings.card_db_path)
                existing.merge(db)
                db = existing
            db.save(self.app.settings.card_db_path)
            return len(db)

        def done(count):
            self.status_var.set(f"{count} 枚取得しました。")
            self._refresh_count()

        def error(exc):
            self.status_var.set("取得に失敗しました。")
            messagebox.showerror(
                "カード取得エラー",
                f"{exc}\n\nサイト構造が変わっている可能性があります。ローカル取り込みをお試しください。",
            )

        self.app.run_in_background(work, on_done=done, on_error=error)

    def _import(self) -> None:
        images_dir = filedialog.askdirectory(title="カード画像フォルダを選択")
        if not images_dir:
            return
        csv_path = filedialog.askopenfilename(title="メタ情報CSVを選択", filetypes=[("CSV", "*.csv")])
        if not csv_path:
            return
        self.status_var.set("取り込み中...")
        merge = self.merge_var.get()

        def work():
            from svtracker.cards.card_fetcher import import_from_local

            db = import_from_local(Path(images_dir), Path(csv_path), hash_size=self.app.settings.hash_size)
            if merge and self.app.settings.card_db_path.exists():
                existing = CardDatabase.load(self.app.settings.card_db_path)
                existing.merge(db)
                db = existing
            db.save(self.app.settings.card_db_path)
            return len(db)

        def done(count):
            self.status_var.set(f"{count} 枚取り込みました。")
            self._refresh_count()

        def error(exc):
            self.status_var.set("取り込みに失敗しました。")
            messagebox.showerror("取り込みエラー", str(exc))

        self.app.run_in_background(work, on_done=done, on_error=error)


class CalibrationTab(ttk.Frame):
    def __init__(self, parent, app: App):
        super().__init__(parent, padding=8)
        self.app = app
        self._captured_image = None
        self._pending_color_target: Optional[str] = None
        self.current_region = REGION_ORDER[0]

        left = ttk.Frame(self)
        left.pack(side="left", fill="both", expand=True)
        right = ttk.Frame(self, padding=(12, 0, 0, 0))
        right.pack(side="right", fill="y")

        self.canvas_widget = RegionCanvas(left)
        self.canvas_widget.pack(fill="both", expand=True)
        self.canvas_widget.on_rect_drawn = self._on_rect_drawn
        self.canvas_widget.on_point_picked = self._on_point_picked

        ttk.Label(right, text="キャプチャするモニタ", font=("", 10, "bold")).pack(anchor="w")
        self.monitor_var = tk.StringVar()
        self._monitor_options = self._load_monitor_options()
        if self._monitor_options:
            self.monitor_combo = ttk.Combobox(
                right,
                textvariable=self.monitor_var,
                state="readonly",
                values=[self._monitor_label(m) for m in self._monitor_options],
                width=28,
            )
            current_pos = next(
                (i for i, m in enumerate(self._monitor_options) if m.index == app.settings.monitor_index), 0
            )
            self.monitor_combo.current(current_pos)
            self.monitor_combo.pack(fill="x", pady=(0, 4))
            self.monitor_combo.bind("<<ComboboxSelected>>", self._on_monitor_selected)
        else:
            ttk.Label(
                right,
                text="モニタ一覧を取得できませんでした。番号を直接入力してください。",
                foreground="#888",
                wraplength=230,
            ).pack(anchor="w")
            self.monitor_var.set(str(app.settings.monitor_index))
            monitor_entry = ttk.Entry(right, textvariable=self.monitor_var, width=6)
            monitor_entry.pack(anchor="w", pady=(0, 4))
            monitor_entry.bind("<FocusOut>", self._on_monitor_entry_changed)
            monitor_entry.bind("<Return>", self._on_monitor_entry_changed)

        ttk.Button(right, text="スクリーンショットを撮る", command=self._capture).pack(fill="x", pady=4)

        ttk.Label(right, text="編集する領域", font=("", 10, "bold")).pack(anchor="w", pady=(12, 0))
        self.region_var = tk.StringVar(value=REGION_LABELS.get(self.current_region, self.current_region))
        region_box = ttk.Combobox(
            right,
            textvariable=self.region_var,
            state="readonly",
            values=[REGION_LABELS.get(n, n) for n in REGION_ORDER],
            width=24,
        )
        region_box.current(0)
        region_box.pack(fill="x")
        region_box.bind("<<ComboboxSelected>>", lambda e: self._on_region_changed(region_box.current()))

        self.hint_var = tk.StringVar()
        ttk.Label(right, textvariable=self.hint_var, wraplength=230, foreground="#888").pack(anchor="w", pady=(6, 0))

        self.slot_count_var = tk.StringVar()
        ttk.Label(right, textvariable=self.slot_count_var).pack(anchor="w", pady=(6, 0))
        ttk.Button(right, text="最後のスロットを削除", command=self._remove_last_slot).pack(fill="x", pady=2)
        ttk.Button(right, text="この領域をクリア", command=self._clear_region).pack(fill="x", pady=2)

        ttk.Separator(right).pack(fill="x", pady=6)
        ttk.Label(right, text="等間隔の自動補完(複数枠の領域のみ)", font=("", 10, "bold")).pack(anchor="w")
        ttk.Label(
            right,
            text="先頭2〜3枚をドラッグしたあと枚数を指定して押すと、間隔を推定して残りを自動生成します。",
            wraplength=230,
            foreground="#888",
        ).pack(anchor="w")
        count_row = ttk.Frame(right)
        count_row.pack(fill="x", pady=2)
        ttk.Label(count_row, text="枚数:").pack(side="left")
        self.auto_fill_count_var = tk.StringVar(value=str(DEFAULT_SLOT_COUNT.get(self.current_region, 9)))
        ttk.Entry(count_row, textvariable=self.auto_fill_count_var, width=6).pack(side="left", padx=4)
        ttk.Button(right, text="等間隔で自動補完", command=self._auto_fill_row).pack(fill="x", pady=2)

        ttk.Separator(right).pack(fill="x", pady=10)
        ttk.Label(right, text="手番判定の基準色", font=("", 10, "bold")).pack(anchor="w")
        ttk.Label(
            right,
            text="スクリーンショット上で、自分/相手それぞれの手番のときに色が変わるUI部分をクリックして登録します。",
            wraplength=230,
            foreground="#888",
        ).pack(anchor="w")
        ttk.Button(right, text="この位置を自分の手番色として登録", command=lambda: self._arm_color_pick("self")).pack(
            fill="x", pady=2
        )
        ttk.Button(
            right, text="この位置を相手の手番色として登録", command=lambda: self._arm_color_pick("opponent")
        ).pack(fill="x", pady=2)
        self.self_color_swatch = tk.Label(right, text="自分の手番色", bg=self._rgb_to_hex(app.settings.self_turn_color))
        self.self_color_swatch.pack(fill="x", pady=2)
        self.opponent_color_swatch = tk.Label(
            right, text="相手の手番色", bg=self._rgb_to_hex(app.settings.opponent_turn_color)
        )
        self.opponent_color_swatch.pack(fill="x", pady=2)

        ttk.Separator(right).pack(fill="x", pady=10)
        ttk.Button(right, text="regions.json / settings.json に保存", command=self._save_all).pack(fill="x", pady=4)

        self._apply_mode_for_region(self.current_region)
        self._update_slot_count()
        self._refresh_overlays()

    @staticmethod
    def _rgb_to_hex(rgb) -> str:
        r, g, b = rgb
        return f"#{r:02x}{g:02x}{b:02x}"

    @staticmethod
    def _load_monitor_options():
        try:
            from svtracker.capture.screen_capture import list_monitors

            return list_monitors()
        except Exception:  # noqa: BLE001 - モニタ列挙に失敗しても手入力にフォールバックする
            logger.exception("モニタ一覧の取得に失敗しました")
            return None

    @staticmethod
    def _monitor_label(monitor) -> str:
        if monitor.is_virtual_combined:
            return f"{monitor.index}: 全モニタ結合 ({monitor.width}x{monitor.height})"
        return f"{monitor.index}: モニタ{monitor.index} ({monitor.width}x{monitor.height}, 位置 {monitor.left},{monitor.top})"

    def _on_monitor_selected(self, _event) -> None:
        monitor = self._monitor_options[self.monitor_combo.current()]
        self.app.settings.monitor_index = monitor.index
        self.app.settings.save()

    def _on_monitor_entry_changed(self, _event) -> None:
        try:
            monitor_index = int(self.monitor_var.get())
        except ValueError:
            return
        self.app.settings.monitor_index = monitor_index
        self.app.settings.save()

    def _apply_mode_for_region(self, name: str) -> None:
        if name in POINT_REGIONS:
            self.canvas_widget.set_mode("point")
            self.hint_var.set("キャンバス上をクリックして座標を指定します。")
        elif name in RECT_LIST_REGIONS:
            self.canvas_widget.set_mode("rect")
            self.hint_var.set("ドラッグして矩形を追加していきます(複数枠)。")
        else:
            self.canvas_widget.set_mode("rect")
            self.hint_var.set("ドラッグして矩形を指定します(1つだけ)。")

    def _capture(self) -> None:
        def work():
            from svtracker.capture.screen_capture import ScreenCapture

            capture = ScreenCapture(monitor_index=self.app.settings.monitor_index, window_title_hint=None)
            try:
                return capture.grab()
            finally:
                capture.close()

        def done(image):
            self._captured_image = image
            self.canvas_widget.set_image(image)
            self._refresh_overlays()

        self.app.run_in_background(work, on_done=done)

    def _on_region_changed(self, index: int) -> None:
        self.current_region = REGION_ORDER[index]
        self._apply_mode_for_region(self.current_region)
        self._update_slot_count()
        self.auto_fill_count_var.set(str(DEFAULT_SLOT_COUNT.get(self.current_region, 9)))

    def _auto_fill_row(self) -> None:
        name = self.current_region
        if name not in RECT_LIST_REGIONS:
            messagebox.showinfo("対象外", "自動補完は手札・盤面など複数枠の領域でのみ使えます。")
            return
        try:
            count = int(self.auto_fill_count_var.get())
        except ValueError:
            messagebox.showwarning("入力エラー", "枚数は整数で指定してください。")
            return

        existing = self.app.regions.slots(name)
        if len(existing) < 2:
            messagebox.showwarning(
                "サンプル不足", "先に先頭2枚以上をドラッグして矩形を指定してから自動補完してください。"
            )
            return

        from svtracker.capture.auto_layout import interpolate_row

        try:
            generated = interpolate_row(existing, count)
        except ValueError as exc:
            messagebox.showwarning("入力エラー", str(exc))
            return

        self.app.regions.set_slots(name, generated)
        self._update_slot_count()
        self._refresh_overlays()

    def _update_slot_count(self) -> None:
        name = self.current_region
        if name in RECT_LIST_REGIONS:
            self.slot_count_var.set(f"現在 {len(self.app.regions.slots(name))} 枠")
        elif name in RECT_SINGLE_REGIONS:
            self.slot_count_var.set("設定済み" if self.app.regions.single(name) else "未設定")
        else:
            self.slot_count_var.set("設定済み" if self.app.regions.point(name) else "未設定")

    def _on_rect_drawn(self, x: int, y: int, w: int, h: int) -> None:
        name = self.current_region
        if name in RECT_LIST_REGIONS:
            self.app.regions.add_slot(name, (x, y, w, h))
        elif name in RECT_SINGLE_REGIONS:
            self.app.regions.set_single(name, (x, y, w, h))
        else:
            return
        self._update_slot_count()
        self._refresh_overlays()

    def _on_point_picked(self, x: int, y: int) -> None:
        if self._pending_color_target is not None:
            self._pick_color_at(x, y)
            return
        name = self.current_region
        if name in POINT_REGIONS:
            self.app.regions.set_point(name, (x, y))
            self._update_slot_count()
            self._refresh_overlays()

    def _pick_color_at(self, x: int, y: int) -> None:
        target = self._pending_color_target
        self._pending_color_target = None
        self._apply_mode_for_region(self.current_region)
        if self._captured_image is None:
            messagebox.showwarning("未撮影", "先にスクリーンショットを撮ってください。")
            return
        color = self._captured_image.convert("RGB").getpixel((x, y))
        if target == "self":
            self.app.settings.self_turn_color = color
            self.self_color_swatch.config(bg=self._rgb_to_hex(color))
        else:
            self.app.settings.opponent_turn_color = color
            self.opponent_color_swatch.config(bg=self._rgb_to_hex(color))

    def _arm_color_pick(self, target: str) -> None:
        if self._captured_image is None:
            messagebox.showwarning("未撮影", "先にスクリーンショットを撮ってください。")
            return
        self._pending_color_target = target
        self.canvas_widget.set_mode("point")
        self.hint_var.set("キャンバス上で手番表示部分をクリックしてください。")

    def _remove_last_slot(self) -> None:
        name = self.current_region
        if name in RECT_LIST_REGIONS:
            self.app.regions.remove_last_slot(name)
        else:
            self.app.regions.clear(name)
        self._update_slot_count()
        self._refresh_overlays()

    def _clear_region(self) -> None:
        self.app.regions.clear(self.current_region)
        self._update_slot_count()
        self._refresh_overlays()

    def _refresh_overlays(self) -> None:
        rects = []
        for name in RECT_LIST_REGIONS:
            color = REGION_COLORS.get(name, "#ffffff")
            for i, rect in enumerate(self.app.regions.slots(name)):
                rects.append((*rect, f"{REGION_LABELS.get(name, name)}{i + 1}", color))
        for name in RECT_SINGLE_REGIONS:
            rect = self.app.regions.single(name)
            if rect:
                rects.append((*rect, REGION_LABELS.get(name, name), REGION_COLORS.get(name, "#ffffff")))
        points = []
        for name in POINT_REGIONS:
            pt = self.app.regions.point(name)
            if pt:
                points.append((*pt, REGION_LABELS.get(name, name), "#ff33ff"))
        self.canvas_widget.set_overlays(rects, points)

    def _save_all(self) -> None:
        self.app.regions.save(self.app.settings.regions_path)
        self.app.settings.save()
        messagebox.showinfo("保存しました", "regions.json / settings.json を保存しました。")


class MonitorTab(ttk.Frame):
    def __init__(self, parent, app: App):
        super().__init__(parent, padding=8)
        self.app = app
        self._pending_result = "unknown"

        form = ttk.Frame(self)
        form.pack(fill="x")
        ttk.Label(form, text="自分のクラス(空欄で自動判別):").grid(row=0, column=0, sticky="w")
        self.self_clan_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.self_clan_var, width=16).grid(row=0, column=1, padx=4)
        ttk.Label(form, text="相手のクラス(空欄で自動判別):").grid(row=0, column=2, sticky="w", padx=(12, 0))
        self.opponent_clan_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.opponent_clan_var, width=16).grid(row=0, column=3, padx=4)

        self.start_button = ttk.Button(form, text="開始", command=self._start)
        self.start_button.grid(row=0, column=4, padx=(12, 4))
        self.stop_button = ttk.Button(form, text="停止", command=self._stop, state="disabled")
        self.stop_button.grid(row=0, column=5)

        ttk.Label(form, text="対戦形式:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        self.format_var = tk.StringVar()
        self.format_combo = ttk.Combobox(
            form,
            textvariable=self.format_var,
            state="readonly",
            values=list(GAME_FORMAT_LABELS.values()),
            width=14,
        )
        initial_format = GAME_FORMAT_LABELS.get(app.settings.game_format, GAME_FORMAT_LABELS["unlimited"])
        self.format_combo.set(initial_format)
        self.format_combo.grid(row=1, column=1, padx=4, pady=(6, 0), sticky="w")
        self.format_combo.bind("<<ComboboxSelected>>", self._on_format_selected)

        self.status_var = tk.StringVar(value="停止中")
        ttk.Label(self, textvariable=self.status_var, foreground="#666").pack(anchor="w", pady=(6, 0))
        self.clan_status_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.clan_status_var, foreground="#666").pack(anchor="w")
        self.count_status_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.count_status_var, foreground="#666").pack(anchor="w")
        self.after(500, self._poll_clan_status)

        self.log_text = tk.Text(self, height=30, state="disabled", bg="#111111", fg="#dddddd", wrap="word")
        self.log_text.pack(fill="both", expand=True, pady=(8, 0))

    def _poll_clan_status(self) -> None:
        monitor_app = self.app.monitor_app
        if monitor_app is not None:
            state = monitor_app.tracker.state
            self_clan = state.self_clan or "判別中..."
            opponent_clan = state.opponent_clan or "判別中..."
            self.clan_status_var.set(f"検出中のクラス: 自分={self_clan} / 相手={opponent_clan}")
            self.count_status_var.set(self._format_counts(state))
        else:
            self.clan_status_var.set("")
            self.count_status_var.set("")
        self.after(500, self._poll_clan_status)

    @staticmethod
    def _format_counts(state) -> str:
        """バトルログ用カウンタ(領域を設定したものだけ)を1行にまとめる."""
        parts = []
        if state.combo_count is not None:
            parts.append(f"コンボ{state.combo_count}")
        if state.self_hand_count is not None or state.opponent_hand_count is not None:
            parts.append(f"手札 自{state.self_hand_count}/相{state.opponent_hand_count}")
        if state.self_deck_count is not None or state.opponent_deck_count is not None:
            parts.append(f"デッキ 自{state.self_deck_count}/相{state.opponent_deck_count}")
        if state.self_cemetery_count is not None or state.opponent_cemetery_count is not None:
            parts.append(f"墓場 自{state.self_cemetery_count}/相{state.opponent_cemetery_count}")
        return "  ".join(parts)

    def _on_format_selected(self, _event) -> None:
        self.app.settings.game_format = GAME_FORMAT_VALUES.get(self.format_var.get(), "unlimited")
        self.app.settings.save()

    def append_log(self, lines: list[str]) -> None:
        self.log_text.config(state="normal")
        for line in lines:
            self.log_text.insert("end", line + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _start(self) -> None:
        if self.app.monitor_thread is not None and self.app.monitor_thread.is_alive():
            return
        if not self.app.settings.regions_path.exists():
            messagebox.showwarning("未設定", "先にキャリブレーションタブで regions.json を保存してください。")
            return

        self_clan = self.self_clan_var.get()
        opponent_clan = self.opponent_clan_var.get()
        game_format = GameFormat(GAME_FORMAT_VALUES.get(self.format_var.get(), "unlimited"))
        self._pending_result = "unknown"
        self.app.monitor_stop_event.clear()
        self.status_var.set("開始中...")
        self.start_button.config(state="disabled")

        def loop():
            from svtracker.app import MonitorApp

            try:
                monitor_app = MonitorApp(
                    self.app.settings, self_clan=self_clan, opponent_clan=opponent_clan, game_format=game_format
                )
            except Exception as exc:  # noqa: BLE001
                logger.exception("監視の開始に失敗しました")
                self.app.after(0, lambda: self._on_start_failed(exc))
                return

            self.app.monitor_app = monitor_app
            self.app.after(0, self._on_started)
            interval = self.app.settings.capture_interval_sec
            while not self.app.monitor_stop_event.is_set():
                try:
                    monitor_app.step()
                except Exception:  # noqa: BLE001
                    logger.exception("監視ループでエラーが発生しました")
                self.app.monitor_stop_event.wait(interval)
            try:
                monitor_app.end_match(self._pending_result)
                monitor_app.close()
            except Exception:  # noqa: BLE001
                logger.exception("監視の終了処理でエラーが発生しました")
            self.app.monitor_app = None

        self.app.monitor_thread = threading.Thread(target=loop, daemon=True)
        self.app.monitor_thread.start()

    def _on_started(self) -> None:
        self.status_var.set("監視中")
        self.stop_button.config(state="normal")

    def _on_start_failed(self, exc: Exception) -> None:
        self.status_var.set("停止中")
        self.start_button.config(state="normal")
        messagebox.showerror("開始できません", str(exc))

    def _stop(self) -> None:
        self._pending_result = self._ask_match_result()
        self.stop_button.config(state="disabled")
        self.app.run_in_background(self.stop_monitoring, on_done=lambda _: self._on_stopped())

    def _ask_match_result(self) -> str:
        """対戦結果を確認するモーダルダイアログ(メインスレッドから同期的に呼ぶこと)。"""
        dialog = tk.Toplevel(self)
        dialog.title("対戦結果")
        dialog.transient(self)
        dialog.resizable(False, False)
        ttk.Label(dialog, text="この対戦の結果を記録しますか?", padding=(16, 16, 16, 8)).pack()

        chosen = {"value": "unknown"}

        def choose(value: str) -> None:
            chosen["value"] = value
            dialog.destroy()

        btn_row = ttk.Frame(dialog)
        btn_row.pack(pady=(0, 16))
        ttk.Button(btn_row, text="勝ち", command=lambda: choose("win")).pack(side="left", padx=6)
        ttk.Button(btn_row, text="負け", command=lambda: choose("loss")).pack(side="left", padx=6)
        ttk.Button(btn_row, text="記録しない", command=lambda: choose("unknown")).pack(side="left", padx=6)
        dialog.protocol("WM_DELETE_WINDOW", lambda: choose("unknown"))
        dialog.grab_set()
        self.wait_window(dialog)
        return chosen["value"]

    def _on_stopped(self) -> None:
        self.status_var.set("停止中")
        self.start_button.config(state="normal")

    def stop_monitoring(self) -> None:
        """スレッドセーフな停止処理のみ(Tkinterウィジェットは触らない)。
        ウィンドウを閉じる際にもメインスレッドから直接呼ばれる。"""
        if self.app.monitor_thread is None:
            return
        self.app.monitor_stop_event.set()
        self.app.monitor_thread.join(timeout=10)
        self.app.monitor_thread = None


class StatsTab(ttk.Frame):
    def __init__(self, parent, app: App):
        super().__init__(parent, padding=8)
        self.app = app

        form = ttk.Frame(self)
        form.pack(fill="x")
        ttk.Label(form, text="相手クラス:").pack(side="left")
        self.clan_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.clan_var, width=16).pack(side="left", padx=4)
        ttk.Button(form, text="表示", command=self._refresh).pack(side="left")

        self.win_rate_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.win_rate_var, font=("", 10, "bold")).pack(anchor="w", pady=(8, 0))

        columns = ("name", "count")
        self.tree = ttk.Treeview(self, columns=columns, show="headings")
        self.tree.heading("name", text="カード名")
        self.tree.heading("count", text="使用された試合数")
        self.tree.pack(fill="both", expand=True, pady=(8, 0))

    def _refresh(self) -> None:
        clan = self.clan_var.get()
        if not clan:
            return
        if not self.app.settings.match_db_path.exists():
            messagebox.showinfo("記録なし", "対戦記録がまだありません。")
            return
        for row in self.tree.get_children():
            self.tree.delete(row)

        log = MatchLog(self.app.settings.match_db_path)
        try:
            win_stats = log.match_results(opponent_clan=clan)
            pool = log.opponent_card_pool(clan)
        finally:
            log.close()

        if win_stats.total > 0:
            self.win_rate_var.set(
                f"戦績: {win_stats.wins}勝{win_stats.losses}敗 (勝率{win_stats.win_rate:.0%}、{win_stats.total}戦)"
            )
        else:
            self.win_rate_var.set("戦績: 記録なし")

        if not pool:
            messagebox.showinfo("記録なし", f"クラス '{clan}' の対戦記録が見つかりませんでした。")
            return

        db = CardDatabase.load(self.app.settings.card_db_path)
        for card_id, count in pool:
            card = db.get(card_id)
            name = card.name if card else card_id
            self.tree.insert("", "end", values=(name, count))


def main() -> int:
    app = App()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
