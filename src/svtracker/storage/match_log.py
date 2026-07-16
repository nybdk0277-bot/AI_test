"""対戦履歴の永続化(SQLite)と、予測エンジン向けの集計クエリ."""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from svtracker.game.models import Action, ActionType, Player

# end_match() の result に使う正規値。それ以外の文字列("unknown"等)は
# 勝率集計(WinStats)の対象から除外される。
RESULT_WIN = "win"
RESULT_LOSS = "loss"
_DECIDED_RESULTS = (RESULT_WIN, RESULT_LOSS)


@dataclass
class WinStats:
    wins: int
    losses: int

    @property
    def total(self) -> int:
        return self.wins + self.losses

    @property
    def win_rate(self) -> Optional[float]:
        if self.total == 0:
            return None
        return self.wins / self.total

SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at REAL NOT NULL,
    ended_at REAL,
    self_clan TEXT,
    opponent_clan TEXT,
    result TEXT,
    first_player TEXT
);

CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL REFERENCES matches(id),
    turn INTEGER NOT NULL,
    player TEXT NOT NULL,
    action_type TEXT NOT NULL,
    card_id TEXT,
    card_name TEXT,
    detail TEXT,
    timestamp REAL NOT NULL,
    context TEXT
);

CREATE INDEX IF NOT EXISTS idx_actions_match ON actions(match_id);
CREATE INDEX IF NOT EXISTS idx_actions_card_turn ON actions(card_id, turn);
"""


class MatchLog:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._conn = sqlite3.connect(str(db_path))
        self._conn.executescript(SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        """古いDB(新カラムが無い)を新スキーマへ追従させる."""
        with closing(self._conn.cursor()) as cur:
            action_cols = {row[1] for row in cur.execute("PRAGMA table_info(actions)").fetchall()}
            if "context" not in action_cols:
                cur.execute("ALTER TABLE actions ADD COLUMN context TEXT")
            match_cols = {row[1] for row in cur.execute("PRAGMA table_info(matches)").fetchall()}
            if "first_player" not in match_cols:
                cur.execute("ALTER TABLE matches ADD COLUMN first_player TEXT")

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "MatchLog":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def start_match(self, self_clan: str = "", opponent_clan: str = "") -> int:
        with closing(self._conn.cursor()) as cur:
            cur.execute(
                "INSERT INTO matches (started_at, self_clan, opponent_clan) VALUES (?, ?, ?)",
                (time.time(), self_clan, opponent_clan),
            )
            self._conn.commit()
            return cur.lastrowid

    def log_action(self, match_id: int, action: Action) -> None:
        context_json = json.dumps(action.context, ensure_ascii=False) if action.context else None
        with closing(self._conn.cursor()) as cur:
            cur.execute(
                """INSERT INTO actions
                   (match_id, turn, player, action_type, card_id, card_name, detail, timestamp, context)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    match_id,
                    action.turn,
                    action.player.value,
                    action.action_type.value,
                    action.card_id,
                    action.card_name,
                    action.detail,
                    action.timestamp,
                    context_json,
                ),
            )
            self._conn.commit()

    def update_match_clans(
        self, match_id: int, self_clan: Optional[str] = None, opponent_clan: Optional[str] = None
    ) -> None:
        """自動判別で後から判明したクラスを、開始時に記録した matches 行へ反映する."""
        with closing(self._conn.cursor()) as cur:
            if self_clan is not None:
                cur.execute("UPDATE matches SET self_clan = ? WHERE id = ?", (self_clan, match_id))
            if opponent_clan is not None:
                cur.execute("UPDATE matches SET opponent_clan = ? WHERE id = ?", (opponent_clan, match_id))
            self._conn.commit()

    def set_first_player(self, match_id: int, first_player: str) -> None:
        """先攻プレイヤー("self"/"opponent")を記録する。既に記録済みなら上書きしない."""
        with closing(self._conn.cursor()) as cur:
            cur.execute(
                "UPDATE matches SET first_player = ? WHERE id = ? AND first_player IS NULL",
                (first_player, match_id),
            )
            self._conn.commit()

    def end_match(self, match_id: int, result: str) -> None:
        with closing(self._conn.cursor()) as cur:
            cur.execute(
                "UPDATE matches SET ended_at = ?, result = ? WHERE id = ?",
                (time.time(), result, match_id),
            )
            self._conn.commit()

    # --- 予測エンジン向け集計 -------------------------------------------------

    def total_matches_vs_clan(self, opponent_clan: str) -> int:
        with closing(self._conn.cursor()) as cur:
            cur.execute("SELECT COUNT(*) FROM matches WHERE opponent_clan = ?", (opponent_clan,))
            return cur.fetchone()[0]

    def card_play_frequency(self, opponent_clan: str, card_id: str, turn: int, window: int = 1) -> float:
        """過去の対戦で、指定クラスの相手がそのターン付近(±window)にそのカードを
        プレイした割合(0.0-1.0)。対戦データが無ければ0.0."""
        total = self.total_matches_vs_clan(opponent_clan)
        if total == 0:
            return 0.0
        with closing(self._conn.cursor()) as cur:
            cur.execute(
                """SELECT COUNT(DISTINCT actions.match_id)
                   FROM actions JOIN matches ON actions.match_id = matches.id
                   WHERE matches.opponent_clan = ?
                     AND actions.player = ?
                     AND actions.action_type = ?
                     AND actions.card_id = ?
                     AND actions.turn BETWEEN ? AND ?""",
                (opponent_clan, Player.OPPONENT.value, ActionType.PLAY_CARD.value, card_id, turn - window, turn + window),
            )
            count = cur.fetchone()[0]
        return min(1.0, count / total)

    def match_results(
        self, self_clan: Optional[str] = None, opponent_clan: Optional[str] = None
    ) -> WinStats:
        """勝敗(win/loss)が記録された対戦を集計する。"unknown"等の未記録分は含めない.

        self_clan / opponent_clan を指定するとそのクラス(組み合わせ)に絞り込む。
        """
        query = "SELECT result, COUNT(*) FROM matches WHERE result IN (?, ?)"
        params: list = [RESULT_WIN, RESULT_LOSS]
        if self_clan:
            query += " AND self_clan = ?"
            params.append(self_clan)
        if opponent_clan:
            query += " AND opponent_clan = ?"
            params.append(opponent_clan)
        query += " GROUP BY result"
        with closing(self._conn.cursor()) as cur:
            cur.execute(query, params)
            counts = dict(cur.fetchall())
        return WinStats(wins=counts.get(RESULT_WIN, 0), losses=counts.get(RESULT_LOSS, 0))

    def card_win_rate(self, self_clan: str, opponent_clan: str, card_id: str) -> WinStats:
        """指定クラス相手の対戦のうち、自分がそのカードをプレイした対戦の勝敗を集計する.

        同じ対戦で同じカードを複数回プレイしても1対戦として数える(DISTINCT match_id)。
        """
        with closing(self._conn.cursor()) as cur:
            cur.execute(
                """SELECT DISTINCT matches.id, matches.result
                   FROM actions JOIN matches ON actions.match_id = matches.id
                   WHERE actions.player = ? AND actions.action_type = ? AND actions.card_id = ?
                     AND matches.self_clan = ? AND matches.opponent_clan = ?
                     AND matches.result IN (?, ?)""",
                (
                    Player.SELF.value,
                    ActionType.PLAY_CARD.value,
                    card_id,
                    self_clan,
                    opponent_clan,
                    RESULT_WIN,
                    RESULT_LOSS,
                ),
            )
            rows = cur.fetchall()
        wins = sum(1 for _match_id, result in rows if result == RESULT_WIN)
        losses = sum(1 for _match_id, result in rows if result == RESULT_LOSS)
        return WinStats(wins=wins, losses=losses)

    def evolve_win_rate(self, self_clan: str, opponent_clan: str) -> WinStats:
        """指定クラス相手の対戦のうち、自分が進化/超進化を行った対戦の勝敗を集計する.

        進化アクションはどのユニットに進化したかを記録していないため card_id での
        絞り込みはできず、「その対戦中に一度でも進化したか」単位で集計する。
        """
        with closing(self._conn.cursor()) as cur:
            cur.execute(
                """SELECT DISTINCT matches.id, matches.result
                   FROM actions JOIN matches ON actions.match_id = matches.id
                   WHERE actions.player = ? AND actions.action_type IN (?, ?)
                     AND matches.self_clan = ? AND matches.opponent_clan = ?
                     AND matches.result IN (?, ?)""",
                (
                    Player.SELF.value,
                    ActionType.EVOLVE.value,
                    ActionType.SUPER_EVOLVE.value,
                    self_clan,
                    opponent_clan,
                    RESULT_WIN,
                    RESULT_LOSS,
                ),
            )
            rows = cur.fetchall()
        wins = sum(1 for _match_id, result in rows if result == RESULT_WIN)
        losses = sum(1 for _match_id, result in rows if result == RESULT_LOSS)
        return WinStats(wins=wins, losses=losses)

    def opponent_card_pool(self, opponent_clan: str, limit: int = 200) -> list[tuple[str, int]]:
        """そのクラス相手に過去プレイされたカードと、プレイされた対戦数の一覧
        (頻度が高い順)。predictorが候補を絞り込む際の材料にする。"""
        with closing(self._conn.cursor()) as cur:
            cur.execute(
                """SELECT actions.card_id, COUNT(DISTINCT actions.match_id) AS n
                   FROM actions JOIN matches ON actions.match_id = matches.id
                   WHERE matches.opponent_clan = ? AND actions.player = ?
                     AND actions.action_type = ? AND actions.card_id IS NOT NULL
                   GROUP BY actions.card_id
                   ORDER BY n DESC
                   LIMIT ?""",
                (opponent_clan, Player.OPPONENT.value, ActionType.PLAY_CARD.value, limit),
            )
            return list(cur.fetchall())

    def _filtered_match_max_turns(
        self,
        clan_column: str,
        clan: str,
        result: Optional[str] = None,
        first_player: Optional[str] = None,
    ) -> dict[int, int]:
        """条件に合う対戦の {match_id: そのマッチで到達した最大ターン} を返す.

        result("win"/"loss")、first_player("self"/"opponent")で絞り込める。
        「そのターンに到達したマッチ数」(確率の分母)を数えるための基礎データ。
        """
        query = (
            f"SELECT matches.id, COALESCE(MAX(actions.turn), 0) "
            f"FROM matches LEFT JOIN actions ON actions.match_id = matches.id "
            f"WHERE matches.{clan_column} = ?"
        )
        params: list = [clan]
        if result is not None:
            query += " AND matches.result = ?"
            params.append(result)
        if first_player is not None:
            query += " AND matches.first_player = ?"
            params.append(first_player)
        query += " GROUP BY matches.id"
        with closing(self._conn.cursor()) as cur:
            return {mid: max_turn for mid, max_turn in cur.execute(query, params).fetchall()}

    def card_play_probability_by_turn(
        self,
        card_id: str,
        player: Player,
        clan: str,
        result: Optional[str] = None,
        first_player: Optional[str] = None,
    ) -> list[tuple[int, int, int, float]]:
        """「そのターン(=そのPP)に到達したマッチのうち、そのカードを出した割合」を
        ターンごとに返す。戻り値は (turn, played_matches, reached_matches, probability) のリスト。

        平均だと3枚積みや複数ターンで濁るため、条件付き確率で「6PP(=6ターン目)に
        達したゲームで相手がこのカードを出す確率」を出せるようにしたもの。
        player=OPPONENT なら clan は opponent_clan、SELF なら self_clan で絞り込む。
        result / first_player でさらに勝敗別・先後別に分けられる。
        """
        clan_column = "opponent_clan" if player == Player.OPPONENT else "self_clan"
        max_turns = self._filtered_match_max_turns(clan_column, clan, result, first_player)
        if not max_turns:
            return []
        match_ids = set(max_turns)

        # そのカードを「どのマッチの何ターン目に出したか」(1マッチ内の同ターン重複は除く)
        placeholders = ",".join("?" for _ in match_ids)
        query = (
            f"SELECT DISTINCT actions.match_id, actions.turn FROM actions "
            f"WHERE actions.player = ? AND actions.action_type = ? AND actions.card_id = ? "
            f"AND actions.match_id IN ({placeholders})"
        )
        params = [player.value, ActionType.PLAY_CARD.value, card_id, *match_ids]
        with closing(self._conn.cursor()) as cur:
            play_rows = cur.execute(query, params).fetchall()

        played_by_turn: dict[int, int] = {}
        for _mid, turn in play_rows:
            played_by_turn[turn] = played_by_turn.get(turn, 0) + 1

        max_observed_turn = max(max_turns.values())
        results: list[tuple[int, int, int, float]] = []
        for turn in range(1, max_observed_turn + 1):
            reached = sum(1 for mt in max_turns.values() if mt >= turn)
            if reached == 0:
                continue
            played = played_by_turn.get(turn, 0)
            results.append((turn, played, reached, played / reached))
        return results

    def card_play_situations(
        self, card_id: str, player: Player, opponent_clan: Optional[str] = None
    ) -> list[dict]:
        """指定カードがプレイされたときの局面スナップショット(context)を全て返す.

        「このカードはどんな状況で出されているか」(何ターン目・何PP・盤面何体・
        ライフ状況など)を後から考察するための生データ。context未記録の行は除く。
        """
        query = (
            "SELECT actions.context FROM actions JOIN matches ON actions.match_id = matches.id "
            "WHERE actions.player = ? AND actions.action_type = ? AND actions.card_id = ? "
            "AND actions.context IS NOT NULL"
        )
        params: list = [player.value, ActionType.PLAY_CARD.value, card_id]
        if opponent_clan:
            query += " AND matches.opponent_clan = ?"
            params.append(opponent_clan)
        with closing(self._conn.cursor()) as cur:
            rows = cur.execute(query, params).fetchall()
        situations = []
        for (context_json,) in rows:
            try:
                situations.append(json.loads(context_json))
            except (json.JSONDecodeError, TypeError):
                continue
        return situations

    def card_play_context_summary(
        self, card_id: str, player: Player, opponent_clan: Optional[str] = None
    ) -> Optional[dict]:
        """card_play_situations を集計し、代表的な傾向(平均ターン/平均PP/平均盤面数など)を返す.

        記録が1件も無ければ None。
        """
        situations = self.card_play_situations(card_id, player, opponent_clan)
        if not situations:
            return None

        def avg(key: str) -> Optional[float]:
            values = [s[key] for s in situations if isinstance(s.get(key), (int, float))]
            return sum(values) / len(values) if values else None

        pp_key = "self_pp" if player == Player.SELF else "opponent_pp"
        board_key = "self_board_count" if player == Player.SELF else "opponent_board_count"
        return {
            "samples": len(situations),
            "avg_turn": avg("turn"),
            "avg_pp": avg(pp_key),
            "avg_self_board_count": avg("self_board_count"),
            "avg_opponent_board_count": avg("opponent_board_count"),
            "avg_own_board_count": avg(board_key),
        }
