"""SVWBのゲームウィンドウの位置・サイズを取得する（Windows想定・ベストエフォート）.

Steam版は基本的にWindows上で動くため pygetwindow を優先的に使う。
取得できない環境（Linux/Mac、または pygetwindow 未インストール）では
None を返すので、呼び出し側は config の固定モニタキャプチャにフォールバックする。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class WindowRect:
    left: int
    top: int
    width: int
    height: int


def find_game_window(title_hint: str = "Shadowverse") -> Optional[WindowRect]:
    try:
        import pygetwindow as gw
    except ImportError:
        logger.debug("pygetwindow not installed; skipping window auto-detect")
        return None

    matches = [w for w in gw.getAllWindows() if title_hint.lower() in w.title.lower()]
    if not matches:
        logger.debug("no window matching title hint %r found", title_hint)
        return None

    window = matches[0]
    return WindowRect(left=window.left, top=window.top, width=window.width, height=window.height)
