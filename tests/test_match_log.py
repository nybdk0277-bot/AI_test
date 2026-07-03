from svtracker.game.models import Action, ActionType, Player
from svtracker.storage.match_log import MatchLog


def test_update_match_clans_overwrites_only_given_fields(tmp_path):
    log = MatchLog(tmp_path / "matches.db")
    match_id = log.start_match(self_clan="", opponent_clan="")

    log.update_match_clans(match_id, self_clan="エルフ")

    with log._conn:
        row = log._conn.execute(
            "SELECT self_clan, opponent_clan FROM matches WHERE id = ?", (match_id,)
        ).fetchone()
    assert row == ("エルフ", "")

    log.update_match_clans(match_id, opponent_clan="ロイヤル")

    with log._conn:
        row = log._conn.execute(
            "SELECT self_clan, opponent_clan FROM matches WHERE id = ?", (match_id,)
        ).fetchone()
    assert row == ("エルフ", "ロイヤル")

    log.close()


def test_match_results_counts_win_loss_and_ignores_unrecorded(tmp_path):
    log = MatchLog(tmp_path / "matches.db")
    m1 = log.start_match(self_clan="エルフ", opponent_clan="ロイヤル")
    log.end_match(m1, "win")
    m2 = log.start_match(self_clan="エルフ", opponent_clan="ロイヤル")
    log.end_match(m2, "loss")
    m3 = log.start_match(self_clan="エルフ", opponent_clan="ロイヤル")
    log.end_match(m3, "unknown")
    m4 = log.start_match(self_clan="ウィッチ", opponent_clan="ロイヤル")
    log.end_match(m4, "win")

    stats = log.match_results(opponent_clan="ロイヤル")
    assert stats.wins == 2
    assert stats.losses == 1
    assert stats.total == 3
    assert stats.win_rate == 2 / 3

    filtered = log.match_results(self_clan="エルフ", opponent_clan="ロイヤル")
    assert filtered.wins == 1
    assert filtered.losses == 1
    assert filtered.total == 2

    log.close()


def test_match_results_with_no_data_has_none_win_rate(tmp_path):
    log = MatchLog(tmp_path / "matches.db")

    stats = log.match_results(opponent_clan="ロイヤル")

    assert stats.total == 0
    assert stats.win_rate is None

    log.close()


def test_card_win_rate_counts_distinct_matches_where_card_was_played(tmp_path):
    log = MatchLog(tmp_path / "matches.db")

    m1 = log.start_match(self_clan="エルフ", opponent_clan="ロイヤル")
    log.log_action(m1, Action(turn=2, player=Player.SELF, action_type=ActionType.PLAY_CARD, card_id="c1"))
    log.log_action(m1, Action(turn=4, player=Player.SELF, action_type=ActionType.PLAY_CARD, card_id="c1"))
    log.end_match(m1, "win")

    m2 = log.start_match(self_clan="エルフ", opponent_clan="ロイヤル")
    log.log_action(m2, Action(turn=2, player=Player.SELF, action_type=ActionType.PLAY_CARD, card_id="c1"))
    log.end_match(m2, "loss")

    m3 = log.start_match(self_clan="エルフ", opponent_clan="ロイヤル")
    log.log_action(m3, Action(turn=2, player=Player.SELF, action_type=ActionType.PLAY_CARD, card_id="other"))
    log.end_match(m3, "win")

    stats = log.card_win_rate("エルフ", "ロイヤル", "c1")

    # m1で2回プレイしていても1対戦として数える
    assert stats.wins == 1
    assert stats.losses == 1
    assert stats.total == 2

    log.close()
