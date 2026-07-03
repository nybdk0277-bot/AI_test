from pathlib import Path

from svtracker.cards.card_database import CardDatabase
from svtracker.cards.models import Card
from svtracker.game.match_tracker import MatchTracker
from svtracker.game.models import Action, ActionType, Player
from svtracker.prediction.predictor import predict_opponent_next_actions
from svtracker.storage.match_log import MatchLog


def build_database() -> CardDatabase:
    db = CardDatabase()
    db.add(Card(card_id="r1", name="よく使われるロイヤルカード", clan="ロイヤル", cost=3, card_type="フォロワー"))
    db.add(Card(card_id="r2", name="めったに使われないロイヤルカード", clan="ロイヤル", cost=3, card_type="フォロワー"))
    db.add(Card(card_id="r3", name="コストが高すぎるカード", clan="ロイヤル", cost=9, card_type="フォロワー"))
    db.add(Card(card_id="n1", name="ニュートラルカード", clan="ニュートラル", cost=3, card_type="フォロワー"))
    db.add(Card(card_id="n0", name="安いニュートラルカード", clan="ニュートラル", cost=1, card_type="フォロワー"))
    return db


def seed_history(db_path: Path, times_played: int) -> None:
    log = MatchLog(db_path)
    for _ in range(times_played):
        match_id = log.start_match(self_clan="エルフ", opponent_clan="ロイヤル")
        log.log_action(
            match_id,
            Action(turn=3, player=Player.OPPONENT, action_type=ActionType.PLAY_CARD, card_id="r1"),
        )
        log.end_match(match_id, "loss")
    log.close()


def test_predictor_ranks_frequently_played_card_higher(tmp_path):
    db_path = tmp_path / "matches.db"
    seed_history(db_path, times_played=4)

    database = build_database()
    tracker = MatchTracker(self_clan="エルフ", opponent_clan="ロイヤル")
    tracker.advance_turn(Player.OPPONENT)
    tracker.advance_turn(Player.SELF)
    tracker.advance_turn(Player.OPPONENT)  # turn=3

    with MatchLog(db_path) as log:
        predictions = predict_opponent_next_actions(tracker, database, log, top_k=5)

    assert predictions, "候補が返らなかった"
    assert predictions[0].card.card_id == "r1"
    # コストオーバーのカードは候補にすら入らない
    assert all(p.card.card_id != "r3" for p in predictions)


def test_predictor_without_history_falls_back_to_curve_and_novelty(tmp_path):
    database = build_database()
    tracker = MatchTracker(self_clan="エルフ", opponent_clan="ロイヤル")
    tracker.advance_turn(Player.OPPONENT)  # turn=1

    predictions = predict_opponent_next_actions(tracker, database, match_log=None, top_k=5)

    # turn=1 なのでコスト3のカードは(コスト超過で)候補から外れているはず
    assert all(p.card.cost <= 1 for p in predictions)
