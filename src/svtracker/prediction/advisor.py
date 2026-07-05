"""現在の対戦状況から「最善に近い」行動を提案するヒューリスティックアドバイザー.

完全なゲーム木探索ではなく、以下の分かりやすいルールに基づく:
  1. リーサル(相手を倒しきれるか)の検出
  2. 相手目線のリーサル(このターン凌がないと次に倒されるか)の警戒
  3. 損をしない/得するフォロワートレードの検出
  4. 手札を使ってPPを無駄なく使う組み合わせの提案(PP回復カードによる上乗せも考慮)
  5. (対戦記録が十分あれば)過去にプレイして勝率が高かったカードの提示
  6. PP上限を増やすカード・進化ポイントを回復するカードの優先プレイ提案
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from svtracker.cards.models import Card
from svtracker.game.match_tracker import MatchTracker
from svtracker.storage.match_log import MatchLog, WinStats

# 勝率提案を出すために必要な最低対戦数(サンプルが少なすぎるとノイズが大きいため)。
MIN_WIN_RATE_SAMPLES = 3


@dataclass
class Recommendation:
    title: str
    detail: str
    priority: int  # 小さいほど優先度が高い


def recommend_actions(
    tracker: MatchTracker, hand: list[Card], match_log: Optional[MatchLog] = None
) -> list[Recommendation]:
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

    opponent_attackable_power = sum(u.atk for u in state.opponent_board if u.can_attack)
    if state.self_life > 0 and opponent_attackable_power >= state.self_life:
        recs.append(
            Recommendation(
                title="相手のリーサルに警戒",
                detail=(
                    f"相手の盤面の合計攻撃力 {opponent_attackable_power} が"
                    f"あなたのライフ {state.self_life} 以上です。次の相手ターンにリーサルされる"
                    "可能性があるため、ブロッカーとして残せるフォロワーを温存する、"
                    "除去やライフ回復の手段を優先するなど、リーサルケアを意識してください。"
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
    # PP回復カードで後から使えるPPが増える可能性を見込み、単純な cost <= spendable_pp
    # より緩い上限で候補を残す(実際にプレイできるかどうかは _best_pp_combo 側で判定する)。
    max_possible_pp = spendable_pp + sum(c.pp_recover for c in hand)
    playable = [c for c in hand if c.cost <= max_possible_pp]
    combo = _best_pp_combo(playable, spendable_pp)
    if combo:
        names = ", ".join(c.name for c in combo)
        used = sum(c.cost for c in combo)
        recovered = sum(c.pp_recover for c in combo)
        extra_used = max(0, used - recovered - state.self_pp)
        detail_parts = [f"{names} をプレイすると PP {used} 分を使えます"]
        notes = []
        if extra_used > 0:
            notes.append(f"エクストラPPを{extra_used}消費")
        if recovered > 0:
            notes.append(f"PP回復効果で{recovered}分を追加確保")
        if notes:
            detail_parts.append(f"({'、'.join(notes)})")
        recs.append(Recommendation(title="PP消費の提案", detail="".join(detail_parts) + "。", priority=2))

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

    pp_boost_cards = [c for c in playable if c.max_pp_boost > 0]
    if pp_boost_cards:
        names = ", ".join(f"{c.name}(PP上限+{c.max_pp_boost})" for c in pp_boost_cards)
        recs.append(
            Recommendation(
                title="PP上限を増やせるカードがあります",
                detail=f"{names}。早めにプレイするほど以降のターンで有利になりやすいので優先を検討してください。",
                priority=1,
            )
        )

    if state.self_ep == 0 and state.self_board:
        ep_recover_cards = [c for c in playable if c.ep_recover > 0]
        if ep_recover_cards:
            names = ", ".join(f"{c.name}(EP+{c.ep_recover})" for c in ep_recover_cards)
            recs.append(
                Recommendation(
                    title="進化ポイントを回復できるカードがあります",
                    detail=f"{names}。進化を使い切っていても再度進化を検討できます。",
                    priority=2,
                )
            )

    if match_log is not None and state.self_clan and state.opponent_clan:
        best = _best_win_rate_card(match_log, state.self_clan, state.opponent_clan, playable)
        if best is not None:
            card, stats = best
            recs.append(
                Recommendation(
                    title=f"勝率の高いカード: {card.name}",
                    detail=(
                        f"{state.opponent_clan}相手に{card.name}をプレイした過去{stats.total}戦の"
                        f"勝率は{stats.win_rate:.0%}でした。優先してプレイを検討してください。"
                    ),
                    priority=1,
                )
            )

    recs.sort(key=lambda r: r.priority)
    return recs


def _best_win_rate_card(
    match_log: MatchLog, self_clan: str, opponent_clan: str, playable: list[Card]
) -> Optional[tuple[Card, WinStats]]:
    """現在プレイ可能な手札の中で、過去の勝率が最も高いカードを選ぶ.

    対戦数が MIN_WIN_RATE_SAMPLES 未満のカードはノイズが大きいため候補にしない。
    """
    best = None
    for card in playable:
        stats = match_log.card_win_rate(self_clan, opponent_clan, card.card_id)
        if stats.total < MIN_WIN_RATE_SAMPLES:
            continue
        if best is None or stats.win_rate > best[1].win_rate:
            best = (card, stats)
    return best


def _best_pp_combo(cards: list[Card], pp: int) -> list[Card]:
    """0/1ナップサック: PP以内で消費コスト合計を最大化(タイブレークは枚数優先)する組み合わせ.

    各カードの pp_recover(PP回復量)を「実質コスト = cost - pp_recover」として
    予算に加算することで、回復カードを絡めた分だけ多くプレイできる組み合わせも
    自然に候補になる(合計の実質コストが pp を超えなければ、回復分を他のカードに
    使い回せる、という近似。実際の回復タイミング/上限は考慮しない簡易モデル)。
    """
    if pp <= 0 or not cards:
        return []

    # best[budget] = (used_cost, card_count, card_indices)
    # budgetは実質コストの累計なので、回復量が大きいカードを含めると負になり得る。
    best: dict[int, tuple[int, int, list[int]]] = {0: (0, 0, [])}
    for idx, card in enumerate(cards):
        net_cost = card.cost - card.pp_recover
        for budget in list(best.keys()):
            new_budget = budget + net_cost
            if new_budget > pp:
                continue
            used, count, combo = best[budget]
            candidate = (used + card.cost, count + 1, combo + [idx])
            existing = best.get(new_budget)
            if existing is None or (candidate[0], candidate[1]) > (existing[0], existing[1]):
                best[new_budget] = candidate

    best_budget = max(best, key=lambda b: (best[b][0], best[b][1]))
    return [cards[i] for i in best[best_budget][2]]
