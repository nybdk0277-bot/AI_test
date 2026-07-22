"""キャリブレーションのプリセット(割合ベース)と、キャプチャ画面サイズへの自動スケール.

ゲームUIのレイアウトは解像度ごとにほぼ固定なので、1920x1080の実対戦動画から採った座標を
「画面サイズに対する割合(0.0-1.0)」で持っておき、実際のキャプチャ画面サイズに合わせて
スケールすれば、手作業のドラッグ無しで一括適用できる。フルスクリーン1920x1080ならそのまま、
別解像度でも同じ縦横比なら比率でフィットする。

注意: PP/ライフ/ターン/各カウンタ/クレスト/進化ピップなどの固定UIは位置が安定しているため
プリセットが有効。一方カード枠(手札・盤面)はゲーム側がフォロワーを中央寄せで再配置し、
手札は扇状に傾くため、プリセットはあくまで初期値。実際に合わせるにはキャリブレーションで
微調整すること。
"""
from __future__ import annotations

from svtracker.capture.screen_capture import RegionSet

PRESET_BASE_WIDTH = 1920
PRESET_BASE_HEIGHT = 1080

# 1920x1080基準のピクセル座標。矩形は [x, y, w, h]、点は [x, y]、複数枠はそのリスト。
_PRESET_1080P: dict = {
    "self_hand": [
        [350, 890, 140, 150],
        [540, 890, 140, 150],
        [730, 890, 140, 150],
        [920, 890, 140, 150],
        [1110, 890, 140, 150],
    ],
    "self_board": [
        [560, 480, 120, 150],
        [700, 480, 120, 150],
        [840, 480, 120, 150],
        [980, 480, 120, 150],
        [1120, 480, 120, 150],
    ],
    "opponent_board": [
        [560, 250, 110, 140],
        [690, 250, 110, 140],
        [820, 250, 110, 140],
        [950, 250, 110, 140],
        [1080, 250, 110, 140],
    ],
    "self_pp": [1660, 630, 210, 55],
    "opponent_pp": [1660, 290, 210, 55],
    "self_life": [1150, 800, 90, 60],
    "opponent_life": [1120, 40, 80, 60],
    "combo_count": [70, 930, 60, 50],
    "self_hand_count": [60, 1000, 45, 40],
    "self_deck_count": [140, 1000, 45, 40],
    "self_cemetery_count": [230, 1000, 45, 40],
    "opponent_hand_count": [1640, 55, 45, 40],
    "opponent_deck_count": [1720, 55, 45, 40],
    "opponent_cemetery_count": [1810, 55, 45, 40],
    "self_ep_pips": [[810, 784, 20, 22], [842, 784, 20, 22]],
    "opponent_ep_pips": [[800, 168, 20, 24], [830, 168, 20, 24]],
    "self_sep_pips": [[1050, 784, 20, 22], [1080, 784, 20, 22]],
    "opponent_sep_pips": [[1055, 168, 20, 24], [1085, 168, 20, 24]],
    "self_crest_slots": [[790, 730, 70, 70], [1030, 730, 70, 70]],
    "opponent_crest_slots": [
        [1290, 38, 70, 70],
        [1392, 28, 80, 80],
        [1340, 120, 80, 80],
        [1448, 120, 80, 80],
    ],
    # プレイ表示: カードをプレイすると画面「中央」に大きく正立表示される「完全なカード」。
    # 自分・相手どちらのプレイでも同じ中央位置に出るので枠は1つにまとめ、手番
    # (active_player_pixel)で「今出したのは自分か相手か」を判定する。実対戦の
    # フル画面(1920x1080)で中央のカードは概ね x:0.375-0.625 / y:0.16-0.75 に出る。
    "play_reveal": [720, 173, 480, 640],
    # 手番判定ピクセル: 右側の「ターン終了 / ENEMY TURN」ボタン中央(色が青⇔赤で変わる)
    "active_player_pixel": [1740, 470],
}


def _scale_value(value, sx: float, sy: float):
    """[x,y,w,h] / [x,y] / それらのリストを、縦横それぞれの倍率でスケールする."""
    if isinstance(value, list) and value and isinstance(value[0], list):
        return [_scale_value(v, sx, sy) for v in value]
    if len(value) == 4:
        x, y, w, h = value
        return [round(x * sx), round(y * sy), round(w * sx), round(h * sy)]
    if len(value) == 2:
        x, y = value
        return [round(x * sx), round(y * sy)]
    return value


def preset_region_set(capture_width: int, capture_height: int) -> RegionSet:
    """指定したキャプチャ画面サイズに合わせてスケールしたプリセットのRegionSetを返す."""
    sx = capture_width / PRESET_BASE_WIDTH
    sy = capture_height / PRESET_BASE_HEIGHT
    scaled = {name: _scale_value(value, sx, sy) for name, value in _PRESET_1080P.items()}
    return RegionSet(scaled)
