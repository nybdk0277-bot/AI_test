"""アプリ全体の設定。

`config/settings.json` があればそれを読み込み、無ければデフォルト値を使う。
パス類はすべてリポジトリルート基準。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SETTINGS_PATH = REPO_ROOT / "config" / "settings.json"


@dataclass
class Settings:
    # データ保存場所
    data_dir: Path = REPO_ROOT / "data"
    cards_dir: Path = REPO_ROOT / "data" / "cards"
    card_db_path: Path = REPO_ROOT / "data" / "cards" / "card_db.json"
    match_db_path: Path = REPO_ROOT / "data" / "matches" / "matches.db"
    regions_path: Path = REPO_ROOT / "config" / "regions.json"

    # キャプチャ設定
    capture_interval_sec: float = 1.0
    window_title_hint: str = "Shadowverse"
    monitor_index: int = 1  # mss は 0 が全モニタ結合、1以降が個別モニタ

    # マッチング設定
    hash_size: int = 16
    match_max_distance: int = 14  # これを超えたら「未検出」とみなす

    # 公式サイト (カード取得元)。サイト構造が変わったら要調整。
    official_site_base: str = "https://shadowverse-wb.com"
    official_cardlist_path: str = "/ja/deck/cardslist/"

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        path = path or DEFAULT_SETTINGS_PATH
        settings = cls()
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            for key, value in raw.items():
                if not hasattr(settings, key):
                    continue
                current = getattr(settings, key)
                if isinstance(current, Path):
                    value = Path(value)
                setattr(settings, key, value)
        return settings

    def ensure_dirs(self) -> None:
        self.cards_dir.mkdir(parents=True, exist_ok=True)
        self.match_db_path.parent.mkdir(parents=True, exist_ok=True)
        self.regions_path.parent.mkdir(parents=True, exist_ok=True)
