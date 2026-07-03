"""バックグラウンドスレッドで動くlogging出力を、Tkinterのメインスレッドへ安全に橋渡しする.

Tkinterのウィジェットはメインスレッド以外から直接触ってはいけないため、
監視ループ(別スレッド)からのログはいったんqueue.Queueに貯め、
GUI側は Tk.after() の定期ポーリングで取り出して表示する。
"""
from __future__ import annotations

import logging
import queue


class QueueLogHandler(logging.Handler):
    def __init__(self, level: int = logging.INFO):
        super().__init__(level=level)
        self.queue: queue.Queue[str] = queue.Queue()
        self.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.queue.put_nowait(self.format(record))
        except Exception:
            pass

    def drain(self) -> list[str]:
        """溜まっているログ行を全て取り出す(GUIのポーリングから呼ぶ)."""
        lines = []
        while True:
            try:
                lines.append(self.queue.get_nowait())
            except queue.Empty:
                break
        return lines
