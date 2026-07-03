"""カードマスタ(名前・コスト・クラス・画像)の取得.

2種類の取得経路を用意している。

1. ``fetch_from_official_site`` : 公式サイト (shadowverse-wb.com) の
   カード一覧ページを走査してカード情報・画像URLを収集する。
   サイトのHTML構造が変わると動かなくなる可能性があるため、
   CSSセレクタは本ファイル冒頭の定数にまとめてあり、調整しやすくしている。
   このプロジェクトの開発環境は一般のWebサイトへの直接アクセスが
   できないため、ここでの実装は未検証。実際に使う際は
   ``--dry-run`` 等で少数ページ取得して構造を確認すること。

2. ``import_from_local`` : 既に手元にある「カード画像フォルダ + メタ情報CSV」
   から DB を構築する。スクレイパーが使えない/使いたくない場合の
   確実な代替手段。CSVフォーマットは README を参照。
"""
from __future__ import annotations

import csv
import logging
import time
from pathlib import Path
from typing import Iterable, Optional

import requests
from bs4 import BeautifulSoup
from PIL import Image

from svtracker.cards.card_database import CardDatabase
from svtracker.cards.hashing import compute_phash_hex
from svtracker.cards.models import Card

logger = logging.getLogger(__name__)

# --- 公式サイト用セレクタ設定（サイト変更時はここを調整）----------------
CARD_LIST_URL_TMPL = "{base}{path}?page={page}"
CARD_ITEM_SELECTOR = "li.p-cardslist-item, div.card-list-item"
CARD_NAME_SELECTOR = ".card-name, .p-cardslist-item__name"
CARD_IMAGE_SELECTOR = "img"
CARD_ID_ATTR = "data-card-id"
CARD_COST_SELECTOR = ".cost, .p-cardslist-item__cost"
CARD_CLAN_ATTR = "data-clan"
CARD_TYPE_ATTR = "data-type"
CARD_RARITY_ATTR = "data-rarity"
CARD_ATK_ATTR = "data-atk"
CARD_HP_ATTR = "data-life"
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}
REQUEST_INTERVAL_SEC = 1.0  # サイトに負荷をかけないよう間隔を空ける


def fetch_from_official_site(
    base_url: str,
    list_path: str,
    images_dir: Path,
    max_pages: int = 50,
    hash_size: int = 16,
    session: Optional[requests.Session] = None,
) -> CardDatabase:
    """公式カード一覧ページを走査してCardDatabaseを構築する.

    ページネーションが尽きた（カードが1件も見つからない）時点で終了する。
    """
    session = session or requests.Session()
    images_dir.mkdir(parents=True, exist_ok=True)
    db = CardDatabase()

    for page in range(1, max_pages + 1):
        url = CARD_LIST_URL_TMPL.format(base=base_url, path=list_path, page=page)
        logger.info("fetching card list page %s: %s", page, url)
        resp = session.get(url, headers=REQUEST_HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        items = soup.select(CARD_ITEM_SELECTOR)
        if not items:
            logger.info("no more cards found, stopping at page %s", page)
            break

        for item in items:
            card = _parse_card_item(item, base_url)
            if card is None:
                continue
            image_path = _download_card_image(item, base_url, images_dir, card.card_id, session)
            if image_path is not None:
                card.image_path = str(image_path)
                with Image.open(image_path) as img:
                    card.phash = compute_phash_hex(img, hash_size=hash_size)
            db.add(card)

        time.sleep(REQUEST_INTERVAL_SEC)

    return db


def _parse_card_item(item, base_url: str) -> Optional[Card]:
    card_id = item.get(CARD_ID_ATTR)
    if not card_id:
        # 属性で取れない場合、詳細ページへのリンクの card_id= クエリから拾う
        link = item.select_one("a[href*='card_id=']")
        if link and "card_id=" in link.get("href", ""):
            card_id = link["href"].split("card_id=")[-1].split("&")[0]
    if not card_id:
        logger.debug("skip item without card_id: %s", item)
        return None

    name_el = item.select_one(CARD_NAME_SELECTOR)
    name = name_el.get_text(strip=True) if name_el else f"card_{card_id}"

    cost_el = item.select_one(CARD_COST_SELECTOR)
    cost = _safe_int(cost_el.get_text(strip=True)) if cost_el else 0

    clan = item.get(CARD_CLAN_ATTR, "") or ""
    card_type = item.get(CARD_TYPE_ATTR, "") or ""
    rarity = item.get(CARD_RARITY_ATTR, "") or ""
    atk_raw = item.get(CARD_ATK_ATTR)
    hp_raw = item.get(CARD_HP_ATTR)

    return Card(
        card_id=str(card_id),
        name=name,
        clan=clan,
        cost=cost,
        card_type=card_type,
        rarity=rarity,
        base_atk=_safe_int(atk_raw) if atk_raw else None,
        base_hp=_safe_int(hp_raw) if hp_raw else None,
    )


def _download_card_image(item, base_url: str, images_dir: Path, card_id: str, session: requests.Session) -> Optional[Path]:
    img_el = item.select_one(CARD_IMAGE_SELECTOR)
    if img_el is None:
        return None
    src = img_el.get("src") or img_el.get("data-src")
    if not src:
        return None
    if src.startswith("//"):
        src = "https:" + src
    elif src.startswith("/"):
        src = base_url.rstrip("/") + src

    dest = images_dir / f"{card_id}.png"
    if dest.exists():
        return dest
    try:
        resp = session.get(src, headers=REQUEST_HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("failed to download image for card %s: %s", card_id, exc)
        return None
    dest.write_bytes(resp.content)
    return dest


def _safe_int(text: str) -> int:
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else 0


# --- ローカルインポート経路 -------------------------------------------------

def import_from_local(images_dir: Path, metadata_csv: Path, hash_size: int = 16) -> CardDatabase:
    """手元のカード画像フォルダ + メタ情報CSVからDBを構築する.

    CSVヘッダ: card_id,name,clan,cost,card_type,rarity,filename[,base_atk,base_hp]
    filename は images_dir 内の画像ファイル名。
    """
    db = CardDatabase()
    with metadata_csv.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            card = Card(
                card_id=str(row["card_id"]),
                name=row["name"],
                clan=row.get("clan", ""),
                cost=int(row.get("cost") or 0),
                card_type=row.get("card_type", ""),
                rarity=row.get("rarity", ""),
                base_atk=int(row["base_atk"]) if row.get("base_atk") else None,
                base_hp=int(row["base_hp"]) if row.get("base_hp") else None,
            )
            image_file = images_dir / row["filename"]
            if image_file.exists():
                card.image_path = str(image_file)
                with Image.open(image_file) as img:
                    card.phash = compute_phash_hex(img, hash_size=hash_size)
            else:
                logger.warning("image file not found for card %s: %s", card.card_id, image_file)
            db.add(card)
    return db


def rehash_database(db: CardDatabase, hash_size: int = 16) -> None:
    """画像は既にあるがphash未計算/再計算したい場合に使う."""
    for card in db.all():
        if not card.image_path:
            continue
        path = Path(card.image_path)
        if not path.exists():
            continue
        with Image.open(path) as img:
            card.phash = compute_phash_hex(img, hash_size=hash_size)
