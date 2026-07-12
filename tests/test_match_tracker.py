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


def test_event_detector_detects_super_evolve_from_sep_decrease():
    # 進化ポイント(黄色)と超進化ポイント(紫)は別カウンター。SEPの減少=超進化。
    detector = EventDetector()
    detector.update(
        turn=8, self_hand_ids=[], self_board_ids=[], opponent_board_ids=[], self_sep=1, opponent_sep=1
    )

    actions = detector.update(
        turn=8, self_hand_ids=[], self_board_ids=[], opponent_board_ids=[], self_sep=1, opponent_sep=0
    )

    assert len(actions) == 1
    assert actions[0].player == Player.OPPONENT
    assert actions[0].action_type == ActionType.SUPER_EVOLVE


def test_event_detector_ep_drop_of_two_is_still_plain_evolve():
    # EPが2減ってもそれは進化(超進化はSEP側で検出する)。1回分のアクションとして記録。
    detector = EventDetector()
    detector.update(turn=8, self_hand_ids=[], self_board_ids=[], opponent_board_ids=[], self_ep=2, opponent_ep=2)

    actions = detector.update(
        turn=8, self_hand_ids=[], self_board_ids=[], opponent_board_ids=[], self_ep=0, opponent_ep=2
    )

    assert len(actions) == 1
    assert actions[0].player == Player.SELF
    assert actions[0].action_type == ActionType.EVOLVE


def test_event_detector_detects_evolve_and_super_evolve_independently():
    detector = EventDetector()
    detector.update(
        turn=6,
        self_hand_ids=[],
        self_board_ids=[],
        opponent_board_ids=[],
        self_ep=2,
        self_sep=1,
    )

    actions = detector.update(
        turn=6,
        self_hand_ids=[],
        self_board_ids=[],
        opponent_board_ids=[],
        self_ep=1,
        self_sep=0,
    )

    types = {a.action_type for a in actions}
    assert types == {ActionType.EVOLVE, ActionType.SUPER_EVOLVE}
    assert all(a.player == Player.SELF for a in actions)


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


def test_event_detector_detects_unit_destroyed_when_card_leaves_board():
    detector = EventDetector()
    detector.update(turn=2, self_hand_ids=[], self_board_ids=["A"], opponent_board_ids=["X"])

    actions = detector.update(turn=3, self_hand_ids=[], self_board_ids=[], opponent_board_ids=["X"])

    assert len(actions) == 1
    assert actions[0].player == Player.SELF
    assert actions[0].card_id == "A"
    assert actions[0].action_type == ActionType.UNIT_DESTROYED


def test_event_detector_detects_life_change_for_both_players():
    detector = EventDetector()
    detector.update(
        turn=1, self_hand_ids=[], self_board_ids=[], opponent_board_ids=[], self_life=20, opponent_life=20
    )

    actions = detector.update(
        turn=2, self_hand_ids=[], self_board_ids=[], opponent_board_ids=[], self_life=17, opponent_life=22
    )

    by_player = {a.player: a for a in actions}
    assert len(actions) == 2
    assert by_player[Player.SELF].action_type == ActionType.LIFE_CHANGE
    assert "-3" in by_player[Player.SELF].detail
    assert by_player[Player.OPPONENT].action_type == ActionType.LIFE_CHANGE
    assert "+2" in by_player[Player.OPPONENT].detail


def test_event_detector_ignores_life_change_on_first_observation():
    detector = EventDetector()

    actions = detector.update(
        turn=1, self_hand_ids=[], self_board_ids=[], opponent_board_ids=[], self_life=20, opponent_life=20
    )

    assert actions == []


def test_event_detector_detects_end_turn_when_turn_changes():
    detector = EventDetector()
    detector.update(
        turn=1, self_hand_ids=[], self_board_ids=[], opponent_board_ids=[], active_player=Player.SELF
    )

    actions = detector.update(
        turn=2, self_hand_ids=[], self_board_ids=[], opponent_board_ids=[], active_player=Player.OPPONENT
    )

    end_turn_actions = [a for a in actions if a.action_type == ActionType.END_TURN]
    assert len(end_turn_actions) == 1
    assert end_turn_actions[0].turn == 1
    assert end_turn_actions[0].player == Player.SELF  # ターン1で手番だった側が終了したとみなす


def test_event_detector_no_end_turn_without_active_player_info():
    detector = EventDetector()
    detector.update(turn=1, self_hand_ids=[], self_board_ids=[], opponent_board_ids=[])

    actions = detector.update(turn=2, self_hand_ids=[], self_board_ids=[], opponent_board_ids=[])

    assert not any(a.action_type == ActionType.END_TURN for a in actions)


def test_match_tracker_set_extra_pp_and_ep():
    tracker = MatchTracker()

    tracker.set_extra_pp(2)
    assert tracker.state.self_extra_pp == 2

    tracker.set_ep(2, 1)
    assert tracker.state.self_ep == 2
    assert tracker.state.opponent_ep == 1

    tracker.set_sep(1, 0)
    assert tracker.state.self_sep == 1
    assert tracker.state.opponent_sep == 0


def test_match_tracker_set_battle_log_counts_keeps_previous_on_none():
    tracker = MatchTracker()

    tracker.set_battle_log_counts(
        combo_count=2,
        self_hand_count=6,
        opponent_hand_count=5,
        self_deck_count=29,
        opponent_deck_count=30,
        self_cemetery_count=7,
        opponent_cemetery_count=3,
    )
    assert tracker.state.combo_count == 2
    assert tracker.state.self_hand_count == 6
    assert tracker.state.opponent_hand_count == 5
    assert tracker.state.self_deck_count == 29
    assert tracker.state.opponent_deck_count == 30
    assert tracker.state.self_cemetery_count == 7
    assert tracker.state.opponent_cemetery_count == 3

    # 一部だけ更新し、Noneの値は既存値を保持する(OCR失敗で値が消えない)
    tracker.set_battle_log_counts(self_cemetery_count=8)
    assert tracker.state.self_cemetery_count == 8
    assert tracker.state.combo_count == 2
    assert tracker.state.self_hand_count == 6


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
