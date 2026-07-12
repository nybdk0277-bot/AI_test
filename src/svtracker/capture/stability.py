"""1フレーム限りの誤読(OCRノイズ・演出の重なり)を弾くための安定化フィルタ.

画面認識は毎フレーム完璧ではなく、カーソルや演出がピップ/カウンタ領域に重なった
一瞬だけ値が変わって見えることがある。実戦ログで「ライフ+184」「誰も使っていない
クレストの増減」「進化の誤検出連発」が観測されたため、値の変化は「同じ値が連続して
規定回数観測されたときだけ」確定させる。
"""
from __future__ import annotations

from typing import Hashable, Optional


class StableValue:
    """同じ観測値が required 回連続したときだけ確定値を更新するデバウンサ."""

    def __init__(self, required: int = 2):
        self.required = required
        self._confirmed: Optional[Hashable] = None
        self._candidate: Optional[Hashable] = None
        self._candidate_count = 0

    @property
    def value(self) -> Optional[Hashable]:
        return self._confirmed

    def update(self, observed: Optional[Hashable]) -> Optional[Hashable]:
        """観測値を渡し、現在の確定値を返す(未確定のうちは None)。

        観測できなかったフレーム(None)は候補のカウントをリセットせず保留にする
        (1フレーム読めなかっただけで確定までやり直しにならないように)。
        """
        if observed is None:
            return self._confirmed
        if observed == self._confirmed:
            self._candidate = None
            self._candidate_count = 0
            return self._confirmed
        if observed == self._candidate:
            self._candidate_count += 1
        else:
            self._candidate = observed
            self._candidate_count = 1
        if self._candidate_count >= self.required:
            self._confirmed = self._candidate
            self._candidate = None
            self._candidate_count = 0
        return self._confirmed
