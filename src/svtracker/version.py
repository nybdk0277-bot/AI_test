"""アプリのバージョン情報.

ベースバージョンは svtracker.__version__ (pyproject.toml と手動で同期)。
CIビルドでは packaging/write_build_info.py が svtracker/_build_info.py
(コミットSHA・ビルド日時)を生成してからexe化するため、配布物では
「どのコミットのビルドか」まで表示できる。開発環境(リポジトリから直接実行)では
_build_info.py が無いので「開発版」と表示する。
"""
from __future__ import annotations

from svtracker import __version__


def full_version() -> str:
    try:
        from svtracker import _build_info  # type: ignore[attr-defined]
    except ImportError:
        return f"{__version__} (開発版)"
    return f"{__version__} (build {_build_info.GIT_SHA[:7]}, {_build_info.BUILD_DATE})"
