"""
Database Manager - hỗ trợ cả PostgreSQL (Cloud Run) và SQLite (local)
- Có DATABASE_URL  → dùng PostgreSQL (Supabase/Neon/Cloud SQL) với Connection Pool
- Không có         → fallback SQLite (local dev)
"""

import json
import os
import logging
import shutil
import threading
from collections import Counter
from datetime import datetime
from typing import List, Dict, Optional

import pandas as pd
import config

logger = logging.getLogger(__name__)

# ── Wrapper cho pooled connection ─────────────────────────────
class _PooledConnection:
    """Wrap psycopg2 connection để close() trả về pool thay vì đóng hẳn."""
    def __init__(self, pool, conn):
        self._pool = pool
        self._conn = conn

    def close(self):
        try:
            self._pool.putconn(self._conn)
        except Exception as e:
            logger.warning("putconn error: %s", e)
            self._conn.close()

    def cursor(self, *args, **kwargs):
        return self._conn.cursor(*args, **kwargs)

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def __getattr__(self, name):
        return getattr(self._conn, name)

# ── Detect backend ────────────────────────────────────────────
USE_POSTGRES = bool(config.DATABASE_URL)

if USE_POSTGRES:
    import psycopg2
    import psycopg2.extras
    from psycopg2 import pool as pg_pool
    logger.info("Database backend: PostgreSQL (connection pool)")
else:
    import sqlite3
    logger.info("Database backend: SQLite (%s)", config.DB_PATH)


# ── PostgreSQL Connection Pool (module-level singleton) ───────
_pg_pool: "pg_pool.ThreadedConnectionPool | None" = None
_pg_pool_lock = threading.Lock()

def _get_pg_pool() -> "pg_pool.ThreadedConnectionPool":
    """Lazy-init ThreadedConnectionPool – an toàn với multi-thread gunicorn."""
    global _pg_pool
    if _pg_pool is not None:
        return _pg_pool
    with _pg_pool_lock:
        if _pg_pool is not None:
            return _pg_pool
        _pg_pool = pg_pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=10,          # Gunicorn 1 worker × 8 threads + dự phòng
            dsn=config.DATABASE_URL,
            connect_timeout=10,
        )
        logger.info("PostgreSQL connection pool khởi tạo (min=1, max=10)")
    return _pg_pool


class _PooledConnection:
    """Context manager: tự trả connection về pool khi xong."""
    def __init__(self, pool):
        self._pool = pool
        self.conn  = None

    def __enter__(self):
        self.conn = self._pool.getconn()
        self.conn.autocommit = False
        return self.conn

    def __exit__(self, exc_type, *_):
        if self.conn:
            if exc_type:
                try:
                    self.conn.rollback()
                except Exception:
                    pass
            self._pool.putconn(self.conn)
            self.conn = None


class DatabaseManager:

    def __init__(self):
        if not USE_POSTGRES:
            os.makedirs(
                os.path.dirname(config.DB_PATH) if os.path.dirname(config.DB_PATH) else '.',
                exist_ok=True
            )
        try:
            self.init_database()
        except Exception as e:
            logger.error("DB init failed (will retry on first request): %s", e)

    # ── Connection ────────────────────────────────────────────
    def get_connection(self):
        """
        PostgreSQL: tạo direct connection (phù hợp Cloud Run serverless + Supabase transaction pooler).
        SQLite:     tạo connection mới (WAL mode).
        """
        if USE_POSTGRES:
            conn = psycopg2.connect(config.DATABASE_URL, connect_timeout=10)
            conn.autocommit = False
            return conn
        else:
            conn = sqlite3.connect(config.DB_PATH)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            return conn

    # ── SQL helpers (cross-db) ────────────────────────────────
    @staticmethod
    def _placeholder(n: int = 1) -> str:
        p = "%s" if USE_POSTGRES else "?"
        return ", ".join([p] * n)

    @staticmethod
    def _ph() -> str:
        return "%s" if USE_POSTGRES else "?"

    # ── Schema init ───────────────────────────────────────────
    def init_database(self):
        conn = self.get_connection()
        try:
            cur = conn.cursor()

            if USE_POSTGRES:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS draw_history (
                        id            SERIAL PRIMARY KEY,
                        draw_number   INTEGER UNIQUE NOT NULL,
                        draw_time     TIMESTAMP NOT NULL,
                        numbers       TEXT NOT NULL,
                        size_category TEXT NOT NULL,
                        sum_value     INTEGER NOT NULL,
                        created_at    TIMESTAMP DEFAULT NOW()
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS predictions (
                        id                SERIAL PRIMARY KEY,
                        draw_number       INTEGER NOT NULL,
                        model_name        TEXT NOT NULL,
                        predicted_numbers TEXT NOT NULL,
                        confidence        REAL NOT NULL,
                        prediction_time   TIMESTAMP NOT NULL,
                        created_at        TIMESTAMP DEFAULT NOW()
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS prediction_results (
                        id            SERIAL PRIMARY KEY,
                        prediction_id INTEGER NOT NULL REFERENCES predictions(id),
                        draw_number   INTEGER NOT NULL,
                        actual_numbers TEXT NOT NULL,
                        match_count   INTEGER NOT NULL,
                        is_win        BOOLEAN NOT NULL,
                        is_win_size   BOOLEAN,
                        is_win_sum    BOOLEAN,
                        created_at    TIMESTAMP DEFAULT NOW()
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS model_stats (
                        id                  SERIAL PRIMARY KEY,
                        model_name          TEXT NOT NULL,
                        window_size         INTEGER NOT NULL,
                        win_rate            REAL NOT NULL,
                        total_predictions   INTEGER NOT NULL,
                        correct_predictions INTEGER NOT NULL,
                        sum_win_rate        REAL DEFAULT 0.0,
                        updated_at          TIMESTAMP DEFAULT NOW(),
                        UNIQUE(model_name, window_size)
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS markov_transitions (
                        id          SERIAL PRIMARY KEY,
                        from_state  TEXT NOT NULL,
                        to_state    TEXT NOT NULL,
                        count       INTEGER DEFAULT 1,
                        probability REAL DEFAULT 0.0,
                        updated_at  TIMESTAMP DEFAULT NOW(),
                        UNIQUE(from_state, to_state)
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS cold_numbers (
                        id             SERIAL PRIMARY KEY,
                        number         INTEGER NOT NULL UNIQUE,
                        last_seen_draw INTEGER NOT NULL,
                        absence_count  INTEGER NOT NULL,
                        updated_at     TIMESTAMP DEFAULT NOW()
                    )
                """)
                for ddl in [
                    "CREATE INDEX IF NOT EXISTS idx_draw_number    ON draw_history(draw_number DESC)",
                    "CREATE INDEX IF NOT EXISTS idx_draw_time      ON draw_history(draw_time DESC)",
                    "CREATE INDEX IF NOT EXISTS idx_pred_draw      ON predictions(draw_number)",
                    "CREATE INDEX IF NOT EXISTS idx_pred_time      ON predictions(prediction_time DESC)",
                    "CREATE INDEX IF NOT EXISTS idx_pred_model     ON predictions(model_name)",
                    "CREATE INDEX IF NOT EXISTS idx_presult_pid    ON prediction_results(prediction_id)",
                    "CREATE INDEX IF NOT EXISTS idx_presult_create ON prediction_results(created_at DESC)",
                    "CREATE INDEX IF NOT EXISTS idx_markov_from    ON markov_transitions(from_state)",
                ]:
                    cur.execute(ddl)

                # ── Migrations (idempotent) ──────────────────────────
                for ddl in [
                    "ALTER TABLE prediction_results ADD COLUMN IF NOT EXISTS is_win_size BOOLEAN",
                    "ALTER TABLE prediction_results ADD COLUMN IF NOT EXISTS is_win_sum  BOOLEAN",
                    "ALTER TABLE model_stats        ADD COLUMN IF NOT EXISTS sum_win_rate REAL DEFAULT 0.0",
                    # required by update_prediction_result()'s ON CONFLICT (prediction_id)
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_presult_pid_uniq ON prediction_results(prediction_id)",
                    # required by insert_prediction() / voter-weight & analytics queries (app.py, prediction_service.py)
                    "ALTER TABLE predictions        ADD COLUMN IF NOT EXISTS vote_breakdown JSONB",
                ]:
                    cur.execute(ddl)

                # Backfill is_win_sum cho các row chưa có
                cur.execute("""
                    UPDATE prediction_results pr
                    SET is_win_sum = (
                        (SELECT SUM(elem::integer)
                         FROM json_array_elements_text(p.predicted_numbers::json) AS elem)
                        =
                        (SELECT SUM(elem::integer)
                         FROM json_array_elements_text(pr.actual_numbers::json) AS elem)
                    )
                    FROM predictions p
                    WHERE p.id = pr.prediction_id
                      AND pr.is_win_sum IS NULL
                """)

            else:  # SQLite
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS draw_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        draw_number INTEGER UNIQUE NOT NULL,
                        draw_time TIMESTAMP NOT NULL,
                        numbers TEXT NOT NULL,
                        size_category TEXT NOT NULL,
                        sum_value INTEGER NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )""")
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS predictions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        draw_number INTEGER NOT NULL,
                        model_name TEXT NOT NULL,
                        predicted_numbers TEXT NOT NULL,
                        confidence REAL NOT NULL,
                        prediction_time TIMESTAMP NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )""")
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS prediction_results (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        prediction_id INTEGER NOT NULL,
                        draw_number INTEGER NOT NULL,
                        actual_numbers TEXT NOT NULL,
                        match_count INTEGER NOT NULL,
                        is_win BOOLEAN NOT NULL,
                        is_win_size BOOLEAN,
                        is_win_sum  BOOLEAN,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (prediction_id) REFERENCES predictions(id)
                    )""")
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS model_stats (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        model_name TEXT NOT NULL,
                        window_size INTEGER NOT NULL,
                        win_rate REAL NOT NULL,
                        total_predictions INTEGER NOT NULL,
                        correct_predictions INTEGER NOT NULL,
                        sum_win_rate REAL DEFAULT 0.0,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(model_name, window_size)
                    )""")
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS markov_transitions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        from_state TEXT NOT NULL,
                        to_state TEXT NOT NULL,
                        count INTEGER DEFAULT 1,
                        probability REAL DEFAULT 0.0,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(from_state, to_state)
                    )""")
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS cold_numbers (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        number INTEGER NOT NULL UNIQUE,
                        last_seen_draw INTEGER NOT NULL,
                        absence_count INTEGER NOT NULL,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )""")
                for ddl in [
                    "CREATE INDEX IF NOT EXISTS idx_draw_number ON draw_history(draw_number DESC)",
                    "CREATE INDEX IF NOT EXISTS idx_pred_time   ON predictions(prediction_time DESC)",
                    "CREATE INDEX IF NOT EXISTS idx_pred_model  ON predictions(model_name)",
                    "CREATE INDEX IF NOT EXISTS idx_markov_from ON markov_transitions(from_state)",
                    # required by update_prediction_result()'s ON CONFLICT (prediction_id)
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_presult_pid_uniq ON prediction_results(prediction_id)",
                ]:
                    cur.execute(ddl)

                # ── SQLite migrations (idempotent) ───────────────────
                for col_ddl in [
                    "ALTER TABLE prediction_results ADD COLUMN is_win_size BOOLEAN",
                    "ALTER TABLE prediction_results ADD COLUMN is_win_sum  BOOLEAN",
                    "ALTER TABLE model_stats        ADD COLUMN sum_win_rate REAL DEFAULT 0.0",
                    # required by _get_voter_multipliers()'s SQLite-path query (p.vote_breakdown)
                    "ALTER TABLE predictions        ADD COLUMN vote_breakdown TEXT",
                ]:
                    try:
                        cur.execute(col_ddl)
                    except Exception:
                        pass  # column already exists

                # Backfill is_win_sum cho SQLite (Python-side vì SQLite JSON yếu)
                cur.execute("""
                    SELECT pr.id, p.predicted_numbers, pr.actual_numbers
                    FROM prediction_results pr
                    JOIN predictions p ON p.id = pr.prediction_id
                    WHERE pr.is_win_sum IS NULL
                """)
                rows = cur.fetchall()
                for pr_id, pred_json, actual_json in rows:
                    try:
                        pred   = json.loads(pred_json) if isinstance(pred_json, str) else pred_json
                        actual = json.loads(actual_json) if isinstance(actual_json, str) else actual_json
                        cur.execute("UPDATE prediction_results SET is_win_sum=? WHERE id=?",
                                    (sum(pred) == sum(actual), pr_id))
                    except Exception:
                        pass

            conn.commit()
        finally:
            conn.close()

    # ── Draw history ──────────────────────────────────────────
    def insert_draw(self, draw_number: int, numbers: List[int],
                    draw_time: datetime = None) -> int:
        if draw_time is None:
            draw_time = datetime.now()

        numbers_str   = json.dumps(sorted(numbers))
        sum_value     = sum(numbers)
        s             = sum_value
        size_category = ("NHO" if config.SIZE_SMALL[0] <= s <= config.SIZE_SMALL[1]
                         else "HOA" if config.SIZE_MEDIUM[0] <= s <= config.SIZE_MEDIUM[1]
                         else "LON")
        ph   = self._ph()
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            if USE_POSTGRES:
                cur.execute(f"""
                    INSERT INTO draw_history (draw_number, draw_time, numbers, size_category, sum_value)
                    VALUES ({ph},{ph},{ph},{ph},{ph})
                    ON CONFLICT (draw_number) DO NOTHING
                    RETURNING id
                """, (draw_number, draw_time, numbers_str, size_category, sum_value))
                row = cur.fetchone()
                conn.commit()
                return row[0] if row else -1
            else:
                try:
                    cur.execute(f"""
                        INSERT INTO draw_history (draw_number, draw_time, numbers, size_category, sum_value)
                        VALUES ({ph},{ph},{ph},{ph},{ph})
                    """, (draw_number, draw_time, numbers_str, size_category, sum_value))
                    conn.commit()
                    return cur.lastrowid
                except Exception:
                    return -1
        finally:
            conn.close()

    def get_recent_draws(self, limit: int = 100) -> pd.DataFrame:
        ph   = self._ph()
        conn = self.get_connection()
        try:
            if USE_POSTGRES:
                cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur.execute(f"""
                    SELECT draw_number, draw_time, numbers, size_category, sum_value
                    FROM draw_history ORDER BY draw_number DESC LIMIT {ph}
                """, (limit,))
                rows = cur.fetchall()
                df = pd.DataFrame(rows) if rows else pd.DataFrame(
                    columns=['draw_number', 'draw_time', 'numbers', 'size_category', 'sum_value'])
            else:
                df = pd.read_sql_query(
                    f"SELECT draw_number,draw_time,numbers,size_category,sum_value "
                    f"FROM draw_history ORDER BY draw_number DESC LIMIT {ph}",
                    conn, params=(limit,))
        finally:
            conn.close()

        if not df.empty:
            df['numbers'] = df['numbers'].apply(
                lambda x: json.loads(x) if isinstance(x, str) else x)
        return df

    # ── Predictions ───────────────────────────────────────────
    def insert_prediction(self, draw_number: int, model_name: str,
                          predicted_numbers: List[int], confidence: float,
                          vote_breakdown: dict = None) -> tuple:
        """Returns (id, is_new) where is_new=False means prediction already existed.

        Uses pg_advisory_xact_lock to serialize concurrent inserts for the same
        draw_number across Cloud Run instances, preventing duplicate Telegram sends.
        """
        ph   = self._ph()
        conn = self.get_connection()
        try:
            cur = conn.cursor()

            if USE_POSTGRES:
                # Advisory lock per draw_number: blocks until no other transaction
                # holds the lock, then proceeds. Released automatically on COMMIT.
                # Offset by 1_000_000 to avoid collision with other pg_advisory uses.
                cur.execute("SELECT pg_advisory_xact_lock(%s)", (1_000_000 + draw_number,))

            # Re-check after acquiring lock (safe: serialized by advisory lock on Postgres,
            # or sequential on SQLite since it's single-writer)
            cur.execute(f"SELECT id FROM predictions WHERE draw_number={ph} ORDER BY id DESC LIMIT 1",
                        (draw_number,))
            existing = cur.fetchone()
            if existing:
                logger.info("Prediction for draw #%d already exists (id=%d), skipping insert",
                            draw_number, existing[0])
                conn.commit()   # release advisory lock
                return existing[0], False

            vb_json = json.dumps(vote_breakdown) if vote_breakdown else None
            if USE_POSTGRES:
                cur.execute(f"""
                    INSERT INTO predictions (draw_number, model_name, predicted_numbers, confidence, prediction_time, vote_breakdown)
                    VALUES ({ph},{ph},{ph},{ph},{ph},{ph}) RETURNING id
                """, (draw_number, model_name, json.dumps([int(x) for x in predicted_numbers]),
                      confidence, datetime.now(), vb_json))
                row_id = cur.fetchone()[0]
            else:
                cur.execute(f"""
                    INSERT INTO predictions (draw_number, model_name, predicted_numbers, confidence, prediction_time)
                    VALUES ({ph},{ph},{ph},{ph},{ph})
                """, (draw_number, model_name, json.dumps([int(x) for x in predicted_numbers]),
                      confidence, datetime.now()))
                row_id = cur.lastrowid
            conn.commit()
            return row_id, True
        finally:
            conn.close()

    @staticmethod
    def get_size_category(numbers: List[int]) -> str:
        s = sum(numbers)
        if s <= config.SIZE_SMALL[1]:
            return "NHO"
        if s <= config.SIZE_MEDIUM[1]:
            return "HOA"
        return "LON"

    def get_recent_predictions(self, model_name: str, limit: int = 5) -> List[List[int]]:
        """Lấy N predicted_numbers gần nhất của một model."""
        ph   = self._ph()
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                f"SELECT predicted_numbers FROM predictions WHERE model_name={ph} "
                f"ORDER BY created_at DESC LIMIT {ph}",
                (model_name, limit))
            rows = cur.fetchall()
            return [json.loads(row[0]) if isinstance(row[0], str) else row[0]
                    for row in rows]
        finally:
            conn.close()

    def update_prediction_result(self, prediction_id: int, draw_number: int,
                                 actual_numbers: List[int]):
        ph   = self._ph()
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute(f"SELECT predicted_numbers FROM predictions WHERE id={ph}",
                        (prediction_id,))
            row = cur.fetchone()
            if not row:
                return
            predicted   = json.loads(row[0])
            match_count = len(set(predicted) & set(actual_numbers))
            size_ok     = len(predicted) == 3 and len(actual_numbers) == 3
            is_win_size = self.get_size_category(predicted) == self.get_size_category(actual_numbers) if size_ok else False
            is_win      = is_win_size  # win = predicted SIZE category matches actual SIZE
            is_win_sum  = (sum(int(x) for x in predicted) == sum(int(x) for x in actual_numbers)) if size_ok else False
            cur.execute(f"""
                INSERT INTO prediction_results
                    (prediction_id, draw_number, actual_numbers, match_count, is_win, is_win_size, is_win_sum)
                VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph})
                ON CONFLICT (prediction_id) DO NOTHING
            """, (prediction_id, draw_number,
                  json.dumps(actual_numbers), match_count, is_win, is_win_size, is_win_sum))
            conn.commit()
        finally:
            conn.close()

    # ── Model stats ───────────────────────────────────────────
    def get_model_win_rate(self, model_name: str, window: int = 100) -> float:
        ph   = self._ph()
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute(f"""
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN is_win THEN 1 ELSE 0 END) as wins
                FROM (
                    SELECT pr.is_win
                    FROM prediction_results pr
                    JOIN predictions p ON pr.prediction_id = p.id
                    WHERE p.model_name = {ph}
                    ORDER BY pr.created_at DESC
                    LIMIT {ph}
                ) sub
            """, (model_name, window))
            row = cur.fetchone()
            if row and row[0]:
                return (row[1] or 0) / row[0]
            return 0.0
        finally:
            conn.close()

    def get_model_sum_win_rate(self, model_name: str, window: int = 100) -> float:
        """Tỷ lệ dự đoán đúng tổng (sum(predicted) == sum(actual))."""
        ph   = self._ph()
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute(f"""
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN COALESCE(is_win_sum, FALSE) THEN 1 ELSE 0 END) as sum_wins
                FROM (
                    SELECT pr.is_win_sum
                    FROM prediction_results pr
                    JOIN predictions p ON pr.prediction_id = p.id
                    WHERE p.model_name = {ph}
                      AND pr.is_win_sum IS NOT NULL
                    ORDER BY pr.created_at DESC
                    LIMIT {ph}
                ) sub
            """, (model_name, window))
            row = cur.fetchone()
            if row and row[0]:
                return (row[1] or 0) / row[0]
            return 0.0
        finally:
            conn.close()

    def refresh_model_stats(self, model_names: List[str],
                            windows: List[int] = [50, 100, 200, 300]):
        ph   = self._ph()
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            for model in model_names:
                for window in windows:
                    cur.execute(f"""
                        SELECT COUNT(*) as total,
                               SUM(CASE WHEN is_win THEN 1 ELSE 0 END) as wins,
                               SUM(CASE WHEN COALESCE(is_win_sum, FALSE) THEN 1 ELSE 0 END) as sum_wins
                        FROM (
                            SELECT pr.is_win, pr.is_win_sum
                            FROM prediction_results pr
                            JOIN predictions p ON pr.prediction_id = p.id
                            WHERE p.model_name = {ph}
                            ORDER BY pr.created_at DESC
                            LIMIT {ph}
                        ) sub
                    """, (model, window))
                    row      = cur.fetchone()
                    total    = row[0] if row else 0
                    wins     = (row[1] or 0) if row else 0
                    sum_wins = (row[2] or 0) if row else 0
                    wr       = wins / total if total > 0 else 0.0
                    swr      = sum_wins / total if total > 0 else 0.0

                    if USE_POSTGRES:
                        cur.execute(f"""
                            INSERT INTO model_stats
                                (model_name, window_size, win_rate, total_predictions,
                                 correct_predictions, sum_win_rate)
                            VALUES ({ph},{ph},{ph},{ph},{ph},{ph})
                            ON CONFLICT (model_name, window_size) DO UPDATE SET
                                win_rate            = EXCLUDED.win_rate,
                                total_predictions   = EXCLUDED.total_predictions,
                                correct_predictions = EXCLUDED.correct_predictions,
                                sum_win_rate        = EXCLUDED.sum_win_rate,
                                updated_at          = NOW()
                        """, (model, window, wr, total, wins, swr))
                    else:
                        cur.execute(f"""
                            INSERT OR REPLACE INTO model_stats
                                (model_name, window_size, win_rate, total_predictions,
                                 correct_predictions, sum_win_rate, updated_at)
                            VALUES ({ph},{ph},{ph},{ph},{ph},{ph},CURRENT_TIMESTAMP)
                        """, (model, window, wr, total, wins, swr))
            conn.commit()
        finally:
            conn.close()

    # ── Markov ────────────────────────────────────────────────
    def update_markov_transition(self, from_state: str, to_state: str):
        ph   = self._ph()
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            if USE_POSTGRES:
                cur.execute(f"""
                    INSERT INTO markov_transitions (from_state, to_state, count)
                    VALUES ({ph},{ph},1)
                    ON CONFLICT (from_state, to_state)
                    DO UPDATE SET count = markov_transitions.count + 1, updated_at = NOW()
                """, (from_state, to_state))
                cur.execute(f"""
                    UPDATE markov_transitions mt
                    SET probability = mt.count::REAL / total.s
                    FROM (SELECT SUM(count) AS s FROM markov_transitions
                          WHERE from_state = {ph}) total
                    WHERE mt.from_state = {ph}
                """, (from_state, from_state))
            else:
                cur.execute(f"""
                    INSERT INTO markov_transitions (from_state, to_state, count)
                    VALUES ({ph},{ph},1)
                    ON CONFLICT(from_state, to_state)
                    DO UPDATE SET count=count+1, updated_at=CURRENT_TIMESTAMP
                """, (from_state, to_state))
                cur.execute(f"""
                    UPDATE markov_transitions
                    SET probability = CAST(count AS REAL) / (
                        SELECT SUM(count) FROM markov_transitions WHERE from_state={ph})
                    WHERE from_state={ph}
                """, (from_state, from_state))
            conn.commit()
        finally:
            conn.close()

    def get_markov_probabilities(self, from_state: str) -> Dict[str, float]:
        ph   = self._ph()
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute(f"""
                SELECT to_state, probability FROM markov_transitions
                WHERE from_state={ph} ORDER BY probability DESC
            """, (from_state,))
            return {r[0]: r[1] for r in cur.fetchall()}
        finally:
            conn.close()

    # ── Cold numbers ──────────────────────────────────────────
    def update_cold_numbers(self, current_draw: int, actual_numbers: List[int] = None):
        if actual_numbers is None:
            ph    = self._ph()
            conn2 = self.get_connection()
            try:
                cur2 = conn2.cursor()
                cur2.execute(
                    f"SELECT numbers FROM draw_history WHERE draw_number={ph}",
                    (current_draw,))
                row            = cur2.fetchone()
                actual_numbers = json.loads(row[0]) if row else []
            finally:
                conn2.close()

        appeared = set(actual_numbers)
        ph   = self._ph()
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            for num in range(1, 7):   # Bingo18: chỉ có số 1-6
                if num in appeared:
                    if USE_POSTGRES:
                        cur.execute(f"""
                            INSERT INTO cold_numbers (number, last_seen_draw, absence_count)
                            VALUES ({ph},{ph},0)
                            ON CONFLICT (number) DO UPDATE SET
                                last_seen_draw=EXCLUDED.last_seen_draw,
                                absence_count=0, updated_at=NOW()
                        """, (num, current_draw))
                    else:
                        cur.execute(f"""
                            INSERT INTO cold_numbers (number, last_seen_draw, absence_count)
                            VALUES ({ph},{ph},0)
                            ON CONFLICT(number) DO UPDATE SET
                                last_seen_draw=excluded.last_seen_draw,
                                absence_count=0, updated_at=CURRENT_TIMESTAMP
                        """, (num, current_draw))
                else:
                    if USE_POSTGRES:
                        cur.execute(f"""
                            INSERT INTO cold_numbers (number, last_seen_draw, absence_count)
                            VALUES ({ph},{ph},1)
                            ON CONFLICT (number) DO UPDATE SET
                                absence_count=cold_numbers.absence_count+1, updated_at=NOW()
                        """, (num, current_draw - 1))
                    else:
                        cur.execute(f"""
                            INSERT INTO cold_numbers (number, last_seen_draw, absence_count)
                            VALUES ({ph},{ph},1)
                            ON CONFLICT(number) DO UPDATE SET
                                absence_count=absence_count+1, updated_at=CURRENT_TIMESTAMP
                        """, (num, current_draw - 1))
            conn.commit()
        finally:
            conn.close()

    def get_cold_numbers(self) -> List[Dict]:
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT number, last_seen_draw, absence_count "
                "FROM cold_numbers ORDER BY absence_count DESC")
            return [{'number': r[0], 'last_seen': r[1], 'absence': r[2]}
                    for r in cur.fetchall()]
        finally:
            conn.close()

    # ── Hot / Cold numbers (dùng cho API dashboard) ───────────
    def get_hot_cold_numbers(self, window: int = 50) -> Dict:
        ph   = self._ph()
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                f"SELECT numbers FROM draw_history ORDER BY draw_number DESC LIMIT {ph}",
                (window,))
            rows = cur.fetchall()
        finally:
            conn.close()

        freq: Dict[int, int] = {}
        for row in rows:
            nums = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            for n in nums:
                freq[n] = freq.get(n, 0) + 1

        sorted_nums = sorted(freq.items(), key=lambda x: x[1], reverse=True)
        hot  = [{"number": k, "count": v} for k, v in sorted_nums[:3]]
        cold = [{"number": k, "count": v} for k, v in sorted_nums[-3:]]
        return {"hot": hot, "cold": cold}

    # ── Number frequency (dùng cho API dashboard) ─────────────
    def get_number_frequency(self, window: int = 100) -> Dict:
        ph   = self._ph()
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute(
                f"SELECT numbers FROM draw_history ORDER BY draw_number DESC LIMIT {ph}",
                (window,))
            rows = cur.fetchall()
        finally:
            conn.close()

        freq: Dict[int, int] = {i: 0 for i in range(1, 7)}
        for row in rows:
            nums = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            for n in nums:
                if 1 <= n <= 6:
                    freq[n] = freq.get(n, 0) + 1
        return freq

    # ── Statistics ────────────────────────────────────────────
    def get_statistics(self) -> Dict:
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM draw_history")
            total = cur.fetchone()[0]

            cur.execute(
                "SELECT size_category, COUNT(*) FROM draw_history GROUP BY size_category")
            size_dist = {r[0]: r[1] for r in cur.fetchall()}

            cur.execute("""
                SELECT model_name, win_rate, total_predictions
                FROM model_stats WHERE window_size=100 AND total_predictions > 0
                ORDER BY win_rate DESC
            """)
            model_perf = [{'model': r[0], 'win_rate': r[1], 'total': r[2]}
                          for r in cur.fetchall()]
            return {
                'total_draws':        total,
                'size_distribution':  size_dist,
                'model_performance':  model_perf,
            }
        finally:
            conn.close()

    # ── Backup (chỉ dùng khi SQLite) ─────────────────────────
    def backup_database(self, backup_path: str = None) -> str:
        if USE_POSTGRES:
            logger.info("Backup skipped – PostgreSQL managed by Supabase")
            return ""
        if backup_path is None:
            backup_path = config.BACKUP_PATH
        os.makedirs(backup_path, exist_ok=True)
        ts   = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = os.path.join(backup_path, f"backup_{ts}.db")
        shutil.copy2(config.DB_PATH, dest)
        files = sorted([os.path.join(backup_path, f)
                        for f in os.listdir(backup_path) if f.endswith('.db')])
        for old in files[:-7]:
            os.remove(old)
        return dest

    ALLOWED_TABLES = {"draw_history", "predictions", "prediction_results", "model_stats"}

    def export_to_csv(self, table_name: str, output_path: str):
        if table_name not in self.ALLOWED_TABLES:
            raise ValueError(f"Table '{table_name}' không được phép export")
        conn = self.get_connection()
        try:
            df = pd.read_sql_query(f"SELECT * FROM {table_name}", conn)
            df.to_csv(output_path, index=False)
        finally:
            conn.close()