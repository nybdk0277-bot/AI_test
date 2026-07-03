"""対戦履歴の永続化(SQLite)と、予測エンジン向けの集計クエリ."""
from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Optional

from svtracker.game.models import Action, Player

SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at REAL NOT NULL,
    ended_at REAL,
    self_clan TEXT,
    opponent_clan TEXT,
    result TEXT
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
    timestamp REAL NOT NULL
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
        self._conn.commit()

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
        with closing(self._conn.cursor()) as cur:
            cur.execute(
                """INSERT INTO actions
                   (match_id, turn, player, action_type, card_id, card_name, detail, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    match_id,
                    action.turn,
                    action.player.value,
                    action.action_type.value,
                    action.card_id,
                    action.card_name,
                    action.detail,
                    action.timestamp,
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
                     AND actions.card_id = ?
                     AND actions.turn BETWEEN ? AND ?""",
                (opponent_clan, Player.OPPONENT.value, card_id, turn - window, turn + window),
            )
            count = cur.fetchone()[0]
        return min(1.0, count / total)

    def opponent_card_pool(self, opponent_clan: str, limit: int = 200) -> list[tuple[str, int]]:
        """そのクラス相手に過去プレイされたカードと、プレイされた対戦数の一覧
        (頻度が高い順)。predictorが候補を絞り込む際の材料にする。"""
        with closing(self._conn.cursor()) as cur:
            cur.execute(
                """SELECT actions.card_id, COUNT(DISTINCT actions.match_id) AS n
                   FROM actions JOIN matches ON actions.match_id = matches.id
                   WHERE matches.opponent_clan = ? AND actions.player = ? AND actions.card_id IS NOT NULL
                   GROUP BY actions.card_id
                   ORDER BY n DESC
                   LIMIT ?""",
                (opponent_clan, Player.OPPONENT.value, limit),
            )
            return list(cur.fetchall())
