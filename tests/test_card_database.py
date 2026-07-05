from svtracker.cards.card_database import CardDatabase
from svtracker.cards.models import Card


def test_merge_adds_cards_without_removing_existing_ones():
    db = CardDatabase([Card(card_id="1", name="公式カード", clan="ロイヤル", cost=2, card_type="フォロワー")])
    tokens = CardDatabase([Card(card_id="t1", name="トークン", clan="ロイヤル", cost=0, card_type="フォロワー")])

    db.merge(tokens)

    assert len(db) == 2
    assert db.get("1") is not None
    assert db.get("t1") is not None


def test_merge_overwrites_cards_with_same_id():
    db = CardDatabase([Card(card_id="1", name="旧データ", clan="ロイヤル", cost=2, card_type="フォロワー")])
    updated = CardDatabase([Card(card_id="1", name="新データ", clan="ロイヤル", cost=3, card_type="フォロワー")])

    db.merge(updated)

    assert len(db) == 1
    assert db.get("1").name == "新データ"
    assert db.get("1").cost == 3


def test_save_and_load_round_trip_preserves_pp_ep_effect_fields(tmp_path):
    db = CardDatabase(
        [
            Card(
                card_id="1",
                name="PP回復カード",
                clan="ニュートラル",
                cost=3,
                card_type="スペル",
                max_pp_boost=1,
                pp_recover=2,
                ep_recover=1,
            )
        ]
    )
    path = tmp_path / "card_db.json"

    db.save(path)
    loaded = CardDatabase.load(path)

    card = loaded.get("1")
    assert card.max_pp_boost == 1
    assert card.pp_recover == 2
    assert card.ep_recover == 1


def test_load_defaults_pp_ep_effect_fields_to_zero_for_old_data_without_them(tmp_path):
    path = tmp_path / "card_db.json"
    path.write_text(
        '[{"card_id": "1", "name": "旧形式カード", "clan": "ニュートラル", "cost": 1, "card_type": "フォロワー"}]',
        encoding="utf-8",
    )

    loaded = CardDatabase.load(path)

    card = loaded.get("1")
    assert card.max_pp_boost == 0
    assert card.pp_recover == 0
    assert card.ep_recover == 0
