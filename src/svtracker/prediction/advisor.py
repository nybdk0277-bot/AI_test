"""現在の対戦状況から「最善に近い」行動を提案するヒューリスティックアドバイザー.

完全なゲーム木探索ではなく、以下の分かりやすいルールに基づく:
  1. リーサル(相手を倒しきれるか)の検出
  2. 損をしない/得するフォロワートレードの検出
  3. 手札を使ってPPを無駄なく使う組み合わせの提案
"""
from __future__ import annotations

from dataclasses import dataclass

from svtracker.cards.models import Card
from svtracker.game.match_tracker import MatchTracker


@dataclass
class Recommendation:
    title: str
    detail: str
    priority: int  # 小さいほど優先度が高い


def recommend_actions(tracker: MatchTracker, hand: list[Card]) -> list[Recommendation]:
    state = tracker.state
    recs: list[Recommendation] = []

    attackable_power = sum(u.atk for u in state.self_board if u.can_attack)
    if state.opponent_life > 0 and attackable_power >= state.opponent_life:
        recs.append(
            Recommendation(
                title="リーサルの可能性",
                detail=(
                    f"攻撃可能な盤面の合計打点 {attackable_power} が"
                    f"相手ライフ {state.opponent_life} 以上です。ブロッカーの有無を確認し、"
                    "全体攻撃で勝利できるか確認してください。"
                ),
                priority=0,
            )
        )

    for unit in state.self_board:
        if not unit.can_attack:
            continue
        for enemy in state.opponent_board:
            kills_enemy = unit.atk >= enemy.hp
            survives = enemy.atk < unit.hp
            if kills_enemy and survives:
                recs.append(
                    Recommendation(
                        title=f"有利トレード: {unit.name} → {enemy.name}",
                        detail=(
                            f"{unit.name}(ATK{unit.atk}/HP{unit.hp}) は "
                            f"{enemy.name}(ATK{enemy.atk}/HP{enemy.hp}) を破壊しつつ生き残れます。"
                        ),
                        priority=1,
                    )
                )
            elif kills_enemy and not survives and enemy.atk >= unit.atk:
                # 相打ちだが自分の方が高コスト損な場合など、注意喚起のみ
                recs.append(
                    Recommendation(
                        title=f"相打ち注意: {unit.name} ⇔ {enemy.name}",
                        detail=f"{unit.name} で攻撃すると相打ちになります。他に選択肢がないか検討してください。",
                        priority=3,
                    )
                )

    spendable_pp = state.self_pp + state.self_extra_pp
    playable = [c for c in hand if c.cost <= spendable_pp]
    combo = _best_pp_combo(playable, spendable_pp)
    if combo:
        names = ", ".join(c.name for c in combo)
        used = sum(c.cost for c in combo)
        extra_used = max(0, used - state.self_pp)
        if extra_used > 0:
            detail = (
                f"{names} をプレイすると PP {used} を使い切れます"
                f"(通常PP {state.self_pp} に加えエクストラPPを{extra_used}消費)。"
            )
        else:
            detail = f"{names} をプレイすると PP {used}/{state.self_pp} を無駄なく使えます。"
        recs.append(Recommendation(title="PP消費の提案", detail=detail, priority=2))

    if state.self_ep > 0 and state.self_board:
        recs.append(
            Recommendation(
                title="進化ポイントが残っています",
                detail=(
                    f"進化ポイントが{state.self_ep}残っています。攻撃力を上げたい/守りたい"
                    "フォロワーへの進化を検討してください。"
                ),
                priority=2,
            )
        )

    recs.sort(key=lambda r: r.priority)
    return recs


def _best_pp_combo(cards: list[Card], pp: int) -> list[Card]:
    """0/1ナップサック: PP以内で消費コスト合計を最大化(タイブレークは枚数優先)する組み合わせ."""
    if pp <= 0 or not cards:
        return []

    # best[budget] = (used_cost, card_count, card_indices)
    best: dict[int, tuple[int, int, list[int]]] = {0: (0, 0, [])}
    for idx, card in enumerate(cards):
        for budget in list(best.keys()):
            new_budget = budget + card.cost
            if new_budget > pp:
                continue
            used, count, combo = best[budget]
            candidate = (used + card.cost, count + 1, combo + [idx])
            existing = best.get(new_budget)
            if existing is None or (candidate[0], candidate[1]) > (existing[0], existing[1]):
                best[new_budget] = candidate

    best_budget = max(best, key=lambda b: (best[b][0], best[b][1]))
    return [cards[i] for i in best[best_budget][2]]
