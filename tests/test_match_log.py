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
