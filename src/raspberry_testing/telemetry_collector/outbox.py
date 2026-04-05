from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path

LOGGER = logging.getLogger(__name__)

SCHEMA_SQL = '''
CREATE TABLE IF NOT EXISTS telemetry_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    qos INTEGER NOT NULL DEFAULT 0,
    retain INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'PENDING',
    retry_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at_ms INTEGER NOT NULL,
    updated_at_ms INTEGER NOT NULL,
    published_at_ms INTEGER
);

CREATE INDEX IF NOT EXISTS idx_outbox_status_id
ON telemetry_outbox(status, id);
'''


class SQLiteOutbox:
    def __init__(self, db_path: str) -> None:
        self.db_path = str(Path(db_path))
        LOGGER.info("SQLiteOutbox initialized db_path=%s", self.db_path)

    def _connect(self) -> sqlite3.Connection:
        LOGGER.debug("Opening SQLite connection db_path=%s", self.db_path)
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def setup(self) -> None:
        LOGGER.info("Setting up SQLite outbox schema")
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)
            conn.commit()
        LOGGER.info("SQLite outbox schema ready")

    def enqueue(
        self,
        *,
        topic: str,
        payload_json: str,
        qos: int,
        retain: bool,
        created_at_ms: int,
    ) -> int:
        now = int(time.time() * 1000)

        with self._connect() as conn:
            cursor = conn.execute(
                '''
                INSERT INTO telemetry_outbox (
                    topic, payload_json, qos, retain,
                    status, retry_count, created_at_ms, updated_at_ms
                )
                VALUES (?, ?, ?, ?, 'PENDING', 0, ?, ?)
                ''',
                (topic, payload_json, qos, int(retain), created_at_ms, now),
            )
            conn.commit()
            row_id = int(cursor.lastrowid)
            LOGGER.debug("Enqueued outbox row_id=%s topic=%s qos=%s retain=%s", row_id, topic, qos, retain)
            return row_id

    def fetch_batch(self, limit: int = 100) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                '''
                SELECT id, topic, payload_json, qos, retain, retry_count
                FROM telemetry_outbox
                WHERE status IN ('PENDING', 'RETRY')
                ORDER BY id ASC
                LIMIT ?
                ''',
                (limit,),
            ).fetchall()
            result = [dict(row) for row in rows]
            if result:
                LOGGER.debug("Fetched outbox batch size=%s", len(result))
            return result

    def mark_sent(self, row_id: int) -> None:
        now = int(time.time() * 1000)
        with self._connect() as conn:
            conn.execute(
                '''
                UPDATE telemetry_outbox
                SET status = 'SENT',
                    updated_at_ms = ?,
                    published_at_ms = ?
                WHERE id = ?
                ''',
                (now, now, row_id),
            )
            conn.commit()
        LOGGER.debug("Marked outbox row as SENT row_id=%s", row_id)

    def mark_retry(self, row_id: int, error: str) -> None:
        now = int(time.time() * 1000)
        with self._connect() as conn:
            conn.execute(
                '''
                UPDATE telemetry_outbox
                SET status = 'RETRY',
                    retry_count = retry_count + 1,
                    last_error = ?,
                    updated_at_ms = ?
                WHERE id = ?
                ''',
                (error[:500], now, row_id),
            )
            conn.commit()
        LOGGER.warning("Marked outbox row for RETRY row_id=%s error=%s", row_id, error[:200])

    def get_counts(self) -> dict:
        with self._connect() as conn:
            rows = conn.execute(
                '''
                SELECT status, COUNT(*) AS total
                FROM telemetry_outbox
                GROUP BY status
                '''
            ).fetchall()

        result = {"PENDING": 0, "RETRY": 0, "SENT": 0}
        for row in rows:
            result[row["status"]] = row["total"]

        LOGGER.debug("Outbox counts=%s", result)
        return result