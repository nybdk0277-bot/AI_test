"""手札・盤面のように等間隔に並ぶカード枠を、少数のサンプル矩形から自動補完する.

画面上のカードをCVで自動検出する方式(誤検出のリスクが高い)ではなく、
ユーザーが先頭の数枚だけ手動でドラッグ指定し、その間隔から残りを
外挿するシンプルな方式。手札9枚・盤面7枚を全部ドラッグする手間を省ける。
"""
from __future__ import annotations

Rect = tuple[int, int, int, int]


def interpolate_row(rects: list[Rect], count: int) -> list[Rect]:
    """既存の2つ以上の矩形から等間隔配置を推定し、count個の矩形列を生成する.

    rects[0]の位置・サイズを起点に、連続する矩形間の移動量(dx, dy)の平均を
    間隔とみなして伸長する。3枚以上サンプルがあれば平均を取るぶん精度が上がる。
    """
    if len(rects) < 2:
        raise ValueError("interpolate_row には少なくとも2つの基準矩形が必要です")
    if count < 1:
        raise ValueError("count は1以上である必要があります")

    x0, y0, w0, h0 = rects[0]
    deltas = [(rects[i][0] - rects[i - 1][0], rects[i][1] - rects[i - 1][1]) for i in range(1, len(rects))]
    avg_dx = sum(d[0] for d in deltas) / len(deltas)
    avg_dy = sum(d[1] for d in deltas) / len(deltas)

    return [(round(x0 + avg_dx * i), round(y0 + avg_dy * i), w0, h0) for i in range(count)]
