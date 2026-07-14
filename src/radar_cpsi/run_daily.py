"""Execução diária do Radar CPSI (entrypoint do cron do GitHub Actions).

    python -m radar_cpsi.run_daily [--days N]

Coleta editais recentes (últimos N dias, default 3 para tolerar folgas do cron),
filtra por CPSI+vídeo, salva os novos, envia notificação instantânea de cada novo
e um resumo diário ao final.
"""

from __future__ import annotations

import argparse
import logging
from datetime import date, timedelta

from .config import KeywordConfig, Settings, configure_logging
from .database import Database
from .http_client import HttpClient
from .keywords import KeywordMatcher
from .notifier import TelegramNotifier
from .pipeline import run_pipeline
from .sources import build_sources

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Coleta diária de editais CPSI.")
    parser.add_argument(
        "--days", type=int, default=3,
        help="Janela de coleta em dias (default: 3, para cobrir eventuais atrasos do cron).",
    )
    parser.add_argument(
        "--no-summary", action="store_true", help="Não enviar o resumo diário."
    )
    args = parser.parse_args(argv)

    configure_logging()
    settings = Settings.from_env()
    kw_config = KeywordConfig.load()
    matcher = KeywordMatcher(kw_config)

    since = (date.today() - timedelta(days=args.days)).isoformat()
    logger.info("Coleta diária desde %s (janela de %d dias)", since, args.days)

    with HttpClient() as http, Database(settings.db_path) as db:
        notifier = TelegramNotifier(settings, http)
        sources = build_sources(kw_config, http)

        report = run_pipeline(
            sources=sources,
            matcher=matcher,
            db=db,
            origem="diario",
            since=since,
            notifier=notifier,
            notify_instant=True,
        )

        if not args.no_summary:
            # busca os novos recém-inseridos para compor o resumo
            new_rows = [
                db._conn.execute(
                    "SELECT * FROM editais WHERE dedup_key = ?", (e.dedup_key,)
                ).fetchone()
                for e in report.new_editais
            ]
            new_rows = [r for r in new_rows if r is not None]
            notifier.notify_daily_summary(report.total_new, new_rows)

    logger.info(
        "Coleta diária concluída: %d novos, %d match, fontes com falha: %s",
        report.total_new,
        report.total_matched,
        [o.source for o in report.failed_sources] or "nenhuma",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
