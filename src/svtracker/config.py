"""アプリ全体の設定。

`config/settings.json` があればそれを読み込み、無ければデフォルト値を使う。
パス類はすべて _default_root() が返すルート基準。
"""
from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _default_root() -> Path:
    """設定・データ(カード画像/DB・対戦履歴など)の保存先ルートを決める.

    開発環境(通常のPython実行)ではリポジトリルート。
    PyInstaller等で固めた実行ファイル(sys.frozen)では __file__ が一時展開
    ディレクトリ(--onefileでは exe終了時に削除される %TEMP%\\_MEIxxxx)を指すため、
    そこに保存するとデータが毎回消える。またインストール先(Program Files配下)は
    管理者権限なしでは書き込めない。そのためユーザーごとのアプリデータ
    ディレクトリ(Windowsは %APPDATA%\\svtracker、それ以外は ~/.svtracker)を使う。
    """
    if getattr(sys, "frozen", False):
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "svtracker"
        return Path.home() / ".svtracker"
    return Path(__file__).resolve().parents[2]


REPO_ROOT = _default_root()
DEFAULT_SETTINGS_PATH = REPO_ROOT / "config" / "settings.json"


@dataclass
class Settings:
    # データ保存場所
    data_dir: Path = REPO_ROOT / "data"
    cards_dir: Path = REPO_ROOT / "data" / "cards"
    card_db_path: Path = REPO_ROOT / "data" / "cards" / "card_db.json"
    match_db_path: Path = REPO_ROOT / "data" / "matches" / "matches.db"
    regions_path: Path = REPO_ROOT / "config" / "regions.json"

    # キャプチャ設定。プレイ表示(プレイ時に中央へ出る大型カード)は1秒前後で消えるため、
    # 取りこぼさないよう既定は0.5秒にしている。
    capture_interval_sec: float = 0.5
    window_title_hint: str = "Shadowverse"
    monitor_index: int = 1  # mss は 0 が全モニタ結合、1以降が個別モニタ

    # マッチング設定
    hash_size: int = 16
    match_max_distance: int = 14  # これを超えたら「未検出」とみなす(手札/盤面枠)
    # プレイ表示(中央の大型カード)専用のゆるい閾値。ゲーム内描画は光・エフェクト・
    # アニメ絵で公式静止画とpHash距離が大きく出る(実機で正しいカードでも70-90程度)。
    # プレイ表示は平面・正立・大型で最も条件が良く、かつ数フレーム連続で同じカードが
    # 表示され続ける(=時間的に安定)ため、閾値をゆるめても「同一カードが規定フレーム
    # 連続で最有力」という条件(reveal_confirm_frames)と併用すれば誤検出を抑えられる。
    reveal_max_distance: int = 40
    reveal_confirm_frames: int = 2  # プレイ表示をこのフレーム数連続で確認したら記録
    # プレイ表示の最有力候補をログに出す診断用の上限距離。閾値を超えていても、この距離
    # 未満なら「候補=カード名(距離)」をログ出力し、実際に正しいカードを捉えているかを
    # ユーザーが確認できるようにする(0以下で無効)。
    reveal_diagnostic_distance: int = 100

    # 手番判定用の基準色(RGB)。config/regions.json の active_player_pixel の座標を
    # 自分/相手の手番それぞれでスポイトした実際の色に置き換えること。ここではダミー値。
    self_turn_color: tuple[int, int, int] = (255, 215, 0)
    opponent_turn_color: tuple[int, int, int] = (200, 30, 30)
    active_player_color_max_distance: float = 60.0

    # 公式サイト (カード取得元)。内部API (/web/CardList/cardList) を利用する。
    official_site_base: str = "https://shadowverse-wb.com"

    # 対戦形式("unlimited" または "rotation")。相手プレイ予測のカードプール絞り込みに使う。
    game_format: str = "unlimited"
    # ローテーションで使えるカードセット(弾)番号のしきい値。この値以上のcard_set_idを
    # 持つカードのみローテーション対象とみなす。カードセットの区切りはゲーム側の
    # レギュレーション更新で変わるため、公式サイトの最新情報に合わせて随時更新すること。
    # None(未設定)の間はローテーションを選んでも絞り込みは行われない(=実質アンリミテッドと同じ)。
    rotation_min_card_set_id: Optional[int] = None

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
                elif isinstance(current, tuple):
                    value = tuple(value)
                setattr(settings, key, value)
        return settings

    def ensure_dirs(self) -> None:
        self.cards_dir.mkdir(parents=True, exist_ok=True)
        self.match_db_path.parent.mkdir(parents=True, exist_ok=True)
        self.regions_path.parent.mkdir(parents=True, exist_ok=True)
        # exe版はインストール先ではなく %APPDATA% に保存するため、どこに保存されるかを
        # 起動時に明示しておく(「フォルダが空」と迷子になる事故を防ぐ)。
        logger.info("データ保存先: %s (カード画像: %s)", self.data_dir, self.cards_dir)

    def save(self, path: Path | None = None) -> None:
        """GUIでの設定変更(手番の基準色など)を config/settings.json に書き戻す."""
        path = path or DEFAULT_SETTINGS_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        for f in fields(self):
            value = getattr(self, f.name)
            if isinstance(value, Path):
                value = str(value)
            elif isinstance(value, tuple):
                value = list(value)
            data[f.name] = value
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
