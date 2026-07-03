from unittest.mock import MagicMock

from svtracker.cards import card_fetcher
from svtracker.cards.card_fetcher import _parse_card_common, fetch_from_official_site


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


def test_parse_card_common_falls_back_for_unknown_type_and_rarity():
    common = {"card_id": 1, "name": "謞カード", "class": 7, "cost": 0, "type": 99, "rarity": 9, "atk": 0, "life": 0}

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

    responses = [MagicMock(), MagicMock()]
    responses[0].json.return_value = page1
    responses[1].json.return_value = page2
    for resp in responses:
        resp.raise_for_status.return_value = None

    session = MagicMock()
    session.get.side_effect = responses

    db = fetch_from_official_site(base_url="https://example.test", images_dir=tmp_path, session=session)

    assert len(db) == 2
    assert db.get("1").name == "A"
    assert db.get("2").name == "B"
    assert session.get.call_count == 2

    first_params = session.get.call_args_list[0].kwargs["params"]
    second_params = session.get.call_args_list[1].kwargs["params"]
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
    assert session.get.call_count == 1
