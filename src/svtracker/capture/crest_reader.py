"""クレスト枠(リーダー横の丸スロット)の占有判定.

空のスロットは暗く模様の少ない円、クレストが入るとカラフルなアイコン(+カウントダウン数字)が
表示される。実対戦動画のフレームから確認したこの性質を使い、切り出したスロット画像の
「明るさ」と「色のばらつき」で埋まっているかを判定する。アイコンの種類までは特定しない
(クレストのアイコン画像一覧を入手できていないため)。
"""
from __future__ import annotations

from PIL import Image, ImageStat

# 実動画のフレームから採った実測値: 占有スロット=明るさ117/ばらつき62、
# 空スロット=明るさ45〜67/ばらつき15〜18。空スロットは半透明で背後の盤面が
# 透けるため、派手な演出中は数値が上がる。実戦で誤検出が出たため、閾値は
# 実測の中間よりも占有側に寄せてある。それでも誤判定が出る場合はここを調整すること。
MIN_OCCUPIED_BRIGHTNESS = 85.0  # グレースケール平均(0-255)
MIN_OCCUPIED_STDDEV = 42.0  # グレースケール標準偏差(のっぺりした空円は低い)


def slot_is_occupied(slot_image: Image.Image) -> bool:
    """クレストスロットの切り出し画像が「埋まっている」とみなせるか判定する."""
    stat = ImageStat.Stat(slot_image.convert("L"))
    brightness = stat.mean[0]
    stddev = stat.stddev[0]
    return brightness >= MIN_OCCUPIED_BRIGHTNESS and stddev >= MIN_OCCUPIED_STDDEV


def count_occupied_slots(slot_images: list[Image.Image]) -> int:
    return sum(1 for img in slot_images if slot_is_occupied(img))
