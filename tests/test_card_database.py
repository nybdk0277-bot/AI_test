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
