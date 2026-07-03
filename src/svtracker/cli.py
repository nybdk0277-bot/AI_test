"""svtracker CLI エントリポイント."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from svtracker.config import Settings


def _cmd_fetch_cards(args: argparse.Namespace) -> None:
    from svtracker.cards.card_fetcher import fetch_from_official_site

    settings = Settings.load()
    settings.ensure_dirs()
    db = fetch_from_official_site(
        base_url=settings.official_site_base,
        images_dir=settings.cards_dir,
        hash_size=settings.hash_size,
    )
    db.save(settings.card_db_path)
    print(f"{len(db)} 枚のカードを取得し {settings.card_db_path} に保存しました。")


def _cmd_import_cards(args: argparse.Namespace) -> None:
    from svtracker.cards.card_fetcher import import_from_local

    settings = Settings.load()
    settings.ensure_dirs()
    db = import_from_local(Path(args.images_dir), Path(args.metadata_csv), hash_size=settings.hash_size)
    db.save(settings.card_db_path)
    print(f"{len(db)} 枚のカードをローカルから取り込み {settings.card_db_path} に保存しました。")


def _cmd_screenshot(args: argparse.Namespace) -> None:
    from svtracker.capture.screen_capture import ScreenCapture

    settings = Settings.load()
    capture = ScreenCapture(monitor_index=settings.monitor_index, window_title_hint=None)
    try:
        image = capture.grab()
        out_path = Path(args.output)
        image.save(out_path)
        print(f"スクリーンショットを保存しました: {out_path} ({image.width}x{image.height})")
        print("画像ビューアで座標を確認し、config/regions.json の各枠の値を調整してください。")
    finally:
        capture.close()


def _cmd_run(args: argparse.Namespace) -> None:
    from svtracker.app import MonitorApp

    settings = Settings.load()
    app = MonitorApp(settings, self_clan=args.self_clan, opponent_clan=args.opponent_clan)
    try:
        app.run_forever()
    finally:
        app.close()


def _cmd_stats(args: argparse.Namespace) -> None:
    from svtracker.storage.match_log import MatchLog

    settings = Settings.load()
    if not settings.match_db_path.exists():
        print("対戦記録がまだありません。")
        return
    log = MatchLog(settings.match_db_path)
    try:
        pool = log.opponent_card_pool(args.clan)
        if not pool:
            print(f"クラン '{args.clan}' の対戦記録が見つかりませんでした。")
            return
        print(f"クラン '{args.clan}' 相手によく使われたカード:")
        for card_id, count in pool[: args.top]:
            print(f"  card_id={card_id}: {count}試合で使用")
    finally:
        log.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="svtracker", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true", help="デバッグログを表示する")
    sub = parser.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch-cards", help="公式サイトからカードマスタを取得する")
    p_fetch.set_defaults(func=_cmd_fetch_cards)

    p_import = sub.add_parser("import-cards", help="ローカルの画像+CSVからカードマスタを取り込む")
    p_import.add_argument("images_dir")
    p_import.add_argument("metadata_csv")
    p_import.set_defaults(func=_cmd_import_cards)

    p_shot = sub.add_parser("screenshot", help="キャリブレーション用にスクリーンショットを1枚保存する")
    p_shot.add_argument("-o", "--output", default="screenshot.png")
    p_shot.set_defaults(func=_cmd_screenshot)

    p_run = sub.add_parser("run", help="画面監視を開始する")
    p_run.add_argument("--self-clan", default="", help="自分のクラン名")
    p_run.add_argument("--opponent-clan", default="", help="相手のクラン名")
    p_run.set_defaults(func=_cmd_run)

    p_stats = sub.add_parser("stats", help="記録済みの対戦統計を表示する")
    p_stats.add_argument("clan", help="対象クラン名")
    p_stats.add_argument("--top", type=int, default=20)
    p_stats.set_defaults(func=_cmd_stats)

    return parser


def _ensure_utf8_streams() -> None:
    """Windowsの既定コンソールエンコーディング(cp1252等)では、ヘルプ/ログの日本語文字列を
    出力しようとした際に UnicodeEncodeError でクラッシュすることがあるため、
    可能なら標準出力/標準エラーをUTF-8に強制する."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_streams()
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
