from unittest.mock import MagicMock

import requests
from PIL import Image

from svtracker.cards import card_fetcher
from svtracker.cards.card_fetcher import (
    _download_card_image,
    _parse_card_common,
    fetch_from_official_site,
    import_from_local,
)


def test_parse_card_common_maps_known_codes():
    common = {
        "card_id": 10201110,
        "name": "二刀のゴブリン",
        "class": 0,
        "cost": 1,
        "type": 1,
        "rarity": 1,
        "atk": 1,
        "life": 1,
    }

    card = _parse_card_common(common)

    assert card.card_id == "10201110"
    assert card.name == "二刀のゴブリン"
    assert card.clan == "ニュートラル"
    assert card.cost == 1
    assert card.card_type == "フォロワー"
    assert card.rarity == "ブロンズ"
    assert card.base_atk == 1
    assert card.base_hp == 1


def test_parse_card_common_extracts_card_set_id_when_present():
    common = {
        "card_id": 1,
        "name": "A",
        "class": 0,
        "cost": 1,
        "type": 1,
        "rarity": 1,
        "atk": 1,
        "life": 1,
        "card_set_id": 12,
    }

    card = _parse_card_common(common)

    assert card.card_set_id == 12


def test_parse_card_common_leaves_card_set_id_none_when_absent():
    common = {"card_id": 1, "name": "A", "class": 0, "cost": 1, "type": 1, "rarity": 1, "atk": 1, "life": 1}

    card = _parse_card_common(common)

    assert card.card_set_id is None


def test_parse_card_common_falls_back_for_unknown_type_and_rarity():
    common = {"card_id": 1, "name": "謎カード", "class": 7, "cost": 0, "type": 99, "rarity": 9, "atk": 0, "life": 0}

    card = _parse_card_common(common)

    assert card.clan == "ネメシス"
    assert card.card_type == "type_99"
    assert card.rarity == ""


def test_parse_card_common_without_card_id_returns_none():
    assert _parse_card_common({"name": "no id"}) is None


def test_fetch_from_official_site_paginates_until_total_reached(tmp_path, monkeypatch):
    monkeypatch.setattr(card_fetcher.time, "sleep", lambda _seconds: None)

    page1 = {
        "data": {
            "count": 2,
            "sort_card_id_list": [1],
            "card_details": {
                "1": {
                    "common": {
                        "card_id": 1,
                        "name": "A",
                        "class": 0,
                        "cost": 1,
                        "type": 1,
                        "rarity": 1,
                        "atk": 1,
                        "life": 1,
                        "card_image_hash": None,
                    }
                }
            },
        }
    }
    page2 = {
        "data": {
            "count": 2,
            "sort_card_id_list": [2],
            "card_details": {
                "2": {
                    "common": {
                        "card_id": 2,
                        "name": "B",
                        "class": 1,
                        "cost": 2,
                        "type": 1,
                        "rarity": 2,
                        "atk": 2,
                        "life": 2,
                        "card_image_hash": None,
                    }
                }
            },
        }
    }

    prime_response = MagicMock()
    responses = [prime_response, MagicMock(), MagicMock()]
    responses[1].json.return_value = page1
    responses[2].json.return_value = page2
    for resp in responses[1:]:
        resp.raise_for_status.return_value = None

    session = MagicMock()
    session.get.side_effect = responses

    db = fetch_from_official_site(base_url="https://example.test", images_dir=tmp_path, session=session)

    assert len(db) == 2
    assert db.get("1").name == "A"
    assert db.get("2").name == "B"
    assert session.get.call_count == 3  # セッションCookie確立の1回 + APIページング2回

    first_params = session.get.call_args_list[1].kwargs["params"]
    second_params = session.get.call_args_list[2].kwargs["params"]
    assert first_params["offset"] == 0
    assert second_params["offset"] == 1


def test_fetch_from_official_site_stops_when_no_ids_returned(tmp_path, monkeypatch):
    monkeypatch.setattr(card_fetcher.time, "sleep", lambda _seconds: None)

    empty_page = {"data": {"count": 0, "sort_card_id_list": [], "card_details": {}}}
    response = MagicMock()
    response.json.return_value = empty_page
    response.raise_for_status.return_value = None

    session = MagicMock()
    session.get.return_value = response

    db = fetch_from_official_site(base_url="https://example.test", images_dir=tmp_path, session=session)

    assert len(db) == 0
    assert session.get.call_count == 2  # セッションCookie確立の1回 + API呼び出し1回


def test_import_from_local_parses_pp_ep_effect_columns(tmp_path):
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    Image.new("RGB", (32, 32), color="red").save(images_dir / "1.png")
    Image.new("RGB", (32, 32), color="blue").save(images_dir / "2.png")

    csv_path = tmp_path / "cards.csv"
    csv_path.write_text(
        "card_id,name,clan,cost,card_type,rarity,filename,max_pp_boost,pp_recover,ep_recover\n"
        "1,PPブーストカード,ニュートラル,2,フォロワー,,1.png,1,0,0\n"
        "2,普通のカード,ニュートラル,2,フォロワー,,2.png,,,\n",
        encoding="utf-8",
    )

    db = import_from_local(images_dir, csv_path)

    boosted = db.get("1")
    assert boosted.max_pp_boost == 1
    assert boosted.pp_recover == 0
    assert boosted.ep_recover == 0

    plain = db.get("2")
    assert plain.max_pp_boost == 0
    assert plain.pp_recover == 0
    assert plain.ep_recover == 0


def test_download_card_image_sends_referer_to_avoid_hotlink_block(tmp_path):
    response = MagicMock()
    response.content = b"fake-png-bytes"
    response.raise_for_status.return_value = None
    session = MagicMock()
    session.get.return_value = response

    result = _download_card_image("https://example.test", tmp_path, "1", "abc123", session)

    assert result == tmp_path / "1.png"
    assert (tmp_path / "1.png").read_bytes() == b"fake-png-bytes"

    # 言語セグメントは "ja" ではなく "jpn"(実機DevToolsで確認。"ja"は403になる)
    requested_url = session.get.call_args.args[0]
    assert requested_url == "https://example.test/uploads/card_image/jpn/card/abc123.png"

    call_headers = session.get.call_args.kwargs["headers"]
    assert call_headers["Referer"] == "https://example.test/ja/deck/cardslist/"


def test_fetch_from_official_site_warns_once_when_all_images_blocked(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(card_fetcher.time, "sleep", lambda _seconds: None)

    list_response = MagicMock()
    list_response.raise_for_status.return_value = None
    list_response.json.return_value = {
        "data": {
            "count": 1,
            "sort_card_id_list": [1],
            "card_details": {
                "1": {
                    "common": {
                        "card_id": 1,
                        "name": "A",
                        "class": 0,
                        "cost": 1,
                        "type": 1,
                        "rarity": 1,
                        "atk": 1,
                        "life": 1,
                        "card_image_hash": "abc123",
                    }
                }
            },
        }
    }

    image_response = MagicMock()
    image_response.raise_for_status.side_effect = requests.HTTPError("403 Client Error: Forbidden")

    prime_response = MagicMock()
    session = MagicMock()
    session.get.side_effect = [prime_response, list_response, image_response]

    with caplog.at_level("WARNING"):
        db = fetch_from_official_site(base_url="https://example.test", images_dir=tmp_path, session=session)

    assert len(db) == 1
    assert db.get("1").image_path is None
    warnings = [r.message for r in caplog.records if r.levelname == "WARNING"]
    assert any("すべて失敗しました" in msg for msg in warnings)
    assert any("import-cards" in msg for msg in warnings)


def test_fetch_from_official_site_primes_session_cookies_before_api_call(tmp_path, monkeypatch):
    monkeypatch.setattr(card_fetcher.time, "sleep", lambda _seconds: None)

    empty_page = {"data": {"count": 0, "sort_card_id_list": [], "card_details": {}}}
    response = MagicMock()
    response.json.return_value = empty_page
    response.raise_for_status.return_value = None

    session = MagicMock()
    session.get.return_value = response

    fetch_from_official_site(base_url="https://example.test", images_dir=tmp_path, session=session)

    prime_call = session.get.call_args_list[0]
    assert prime_call.args[0] == "https://example.test/ja/deck/cardslist/"
    assert "params" not in prime_call.kwargs


def test_fetch_from_official_site_continues_when_cookie_priming_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(card_fetcher.time, "sleep", lambda _seconds: None)

    empty_page = {"data": {"count": 0, "sort_card_id_list": [], "card_details": {}}}
    api_response = MagicMock()
    api_response.json.return_value = empty_page
    api_response.raise_for_status.return_value = None

    session = MagicMock()
    session.get.side_effect = [requests.ConnectionError("boom"), api_response]

    db = fetch_from_official_site(base_url="https://example.test", images_dir=tmp_path, session=session)

    assert len(db) == 0
    assert session.get.call_count == 2


def test_import_from_local_reads_is_token_column(tmp_path):
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    Image.new("RGB", (32, 32), color="green").save(images_dir / "t.png")
    csv_path = tmp_path / "tokens.csv"
    csv_path.write_text(
        "card_id,name,clan,cost,card_type,rarity,filename,is_token\n"
        "tok1,妖精,エルフ,1,フォロワー,ブロンズ,t.png,1\n"
        "norm1,通常,エルフ,2,フォロワー,ブロンズ,t.png,\n",
        encoding="utf-8",
    )
    db = import_from_local(images_dir, csv_path)
    assert db.get("tok1").is_token is True
    assert db.get("norm1").is_token is False
