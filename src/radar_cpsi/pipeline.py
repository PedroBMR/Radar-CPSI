"""Pipeline compartilhado entre coleta diária e backfill.

Fluxo:
  fontes.fetch() -> KeywordMatcher.evaluate() -> Database.insert (dedup) -> contagem

A notificação instantânea acontece só na coleta diária; no backfill os registros
entram pré-marcados como notificados (ver Database.insert_edital) e não disparam
mensagem — só entram no relatório final.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .database import Database
from .keywords import KeywordMatcher
from .models import Edital
from .notifier import TelegramNotifier
from .sources.base import Source

logger = logging.getLogger(__name__)

# Após quantas falhas consecutivas de uma fonte disparamos alerta no Telegram.
SOURCE_FAILURE_ALERT_THRESHOLD = 3


@dataclass
class SourceOutcome:
    source: str
    fetched: int = 0
    matched: int = 0
    new: int = 0
    error: str | None = None


@dataclass
class RunReport:
    origem: str
    outcomes: list[SourceOutcome] = field(default_factory=list)
    new_editais: list[Edital] = field(default_factory=list)

    @property
    def total_new(self) -> int:
        return sum(o.new for o in self.outcomes)

    @property
    def total_matched(self) -> int:
        return sum(o.matched for o in self.outcomes)

    @property
    def failed_sources(self) -> list[SourceOutcome]:
        return [o for o in self.outcomes if o.error]


def run_pipeline(
    *,
    sources: list[Source],
    matcher: KeywordMatcher,
    db: Database,
    origem: str,
    since: str | None = None,
    until: str | None = None,
    notifier: TelegramNotifier | None = None,
    notify_instant: bool = True,
) -> RunReport:
    """Executa a coleta sobre todas as fontes, isolando falhas por fonte."""
    report = RunReport(origem=origem)

    for source in sources:
        outcome = SourceOutcome(source=source.name)
        report.outcomes.append(outcome)
        try:
            for edital in source.fetch(since=since, until=until):
                outcome.fetched += 1
                result = matcher.evaluate(*edital.searchable_text())
                if not result.is_match:
                    continue
                outcome.matched += 1
                edital.origem = origem
                edital.cpsi_hits = ", ".join(result.cpsi_hits)
                edital.video_hits = ", ".join(result.video_hits)

                is_new = db.insert_edital(edital)
                if not is_new:
                    continue
                outcome.new += 1
                report.new_editais.append(edital)

                # Notificação instantânea (só coleta diária).
                if notify_instant and notifier is not None:
                    if notifier.notify_new_edital(edital):
                        # marca notificado buscando o id recém-inserido
                        _mark_notified_by_key(db, edital.dedup_key)

            db.record_source_ok(source.name)
            logger.info(
                "Fonte %s: %d captados, %d match, %d novos",
                source.name, outcome.fetched, outcome.matched, outcome.new,
            )
        except Exception as exc:  # isola falha da fonte
            outcome.error = f"{type(exc).__name__}: {exc}"
            logger.exception("Fonte %s falhou", source.name)
            fails = db.record_source_failure(source.name, outcome.error)
            if (
                notifier is not None
                and db.should_alert_source(source.name, SOURCE_FAILURE_ALERT_THRESHOLD)
            ):
                notifier.notify_source_failure(source.name, fails, outcome.error)
                db.mark_source_alerted(source.name)

    return report


def _mark_notified_by_key(db: Database, dedup_key: str) -> None:
    row = db._conn.execute(
        "SELECT id FROM editais WHERE dedup_key = ?", (dedup_key,)
    ).fetchone()
    if row:
        db.mark_notified(int(row["id"]))
