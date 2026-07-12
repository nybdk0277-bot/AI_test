from svtracker.capture.stability import StableValue


def test_single_frame_spike_is_ignored():
    stable = StableValue(required=2)
    stable.update(20)
    stable.update(20)
    assert stable.value == 20

    # 1フレームだけの誤読(204)は確定値を動かさない
    assert stable.update(204) == 20
    assert stable.update(20) == 20
    assert stable.value == 20


def test_change_confirmed_after_required_consecutive_frames():
    stable = StableValue(required=2)
    stable.update(20)
    stable.update(20)

    assert stable.update(17) == 20  # 1回目はまだ確定しない
    assert stable.update(17) == 17  # 2回連続で確定


def test_none_observation_does_not_reset_candidate():
    stable = StableValue(required=2)
    stable.update(20)
    stable.update(20)

    stable.update(17)
    assert stable.update(None) == 20  # 読めなかったフレームは保留
    assert stable.update(17) == 17  # 続けて同じ値が来れば確定


def test_alternating_noise_never_confirms():
    stable = StableValue(required=2)
    stable.update(0)
    stable.update(0)
    for _ in range(5):
        stable.update(1)
        stable.update(0)
    assert stable.value == 0


def test_works_with_tuples():
    stable = StableValue(required=2)
    stable.update((6, 9))
    assert stable.update((6, 9)) == (6, 9)
    stable.update((1, 1))
    assert stable.value == (6, 9)
