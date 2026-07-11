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


def test_opponent_lethal_warning_when_opponent_board_can_kill_self():
    tracker = MatchTracker()
    tracker.state.self_life = 10
    tracker.state.opponent_board = [
        BoardUnit(card_id="e1", name="敵ユニットA", atk=6, hp=4, can_attack=True),
        BoardUnit(card_id="e2", name="敵ユニットB", atk=5, hp=3, can_attack=True),
    ]

    recs = recommend_actions(tracker, hand=[])

    warning = next(r for r in recs if "相手のリーサルに警戒" in r.title)
    assert warning.priority == 0  # 自分のリーサルと同じ最優先
    assert "11" in warning.detail
    assert "10" in warning.detail


def test_no_opponent_lethal_warning_when_below_self_life():
    tracker = MatchTracker()
    tracker.state.self_life = 20
    tracker.state.opponent_board = [BoardUnit(card_id="e1", name="敵", atk=3, hp=3, can_attack=True)]

    recs = recommend_actions(tracker, hand=[])

    assert not any("相手のリーサルに警戒" in r.title for r in recs)


def test_no_opponent_lethal_warning_when_opponent_units_cannot_attack():
    tracker = MatchTracker()
    tracker.state.self_life = 5
    tracker.state.opponent_board = [
        BoardUnit(card_id="e1", name="疲労中の敵", atk=20, hp=4, can_attack=False)
    ]

    recs = recommend_actions(tracker, hand=[])

    assert not any("相手のリーサルに警戒" in r.title for r in recs)


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


def test_super_evolution_suggestion_when_sep_available():
    tracker = MatchTracker()
    tracker.state.self_sep = 1
    tracker.set_self_board([BoardUnit(card_id="1", name="味方", atk=2, hp=2, can_attack=True)])

    recs = recommend_actions(tracker, hand=[])

    rec = next(r for r in recs if "超進化ポイント" in r.title)
    assert "1残っています" in rec.detail


def test_no_super_evolution_suggestion_when_sep_is_zero():
    tracker = MatchTracker()
    tracker.state.self_sep = 0
    tracker.set_self_board([BoardUnit(card_id="1", name="味方", atk=2, hp=2, can_attack=True)])

    recs = recommend_actions(tracker, hand=[])

    assert not any("超進化ポイント" in r.title for r in recs)


def _seed_card_results(log: MatchLog, self_clan: str, opponent_clan: str, card_id: str, results: list[str]) -> None:
    for result in results:
        match_id = log.start_match(self_clan=self_clan, opponent_clan=opponent_clan)
        log.log_action(match_id, Action(turn=2, player=Player.SELF, action_type=ActionType.PLAY_CARD, card_id=card_id))
        log.end_match(match_id, result)


def _seed_evolve_results(log: MatchLog, self_clan: str, opponent_clan: str, results: list[str]) -> None:
    for result in results:
        match_id = log.start_match(self_clan=self_clan, opponent_clan=opponent_clan)
        log.log_action(match_id, Action(turn=4, player=Player.SELF, action_type=ActionType.EVOLVE))
        log.end_match(match_id, result)


def test_evolution_suggestion_includes_win_rate_when_data_available(tmp_path):
    log = MatchLog(tmp_path / "matches.db")
    _seed_evolve_results(log, "エルフ", "ロイヤル", ["win", "win", "loss"])  # 67%

    tracker = MatchTracker(self_clan="エルフ", opponent_clan="ロイヤル")
    tracker.state.self_ep = 2
    tracker.set_self_board([BoardUnit(card_id="1", name="味方", atk=2, hp=2, can_attack=True)])

    recs = recommend_actions(tracker, hand=[], match_log=log)

    rec = next(r for r in recs if "進化ポイント" in r.title)
    assert "67%" in rec.detail

    log.close()


def test_evolution_suggestion_omits_win_rate_with_too_few_samples(tmp_path):
    log = MatchLog(tmp_path / "matches.db")
    _seed_evolve_results(log, "エルフ", "ロイヤル", ["win"])  # 合計1戦 < MIN_WIN_RATE_SAMPLES

    tracker = MatchTracker(self_clan="エルフ", opponent_clan="ロイヤル")
    tracker.state.self_ep = 2
    tracker.set_self_board([BoardUnit(card_id="1", name="味方", atk=2, hp=2, can_attack=True)])

    recs = recommend_actions(tracker, hand=[], match_log=log)

    rec = next(r for r in recs if "進化ポイント" in r.title)
    assert "%" not in rec.detail

    log.close()


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


def test_pp_combo_prefers_card_with_better_win_rate_over_pp_tie(tmp_path):
    log = MatchLog(tmp_path / "matches.db")
    _seed_card_results(log, "エルフ", "ロイヤル", "a", ["win", "win", "win", "loss"])  # 75%

    tracker = MatchTracker(self_clan="エルフ", opponent_clan="ロイヤル")
    tracker.state.self_pp = 2
    hand = [
        # 意図的にデータ無しカードを先に置く: 勝率データが無ければ最初のカードが
        # タイブレークで勝つはず(同コストのため)。勝率データがあれば逆転する。
        Card(card_id="b", name="データ無しカード", clan="ニュートラル", cost=2, card_type="フォロワー"),
        Card(card_id="a", name="勝率高いカード", clan="ニュートラル", cost=2, card_type="フォロワー"),
    ]

    recs = recommend_actions(tracker, hand=hand, match_log=log)

    pp_rec = next(r for r in recs if r.title == "PP消費の提案")
    assert "勝率高いカード" in pp_rec.detail
    assert "データ無しカード" not in pp_rec.detail
    assert "過去の勝率データを考慮" in pp_rec.detail

    log.close()


def test_pp_combo_ignores_win_rate_without_match_log():
    tracker = MatchTracker(self_clan="エルフ", opponent_clan="ロイヤル")
    tracker.state.self_pp = 2
    hand = [
        Card(card_id="b", name="データ無しカード", clan="ニュートラル", cost=2, card_type="フォロワー"),
        Card(card_id="a", name="もう一枚のカード", clan="ニュートラル", cost=2, card_type="フォロワー"),
    ]

    recs = recommend_actions(tracker, hand=hand, match_log=None)

    pp_rec = next(r for r in recs if r.title == "PP消費の提案")
    assert "データ無しカード" in pp_rec.detail  # match_logが無ければ従来どおり最初のカードが選ばれる
    assert "過去の勝率データを考慮" not in pp_rec.detail
