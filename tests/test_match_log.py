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


def test_card_win_rate_ignores_non_play_card_actions_with_same_card_id(tmp_path):
    log = MatchLog(tmp_path / "matches.db")

    m1 = log.start_match(self_clan="エルフ", opponent_clan="ロイヤル")
    # 盤面から離れた(破壊された)だけで、プレイはしていないカード
    log.log_action(m1, Action(turn=3, player=Player.SELF, action_type=ActionType.UNIT_DESTROYED, card_id="c1"))
    log.end_match(m1, "win")

    stats = log.card_win_rate("エルフ", "ロイヤル", "c1")

    assert stats.total == 0

    log.close()


def test_opponent_card_pool_ignores_non_play_card_actions(tmp_path):
    log = MatchLog(tmp_path / "matches.db")

    m1 = log.start_match(self_clan="エルフ", opponent_clan="ロイヤル")
    log.log_action(m1, Action(turn=3, player=Player.OPPONENT, action_type=ActionType.UNIT_DESTROYED, card_id="c1"))
    log.log_action(m1, Action(turn=4, player=Player.OPPONENT, action_type=ActionType.PLAY_CARD, card_id="c2"))
    log.end_match(m1, "win")

    pool = log.opponent_card_pool("ロイヤル")

    assert ("c2", 1) in pool
    assert all(card_id != "c1" for card_id, _count in pool)

    log.close()


def test_card_play_frequency_ignores_non_play_card_actions(tmp_path):
    log = MatchLog(tmp_path / "matches.db")

    m1 = log.start_match(self_clan="エルフ", opponent_clan="ロイヤル")
    log.log_action(m1, Action(turn=3, player=Player.OPPONENT, action_type=ActionType.UNIT_DESTROYED, card_id="c1"))
    log.end_match(m1, "win")

    frequency = log.card_play_frequency("ロイヤル", "c1", turn=3)

    assert frequency == 0.0

    log.close()


def test_evolve_win_rate_counts_distinct_matches_with_evolve_or_super_evolve(tmp_path):
    log = MatchLog(tmp_path / "matches.db")

    m1 = log.start_match(self_clan="エルフ", opponent_clan="ロイヤル")
    log.log_action(m1, Action(turn=4, player=Player.SELF, action_type=ActionType.EVOLVE))
    log.log_action(m1, Action(turn=6, player=Player.SELF, action_type=ActionType.EVOLVE))  # 同一対戦、2重カウントしない
    log.end_match(m1, "win")

    m2 = log.start_match(self_clan="エルフ", opponent_clan="ロイヤル")
    log.log_action(m2, Action(turn=8, player=Player.SELF, action_type=ActionType.SUPER_EVOLVE))
    log.end_match(m2, "loss")

    m3 = log.start_match(self_clan="エルフ", opponent_clan="ロイヤル")  # 進化なしの対戦は対象外
    log.end_match(m3, "win")

    stats = log.evolve_win_rate("エルフ", "ロイヤル")

    assert stats.wins == 1
    assert stats.losses == 1
    assert stats.total == 2

    log.close()


def test_evolve_win_rate_ignores_opponent_evolve_actions(tmp_path):
    log = MatchLog(tmp_path / "matches.db")

    m1 = log.start_match(self_clan="エルフ", opponent_clan="ロイヤル")
    log.log_action(m1, Action(turn=4, player=Player.OPPONENT, action_type=ActionType.EVOLVE))
    log.end_match(m1, "win")

    stats = log.evolve_win_rate("エルフ", "ロイヤル")

    assert stats.total == 0

    log.close()


def test_log_action_stores_and_summarizes_context(tmp_path):
    log = MatchLog(tmp_path / "matches.db")

    m1 = log.start_match(self_clan="エルフ", opponent_clan="ロイヤル")
    log.log_action(
        m1,
        Action(
            turn=3, player=Player.SELF, action_type=ActionType.PLAY_CARD, card_id="c1",
            context={"turn": 3, "self_pp": 3, "self_board_count": 1, "opponent_board_count": 2},
        ),
    )
    m2 = log.start_match(self_clan="エルフ", opponent_clan="ロイヤル")
    log.log_action(
        m2,
        Action(
            turn=5, player=Player.SELF, action_type=ActionType.PLAY_CARD, card_id="c1",
            context={"turn": 5, "self_pp": 5, "self_board_count": 3, "opponent_board_count": 0},
        ),
    )

    situations = log.card_play_situations("c1", Player.SELF)
    assert len(situations) == 2
    assert situations[0]["turn"] == 3

    summary = log.card_play_context_summary("c1", Player.SELF, opponent_clan="ロイヤル")
    assert summary["samples"] == 2
    assert summary["avg_turn"] == 4.0
    assert summary["avg_pp"] == 4.0
    assert summary["avg_own_board_count"] == 2.0
    assert summary["avg_opponent_board_count"] == 1.0

    log.close()


def test_card_play_context_summary_none_without_records(tmp_path):
    log = MatchLog(tmp_path / "matches.db")
    assert log.card_play_context_summary("nope", Player.SELF) is None
    log.close()


def test_migration_adds_context_column_to_old_db(tmp_path):
    import sqlite3

    db_path = tmp_path / "old.db"
    # context カラムが無い旧スキーマを手で作る
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """CREATE TABLE matches (id INTEGER PRIMARY KEY AUTOINCREMENT, started_at REAL NOT NULL,
               ended_at REAL, self_clan TEXT, opponent_clan TEXT, result TEXT);
           CREATE TABLE actions (id INTEGER PRIMARY KEY AUTOINCREMENT, match_id INTEGER NOT NULL,
               turn INTEGER NOT NULL, player TEXT NOT NULL, action_type TEXT NOT NULL,
               card_id TEXT, card_name TEXT, detail TEXT, timestamp REAL NOT NULL);"""
    )
    conn.commit()
    conn.close()

    log = MatchLog(db_path)  # マイグレーションが走る
    cols = {row[1] for row in log._conn.execute("PRAGMA table_info(actions)").fetchall()}
    assert "context" in cols

    m = log.start_match(self_clan="エルフ", opponent_clan="ロイヤル")
    log.log_action(
        m, Action(turn=1, player=Player.SELF, action_type=ActionType.PLAY_CARD, card_id="c1", context={"turn": 1})
    )
    assert len(log.card_play_situations("c1", Player.SELF)) == 1
    log.close()


def _play(log, match_id, turn, card_id):
    log.log_action(
        match_id,
        Action(turn=turn, player=Player.OPPONENT, action_type=ActionType.PLAY_CARD, card_id=card_id),
    )


def test_card_play_probability_by_turn_conditional(tmp_path):
    log = MatchLog(tmp_path / "matches.db")

    # 3試合すべてがターン6に到達。うち2試合でターン6にcardXを出した -> 66%
    for i in range(3):
        m = log.start_match(self_clan="エルフ", opponent_clan="ロイヤル")
        _play(log, m, 6, "x" if i < 2 else "other")  # 全試合ターン6到達、2試合でxを出す
        log.end_match(m, "win" if i == 0 else "loss")

    rows = log.card_play_probability_by_turn("x", Player.OPPONENT, "ロイヤル")
    by_turn = {t: (played, reached, prob) for t, played, reached, prob in rows}
    # ターン6: xを出したのは2試合 / 到達3試合
    assert by_turn[6][0] == 2
    assert by_turn[6][1] == 3
    assert abs(by_turn[6][2] - 2 / 3) < 1e-9

    log.close()


def test_card_play_probability_filters_by_result(tmp_path):
    log = MatchLog(tmp_path / "matches.db")

    m1 = log.start_match(self_clan="エルフ", opponent_clan="ロイヤル")
    _play(log, m1, 3, "x")
    log.end_match(m1, "win")
    m2 = log.start_match(self_clan="エルフ", opponent_clan="ロイヤル")
    _play(log, m2, 3, "x")
    log.end_match(m2, "loss")

    win_rows = log.card_play_probability_by_turn("x", Player.OPPONENT, "ロイヤル", result="win")
    win_by_turn = {t: (played, reached) for t, played, reached, _ in win_rows}
    assert win_by_turn[3] == (1, 1)  # 勝ち試合は1つ、そこで出している

    log.close()


def test_card_play_probability_filters_by_first_player(tmp_path):
    log = MatchLog(tmp_path / "matches.db")

    m1 = log.start_match(self_clan="エルフ", opponent_clan="ロイヤル")
    log.set_first_player(m1, "opponent")
    _play(log, m1, 2, "x")
    log.end_match(m1, "win")
    m2 = log.start_match(self_clan="エルフ", opponent_clan="ロイヤル")
    log.set_first_player(m2, "self")
    _play(log, m2, 2, "x")
    log.end_match(m2, "loss")

    rows = log.card_play_probability_by_turn("x", Player.OPPONENT, "ロイヤル", first_player="opponent")
    by_turn = {t: (played, reached) for t, played, reached, _ in rows}
    assert by_turn[2] == (1, 1)  # 相手先攻の試合は1つ

    log.close()


def test_set_first_player_does_not_overwrite(tmp_path):
    log = MatchLog(tmp_path / "matches.db")
    m = log.start_match(self_clan="エルフ", opponent_clan="ロイヤル")
    log.set_first_player(m, "opponent")
    log.set_first_player(m, "self")  # 2回目は無視される
    row = log._conn.execute("SELECT first_player FROM matches WHERE id = ?", (m,)).fetchone()
    assert row[0] == "opponent"
    log.close()


def test_self_card_pool_returns_self_plays_only(tmp_path):
    log = MatchLog(tmp_path / "matches.db")
    m = log.start_match(self_clan="エルフ", opponent_clan="ロイヤル")
    log.log_action(m, Action(turn=2, player=Player.SELF, action_type=ActionType.PLAY_CARD, card_id="mine"))
    log.log_action(m, Action(turn=3, player=Player.OPPONENT, action_type=ActionType.PLAY_CARD, card_id="theirs"))
    log.end_match(m, "win")

    self_pool = dict(log.self_card_pool("ロイヤル"))
    opp_pool = dict(log.opponent_card_pool("ロイヤル"))
    assert "mine" in self_pool and "theirs" not in self_pool
    assert "theirs" in opp_pool and "mine" not in opp_pool
    log.close()
