from svtracker.game.event_detector import EventDetector
from svtracker.game.match_tracker import MatchTracker
from svtracker.game.models import Action, ActionType, Player


def test_advance_turn_increments_and_tracks_active_player():
    tracker = MatchTracker(self_clan="エルフ", opponent_clan="ロイヤル")
    assert tracker.current_turn == 0

    tracker.advance_turn(Player.SELF)
    assert tracker.current_turn == 1
    assert tracker.state.active_player == Player.SELF

    tracker.advance_turn(Player.OPPONENT)
    assert tracker.current_turn == 2
    assert tracker.state.active_player == Player.OPPONENT


def test_sync_turn_updates_only_on_change():
    tracker = MatchTracker()

    changed = tracker.sync_turn(1, Player.SELF)
    assert changed is True
    assert tracker.current_turn == 1
    assert tracker.state.active_player == Player.SELF

    changed = tracker.sync_turn(1, Player.SELF)
    assert changed is False
    assert tracker.current_turn == 1

    changed = tracker.sync_turn(2, Player.OPPONENT)
    assert changed is True
    assert tracker.current_turn == 2
    assert tracker.state.active_player == Player.OPPONENT


def test_record_action_tracks_opponent_revealed_cards():
    tracker = MatchTracker()
    tracker.record_action(Action(turn=1, player=Player.OPPONENT, action_type=ActionType.PLAY_CARD, card_id="c1"))
    tracker.record_action(Action(turn=2, player=Player.OPPONENT, action_type=ActionType.PLAY_CARD, card_id="c2"))
    tracker.record_action(Action(turn=2, player=Player.SELF, action_type=ActionType.PLAY_CARD, card_id="c3"))

    assert tracker.state.opponent_revealed_card_ids == {"c1", "c2"}
    assert len(tracker.history(Player.OPPONENT)) == 2
    assert len(tracker.history(Player.SELF)) == 1
    assert len(tracker.history()) == 3


def test_event_detector_detects_self_play_from_hand_to_board():
    detector = EventDetector()

    # 初期状態: 手札にAとBがあり、盤面は空
    actions = detector.update(turn=1, self_hand_ids=["A", "B"], self_board_ids=[], opponent_board_ids=[])
    assert actions == []

    # Aが手札から消え、盤面に出現 -> プレイと判定されるべき
    actions = detector.update(turn=1, self_hand_ids=["B"], self_board_ids=["A"], opponent_board_ids=[])
    assert len(actions) == 1
    assert actions[0].player == Player.SELF
    assert actions[0].card_id == "A"
    assert actions[0].action_type == ActionType.PLAY_CARD


def test_event_detector_detects_opponent_play_from_board_diff():
    detector = EventDetector()
    detector.update(turn=1, self_hand_ids=[], self_board_ids=[], opponent_board_ids=[])

    actions = detector.update(turn=1, self_hand_ids=[], self_board_ids=[], opponent_board_ids=["X"])

    assert len(actions) == 1
    assert actions[0].player == Player.OPPONENT
    assert actions[0].card_id == "X"


def test_event_detector_ignores_unchanged_state():
    detector = EventDetector()
    detector.update(turn=1, self_hand_ids=["A"], self_board_ids=["B"], opponent_board_ids=["X"])

    actions = detector.update(turn=1, self_hand_ids=["A"], self_board_ids=["B"], opponent_board_ids=["X"])

    assert actions == []
