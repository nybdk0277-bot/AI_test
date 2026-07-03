from svtracker.cards.models import Card
from svtracker.game.match_tracker import MatchTracker
from svtracker.game.models import Action, ActionType, BoardUnit, Player
from svtracker.prediction.advisor import recommend_actions
from svtracker.storage.match_log import MatchLog


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


def test_pp_combo_suggestion_includes_extra_pp():
    tracker = MatchTracker()
    tracker.state.self_pp = 3
    tracker.state.self_extra_pp = 2
    hand = [
        Card(card_id="a", name="コスト3", clan="ニュートラル", cost=3, card_type="フォロワー"),
        Card(card_id="b", name="コスト2", clan="ニュートラル", cost=2, card_type="フォロワー"),
    ]

    recs = recommend_actions(tracker, hand=hand)

    pp_rec = next(r for r in recs if r.title == "PP消費の提案")
    assert "コスト3" in pp_rec.detail
    assert "コスト2" in pp_rec.detail
    assert "エクストラPPを2消費" in pp_rec.detail


def test_evolution_point_suggestion_when_ep_available():
    tracker = MatchTracker()
    tracker.state.self_ep = 2
    tracker.set_self_board([BoardUnit(card_id="1", name="味方", atk=2, hp=2, can_attack=True)])

    recs = recommend_actions(tracker, hand=[])

    assert any("進化ポイント" in r.title for r in recs)


def test_no_evolution_suggestion_when_ep_is_zero():
    tracker = MatchTracker()
    tracker.state.self_ep = 0
    tracker.set_self_board([BoardUnit(card_id="1", name="味方", atk=2, hp=2, can_attack=True)])

    recs = recommend_actions(tracker, hand=[])

    assert not any("進化ポイント" in r.title for r in recs)


def _seed_card_results(log: MatchLog, self_clan: str, opponent_clan: str, card_id: str, results: list[str]) -> None:
    for result in results:
        match_id = log.start_match(self_clan=self_clan, opponent_clan=opponent_clan)
        log.log_action(match_id, Action(turn=2, player=Player.SELF, action_type=ActionType.PLAY_CARD, card_id=card_id))
        log.end_match(match_id, result)


def test_recommends_highest_win_rate_playable_card(tmp_path):
    log = MatchLog(tmp_path / "matches.db")
    _seed_card_results(log, "エルフ", "ロイヤル", "a", ["win", "win", "loss"])  # 67%
    _seed_card_results(log, "エルフ", "ロイヤル", "b", ["loss", "loss", "loss"])  # 0%

    tracker = MatchTracker(self_clan="エルフ", opponent_clan="ロイヤル")
    tracker.state.self_pp = 5
    hand = [
        Card(card_id="a", name="勝率高いカード", clan="ニュートラル", cost=2, card_type="フォロワー"),
        Card(card_id="b", name="勝率低いカード", clan="ニュートラル", cost=2, card_type="フォロワー"),
    ]

    recs = recommend_actions(tracker, hand=hand, match_log=log)

    rec = next(r for r in recs if "勝率の高いカード" in r.title)
    assert "勝率高いカード" in rec.title
    assert "67%" in rec.detail

    log.close()


def test_win_rate_recommendation_ignores_cards_with_too_few_samples(tmp_path):
    log = MatchLog(tmp_path / "matches.db")
    _seed_card_results(log, "エルフ", "ロイヤル", "a", ["win"])  # 合計1戦 < MIN_WIN_RATE_SAMPLES

    tracker = MatchTracker(self_clan="エルフ", opponent_clan="ロイヤル")
    tracker.state.self_pp = 5
    hand = [Card(card_id="a", name="サンプル不足カード", clan="ニュートラル", cost=2, card_type="フォロワー")]

    recs = recommend_actions(tracker, hand=hand, match_log=log)

    assert not any("勝率の高いカード" in r.title for r in recs)

    log.close()


def test_no_win_rate_recommendation_without_match_log():
    tracker = MatchTracker(self_clan="エルフ", opponent_clan="ロイヤル")
    tracker.state.self_pp = 5
    hand = [Card(card_id="a", name="カード", clan="ニュートラル", cost=2, card_type="フォロワー")]

    recs = recommend_actions(tracker, hand=hand, match_log=None)

    assert not any("勝率の高いカード" in r.title for r in recs)
