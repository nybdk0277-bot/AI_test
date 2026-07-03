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


def test_event_detector_detects_evolve_from_ep_decrease():
    detector = EventDetector()
    detector.update(turn=4, self_hand_ids=[], self_board_ids=[], opponent_board_ids=[], self_ep=2, opponent_ep=2)

    actions = detector.update(
        turn=4, self_hand_ids=[], self_board_ids=[], opponent_board_ids=[], self_ep=1, opponent_ep=2
    )

    assert len(actions) == 1
    assert actions[0].player == Player.SELF
    assert actions[0].action_type == ActionType.EVOLVE


def test_event_detector_detects_super_evolve_from_ep_drop_of_two():
    detector = EventDetector()
    detector.update(turn=8, self_hand_ids=[], self_board_ids=[], opponent_board_ids=[], self_ep=0, opponent_ep=2)

    actions = detector.update(
        turn=8, self_hand_ids=[], self_board_ids=[], opponent_board_ids=[], self_ep=0, opponent_ep=0
    )

    assert len(actions) == 1
    assert actions[0].player == Player.OPPONENT
    assert actions[0].action_type == ActionType.SUPER_EVOLVE


def test_event_detector_ignores_ep_increase_and_missing_observations():
    detector = EventDetector()
    detector.update(turn=1, self_hand_ids=[], self_board_ids=[], opponent_board_ids=[], self_ep=0, opponent_ep=0)

    # EP増加(ターン開始時の付与)は進化として検出しない
    actions = detector.update(
        turn=2, self_hand_ids=[], self_board_ids=[], opponent_board_ids=[], self_ep=2, opponent_ep=0
    )
    assert actions == []

    # 観測できない(None)フレームは無視して基準値を保持する
    actions = detector.update(turn=3, self_hand_ids=[], self_board_ids=[], opponent_board_ids=[])
    assert actions == []


def test_match_tracker_set_extra_pp_and_ep():
    tracker = MatchTracker()

    tracker.set_extra_pp(2)
    assert tracker.state.self_extra_pp == 2

    tracker.set_ep(2, 1)
    assert tracker.state.self_ep == 2
    assert tracker.state.opponent_ep == 1


def test_infer_clan_ignores_neutral_and_sets_once():
    tracker = MatchTracker()

    assert tracker.infer_clan(Player.SELF, "ニュートラル") is False
    assert tracker.state.self_clan == ""

    assert tracker.infer_clan(Player.SELF, "エルフ") is True
    assert tracker.state.self_clan == "エルフ"

    # 一度判明したら別のクラスが来ても上書きしない(誤認識対策)
    assert tracker.infer_clan(Player.SELF, "ロイヤル") is False
    assert tracker.state.self_clan == "エルフ"


def test_infer_clan_does_not_overwrite_manually_provided_clan():
    tracker = MatchTracker(self_clan="ドラゴン")

    assert tracker.infer_clan(Player.SELF, "ウィッチ") is False
    assert tracker.state.self_clan == "ドラゴン"


def test_infer_clan_tracks_self_and_opponent_independently():
    tracker = MatchTracker()

    assert tracker.infer_clan(Player.OPPONENT, "ビショップ") is True
    assert tracker.state.opponent_clan == "ビショップ"
    assert tracker.state.self_clan == ""
