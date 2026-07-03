from svtracker.cards.models import Card
from svtracker.game.match_tracker import MatchTracker
from svtracker.game.models import BoardUnit
from svtracker.prediction.advisor import recommend_actions


def test_lethal_is_detected_when_attack_power_exceeds_opponent_life():
    tracker = MatchTracker()
    tracker.state.opponent_life = 10
    tracker.set_self_board(
        [
            BoardUnit(card_id="1", name="ユニットA", atk=6, hp=4, can_attack=True),
            BoardUnit(card_id="2", name="ユニットB", atk=5, hp=3, can_attack=True),
        ]
    )

    recs = recommend_actions(tracker, hand=[])

    assert any("リーサル" in r.title for r in recs)
    assert recs[0].priority == 0  # 最優先で提示される


def test_no_lethal_when_units_cannot_attack():
    tracker = MatchTracker()
    tracker.state.opponent_life = 10
    tracker.set_self_board(
        [BoardUnit(card_id="1", name="疲労ユニット", atk=20, hp=4, can_attack=False)]
    )

    recs = recommend_actions(tracker, hand=[])

    assert not any("リーサル" in r.title for r in recs)


def test_favorable_trade_is_suggested():
    tracker = MatchTracker()
    tracker.state.opponent_life = 20
    tracker.set_self_board([BoardUnit(card_id="1", name="味方", atk=4, hp=4, can_attack=True)])
    tracker.state.opponent_board = [BoardUnit(card_id="e1", name="敵", atk=2, hp=3, can_attack=True)]

    recs = recommend_actions(tracker, hand=[])

    assert any("有利トレード" in r.title for r in recs)


def test_pp_combo_suggestion_maximizes_pp_usage():
    tracker = MatchTracker()
    tracker.state.self_pp = 5
    hand = [
        Card(card_id="a", name="コスト2", clan="ニュートラル", cost=2, card_type="フォロワー"),
        Card(card_id="b", name="コスト3", clan="ニュートラル", cost=3, card_type="フォロワー"),
        Card(card_id="c", name="コスト4", clan="ニュートラル", cost=4, card_type="フォロワー"),
    ]

    recs = recommend_actions(tracker, hand=hand)

    pp_rec = next(r for r in recs if r.title == "PP消費の提案")
    assert "コスト2" in pp_rec.detail
    assert "コスト3" in pp_rec.detail
    assert "コスト4" not in pp_rec.detail  # 2+3=5がPPを使い切る最適解
