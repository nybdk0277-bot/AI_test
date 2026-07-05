"""カードマスタ(名前・コスト・クラス・画像)の取得.

2種類の取得経路を用意している。

1. ``fetch_from_official_site`` : 公式サイト (shadowverse-wb.com) が
   カード一覧ページを描画するために内部で呼んでいるJSON API
   (``/web/CardList/cardList``) を直接叩いて収集する。
   カード一覧ページ自体はJavaScriptで描画されるSPAで、素のHTMLには
   カード情報が含まれていないため、静的HTML解析ではなくこのAPIを使う。
   レスポンス形式が変わった場合は本ファイルのフィールド名・マッピングを
   実際のレスポンスに合わせて調整すること。

2. ``import_from_local`` : 既に手元にある「カード画像フォルダ + メタ情報CSV」
   から DB を構築する。API経路が使えない/使いたくない場合の
   確実な代替手段。CSVフォーマットは README を参照。
"""
from __future__ import annotations

import csv
import logging
import time
from pathlib import Path
from typing import Optional

import requests
from PIL import Image

from svtracker.cards.card_database import CardDatabase
from svtracker.cards.hashing import compute_phash_hex
from svtracker.cards.models import Card

logger = logging.getLogger(__name__)

# --- 公式サイト内部API設定（レスポンス形式が変わったら要調整）----------------
CARD_LIST_API_PATH = "/web/CardList/cardList"
CARD_LIST_PAGE_PATH = "/ja/deck/cardslist/"
CARD_IMAGE_URL_TMPL = "{base}/uploads/card_image/ja/card/{image_hash}.png"
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "X-Requested-With": "XMLHttpRequest",
}
# 画像(/uploads/card_image/...)はJSON APIとは別にホットリンク対策(Referer必須)が
# かかっているらしく、REQUEST_HEADERSのままだと403になる。Refererとブラウザの画像
# フェッチっぽいヘッダーを足したものを別途用意する。
IMAGE_REQUEST_HEADERS = {
    "User-Agent": REQUEST_HEADERS["User-Agent"],
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Sec-Fetch-Dest": "image",
    "Sec-Fetch-Mode": "no-cors",
    "Sec-Fetch-Site": "same-origin",
}
REQUEST_INTERVAL_SEC = 1.0  # サイトに負荷をかけないよう間隔を空ける
MAX_PAGES_SAFETY_LIMIT = 1000  # count取得に失敗した場合の無限ループ防止

# 公式サイトのカード一覧の検索条件チェックボックス値と対応(HTML調査済み)。
CLASS_NAMES = {
    0: "ニュートラル",
    1: "エルフ",
    2: "ロイヤル",
    3: "ウィッチ",
    4: "ドラゴン",
    5: "ナイトメア",
    6: "ビショップ",
    7: "ネメシス",
}
RARITY_NAMES = {1: "ブロンズ", 2: "シルバー", 3: "ゴールド", 4: "レジェンド"}
# 確認できているのは 1=フォロワー/2=スペル/3=アミュレット のみ。
# 未知の値は "type_N" のまま保持する(マッチング精度には影響しない)。
CARD_TYPE_NAMES = {1: "フォロワー", 2: "スペル", 3: "アミュレット"}


def fetch_from_official_site(
    base_url: str,
    images_dir: Path,
    hash_size: int = 16,
    session: Optional[requests.Session] = None,
) -> CardDatabase:
    """公式サイトの内部API からカード一覧・画像URLを取得してCardDatabaseを構築する.

    ``data.count`` (総件数) に達するまで ``offset`` を進めながらページングする。
    """
    session = session or requests.Session()
    images_dir.mkdir(parents=True, exist_ok=True)
    db = CardDatabase()
    _prime_session_cookies(base_url, session)

    image_attempts = 0
    image_failures = 0
    offset = 0
    total: Optional[int] = None
    for _ in range(MAX_PAGES_SAFETY_LIMIT):
        if total is not None and offset >= total:
            break

        url = f"{base_url.rstrip('/')}{CARD_LIST_API_PATH}"
        params = {
            "offset": offset,
            "class": "0,1,2,3,4,5,6,7",
            "cost": "0,1,2,3,4,5,6,7,8,9,10",
        }
        logger.info("fetching card list: offset=%s", offset)
        resp = session.get(url, params=params, headers=REQUEST_HEADERS, timeout=15)
        resp.raise_for_status()
        payload = resp.json()
        data = payload.get("data", {})
        total = data.get("count", 0)
        page_ids = data.get("sort_card_id_list", [])
        card_details = data.get("card_details", {})
        if not page_ids:
            break

        for card_id in page_ids:
            detail = card_details.get(str(card_id))
            if detail is None:
                continue
            common = detail.get("common", {})
            card = _parse_card_common(common)
            if card is None:
                continue
            if common.get("card_image_hash"):
                image_attempts += 1
            image_path = _download_card_image(
                base_url, images_dir, card.card_id, common.get("card_image_hash"), session
            )
            if image_path is not None:
                card.image_path = str(image_path)
                with Image.open(image_path) as img:
                    card.phash = compute_phash_hex(img, hash_size=hash_size)
            elif common.get("card_image_hash"):
                image_failures += 1
            db.add(card)

        offset += len(page_ids)
        time.sleep(REQUEST_INTERVAL_SEC)

    if image_attempts > 0 and image_failures == image_attempts:
        logger.warning(
            "カード画像のダウンロードが%d件すべて失敗しました。サイト側のホットリンク対策"
            "(Referer/ヘッダーチェック)がヘッダー付与だけでは回避できていない可能性があります。"
            "画像が無いカードはpHashが計算されず認識対象になりません。実機ブラウザの開発者ツールで"
            "画像リクエストの実際のヘッダー/Cookieを確認するか、`import-cards` で手元に用意した"
            "画像+CSVからカードDBを構築してください。",
            image_failures,
        )
    elif image_failures > 0:
        logger.warning(
            "カード画像のダウンロードが%d/%d件失敗しました。失敗したカードはpHashが計算されず"
            "認識対象になりません。`import-cards --merge` で該当カードの画像を後から補うことも"
            "できます。",
            image_failures,
            image_attempts,
        )

    return db


def _prime_session_cookies(base_url: str, session: requests.Session) -> None:
    """カード一覧ページを一度読み込み、ブラウザ同様にセッションCookieを確立する.

    画像CDNのホットリンク対策がReferer/UAヘッダーだけでなくセッションCookieの有無も
    見ている場合、APIをいきなり叩くだけではCookieが無く403になる可能性がある。
    ここで失敗しても致命的ではない(単にCookie無しで以降の取得を試みるだけ)ため、
    例外は握りつぶして続行する。
    """
    url = f"{base_url.rstrip('/')}{CARD_LIST_PAGE_PATH}"
    try:
        session.get(url, headers=REQUEST_HEADERS, timeout=15)
    except requests.RequestException:
        logger.debug("failed to prime session cookies from %s", url, exc_info=True)


def _parse_card_common(common: dict) -> Optional[Card]:
    card_id = common.get("card_id")
    if card_id is None:
        return None

    name = common.get("name") or f"card_{card_id}"
    clan = CLASS_NAMES.get(common.get("class"), "")
    cost = int(common.get("cost", 0))
    type_code = common.get("type")
    card_type = CARD_TYPE_NAMES.get(type_code, f"type_{type_code}")
    rarity = RARITY_NAMES.get(common.get("rarity"), "")
    # card_set_id(カードセット/弾番号、ローテーション判定に使う)というフィールド名は
    # 未検証の推測。実際のレスポンスで名前が違う/存在しない場合はNoneのままになり、
    # ローテーション絞り込みでは「対象から除外しない」安全側にフォールバックする。
    # 実際のフィールド名を確認したら、ここのキー名を実データに合わせて調整すること。
    card_set_id = common.get("card_set_id")

    # max_pp_boost/pp_recover/ep_recoverはカード効果(能力テキスト)由来のデータで、
    # このAPIのようなカード基礎情報レスポンスには構造化された形で含まれていないとみられる。
    # そのため常に0(効果なし扱い)のままにし、`import-cards`のCSVでの手動指定に委ねる
    # (cards/models.py の Card.max_pp_boost 等のコメント、READMEも参照)。
    return Card(
        card_id=str(card_id),
        name=name,
        clan=clan,
        cost=cost,
        card_type=card_type,
        rarity=rarity,
        base_atk=common.get("atk"),
        base_hp=common.get("life"),
        card_set_id=int(card_set_id) if card_set_id is not None else None,
    )


def _download_card_image(
    base_url: str, images_dir: Path, card_id: str, image_hash: Optional[str], session: requests.Session
) -> Optional[Path]:
    if not image_hash:
        return None
    dest = images_dir / f"{card_id}.png"
    if dest.exists():
        return dest
    url = CARD_IMAGE_URL_TMPL.format(base=base_url.rstrip("/"), image_hash=image_hash)
    headers = {**IMAGE_REQUEST_HEADERS, "Referer": f"{base_url.rstrip('/')}{CARD_LIST_PAGE_PATH}"}
    try:
        resp = session.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("failed to download image for card %s: %s", card_id, exc)
        return None
    dest.write_bytes(resp.content)
    return dest


# --- ローカルインポート経路 -------------------------------------------------

def import_from_local(images_dir: Path, metadata_csv: Path, hash_size: int = 16) -> CardDatabase:
    """手元のカード画像フォルダ + メタ情報CSVからDBを構築する.

    CSVヘッダ: card_id,name,clan,cost,card_type,rarity,filename
    [,base_atk,base_hp,card_set_id,max_pp_boost,pp_recover,ep_recover]
    filename は images_dir 内の画像ファイル名。card_set_id はローテーション絞り込みに使う
    カードセット(弾)番号(省略可、無ければローテーション判定で除外されない)。
    max_pp_boost/pp_recover/ep_recover は効果によるPP上限増加・PP回復・進化ポイント回復量
    (省略可、いずれも既定0=効果なし)。公式サイトAPIには効果の構造化データが無いため
    `fetch-cards` 経由では常に0になる。既に `fetch-cards` で取得済みのカードに対して
    これらの値だけ後から補いたい場合は、`images_dir` に既存の `data/cards/` を指定し
    filename に同じ画像(`{card_id}.png`)を指定した上で `import-cards --merge` を使う。
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
                card_set_id=int(row["card_set_id"]) if row.get("card_set_id") else None,
                max_pp_boost=int(row["max_pp_boost"]) if row.get("max_pp_boost") else 0,
                pp_recover=int(row["pp_recover"]) if row.get("pp_recover") else 0,
                ep_recover=int(row["ep_recover"]) if row.get("ep_recover") else 0,
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
