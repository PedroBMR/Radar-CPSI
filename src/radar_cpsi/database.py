"""Armazenamento SQLite versionado + deduplicação.

O arquivo .db é commitado no repositório a cada execução (ver GitHub Actions).
A deduplicação é garantida pela coluna UNIQUE `dedup_key`.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .models import Edital, _now_iso

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS editais (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    dedup_key         TEXT NOT NULL UNIQUE,
    source            TEXT NOT NULL,
    native_id         TEXT,
    title             TEXT NOT NULL,
    link              TEXT NOT NULL,
    orgao             TEXT,
    municipio         TEXT,
    uf                TEXT,
    data_publicacao   TEXT,
    descricao         TEXT,
    origem            TEXT NOT NULL DEFAULT 'diario',   -- 'diario' | 'backfill'
    cpsi_hits         TEXT,
    video_hits        TEXT,
    data_captura      TEXT NOT NULL,
    notified          INTEGER NOT NULL DEFAULT 0,       -- 0 = pendente, 1 = notificado
    notified_at       TEXT
);

CREATE INDEX IF NOT EXISTS idx_editais_source   ON editais(source);
CREATE INDEX IF NOT EXISTS idx_editais_notified ON editais(notified);
CREATE INDEX IF NOT EXISTS idx_editais_origem   ON editais(origem);

-- Estado de saúde por fonte, para detectar falhas recorrentes.
CREATE TABLE IF NOT EXISTS source_health (
    source            TEXT PRIMARY KEY,
    consecutive_fails INTEGER NOT NULL DEFAULT 0,
    last_ok_at        TEXT,
    last_error        TEXT,
    last_error_at     TEXT,
    alerted           INTEGER NOT NULL DEFAULT 0
);
"""


class Database:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    # -- ciclo de vida -------------------------------------------------------
    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # -- editais -------------------------------------------------------------
    def exists(self, dedup_key: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM editais WHERE dedup_key = ? LIMIT 1", (dedup_key,)
        )
        return cur.fetchone() is not None

    def insert_edital(self, edital: Edital) -> bool:
        """Insere um edital. Retorna True se novo, False se já existia (dedup).

        Editais de backfill entram já marcados como notificados (notified=1),
        para nunca dispararem notificação instantânea.
        """
        pre_notified = 1 if edital.origem == "backfill" else 0
        try:
            with self._tx() as conn:
                conn.execute(
                    """
                    INSERT INTO editais (
                        dedup_key, source, native_id, title, link, orgao,
                        municipio, uf, data_publicacao, descricao, origem,
                        cpsi_hits, video_hits, data_captura, notified, notified_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        edital.dedup_key, edital.source, edital.native_id,
                        edital.title, edital.link, edital.orgao, edital.municipio,
                        edital.uf, edital.data_publicacao, edital.descricao,
                        edital.origem, edital.cpsi_hits, edital.video_hits,
                        edital.data_captura, pre_notified,
                        _now_iso() if pre_notified else None,
                    ),
                )
            return True
        except sqlite3.IntegrityError:
            # dedup_key duplicado — já conhecíamos este edital.
            return False

    def pending_notifications(self) -> list[sqlite3.Row]:
        cur = self._conn.execute(
            "SELECT * FROM editais WHERE notified = 0 ORDER BY data_captura ASC"
        )
        return cur.fetchall()

    def mark_notified(self, edital_id: int) -> None:
        with self._tx() as conn:
            conn.execute(
                "UPDATE editais SET notified = 1, notified_at = ? WHERE id = ?",
                (_now_iso(), edital_id),
            )

    def count(self, *, origem: str | None = None) -> int:
        if origem:
            cur = self._conn.execute(
                "SELECT COUNT(*) FROM editais WHERE origem = ?", (origem,)
            )
        else:
            cur = self._conn.execute("SELECT COUNT(*) FROM editais")
        return int(cur.fetchone()[0])

    # -- saúde das fontes ----------------------------------------------------
    def record_source_ok(self, source: str) -> None:
        with self._tx() as conn:
            conn.execute(
                """
                INSERT INTO source_health (source, consecutive_fails, last_ok_at, alerted)
                VALUES (?, 0, ?, 0)
                ON CONFLICT(source) DO UPDATE SET
                    consecutive_fails = 0, last_ok_at = excluded.last_ok_at, alerted = 0
                """,
                (source, _now_iso()),
            )

    def record_source_failure(self, source: str, error: str) -> int:
        """Registra falha e retorna o número de falhas consecutivas."""
        with self._tx() as conn:
            conn.execute(
                """
                INSERT INTO source_health (source, consecutive_fails, last_error, last_error_at)
                VALUES (?, 1, ?, ?)
                ON CONFLICT(source) DO UPDATE SET
                    consecutive_fails = source_health.consecutive_fails + 1,
                    last_error = excluded.last_error,
                    last_error_at = excluded.last_error_at
                """,
                (source, error[:500], _now_iso()),
            )
            cur = conn.execute(
                "SELECT consecutive_fails FROM source_health WHERE source = ?", (source,)
            )
            return int(cur.fetchone()[0])

    def should_alert_source(self, source: str, threshold: int) -> bool:
        """True se a fonte já falhou `threshold`+ vezes seguidas e ainda não alertou."""
        cur = self._conn.execute(
            "SELECT consecutive_fails, alerted FROM source_health WHERE source = ?",
            (source,),
        )
        row = cur.fetchone()
        if not row:
            return False
        return row["consecutive_fails"] >= threshold and not row["alerted"]

    def mark_source_alerted(self, source: str) -> None:
        with self._tx() as conn:
            conn.execute(
                "UPDATE source_health SET alerted = 1 WHERE source = ?", (source,)
            )
