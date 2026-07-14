"""Carga histórica (backfill) — roda UMA vez, sob demanda, fora do cron diário.

    python -m radar_cpsi.backfill [--start YYYY-MM-DD] [--reset]

Busca todos os editais de CPSI de videomonitoramento desde a vigência da
LC 182/2021 (2021-09-01) até hoje, aplicando o mesmo filtro de palavras-chave e
populando o mesmo banco SQLite.

Características:
  - Registros marcados com origem='backfill' e SEM notificação instantânea.
  - Processa mês a mês e grava um checkpoint em disco; se cair no meio, ao rodar
    de novo retoma a partir do último mês concluído (use --reset para recomeçar).
  - Respeita rate limit / retry via HttpClient.
Ao final, envia um único resumo consolidado ao Telegram (não uma msg por edital).
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import date

from .config import (
    LC182_START_DATE,
    KeywordConfig,
    Settings,
    configure_logging,
)
from .database import Database
from .http_client import HttpClient
from .keywords import KeywordMatcher
from .notifier import TelegramNotifier
from .pipeline import run_pipeline
from .sources import build_sources

logger = logging.getLogger(__name__)

CHECKPOINT_NAME = "backfill_checkpoint.json"


def _month_windows(start: date, end: date) -> list[tuple[str, str]]:
    """Gera janelas mensais [primeiro_dia, ultimo_dia] de start até end."""
    windows: list[tuple[str, str]] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        first = date(y, m, 1)
        if m == 12:
            ny, nm = y + 1, 1
        else:
            ny, nm = y, m + 1
        last = date(ny, nm, 1).toordinal() - 1
        last_d = date.fromordinal(last)
        w_start = max(first, start).isoformat()
        w_end = min(last_d, end).isoformat()
        windows.append((w_start, w_end))
        y, m = ny, nm
    return windows


def _load_checkpoint(path) -> set[str]:
    if path.exists():
        try:
            return set(json.loads(path.read_text(encoding="utf-8")).get("done", []))
        except (json.JSONDecodeError, OSError):
            logger.warning("Checkpoint corrompido, ignorando: %s", path)
    return set()


def _save_checkpoint(path, done: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"done": sorted(done)}, ensure_ascii=False), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Carga histórica de editais CPSI.")
    parser.add_argument(
        "--start", default=LC182_START_DATE,
        help=f"Data inicial (YYYY-MM-DD). Default: {LC182_START_DATE} (vigência da LC 182/2021).",
    )
    parser.add_argument(
        "--end", default=date.today().isoformat(), help="Data final (YYYY-MM-DD). Default: hoje."
    )
    parser.add_argument(
        "--reset", action="store_true", help="Ignora o checkpoint e recomeça do zero."
    )
    args = parser.parse_args(argv)

    configure_logging()
    settings = Settings.from_env()
    kw_config = KeywordConfig.load()
    matcher = KeywordMatcher(kw_config)

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    windows = _month_windows(start, end)
    checkpoint_path = settings.checkpoint_dir / CHECKPOINT_NAME
    done = set() if args.reset else _load_checkpoint(checkpoint_path)
    if args.reset and checkpoint_path.exists():
        checkpoint_path.unlink()

    logger.info(
        "Backfill de %s a %s — %d janelas mensais (%d já concluídas).",
        args.start, args.end, len(windows), len(done),
    )

    total_new = 0
    total_matched = 0
    with HttpClient(min_interval=1.0) as http, Database(settings.db_path) as db:
        notifier = TelegramNotifier(settings, http)
        sources = build_sources(kw_config, http)

        for w_start, w_end in windows:
            window_id = f"{w_start}:{w_end}"
            if window_id in done:
                logger.info("Pulando janela já concluída: %s", window_id)
                continue

            logger.info("Processando janela %s", window_id)
            report = run_pipeline(
                sources=sources,
                matcher=matcher,
                db=db,
                origem="backfill",
                since=w_start,
                until=w_end,
                notifier=notifier,
                notify_instant=False,  # backfill nunca notifica instantâneo
            )
            total_new += report.total_new
            total_matched += report.total_matched

            # Só marca a janela como concluída se nenhuma fonte falhou nela,
            # para que uma retomada reprocesse janelas incompletas.
            if not report.failed_sources:
                done.add(window_id)
                _save_checkpoint(checkpoint_path, done)
            else:
                logger.warning(
                    "Janela %s teve falha em %s — não marcada como concluída.",
                    window_id, [o.source for o in report.failed_sources],
                )

    logger.info("Backfill concluído: %d novos, %d match no total.", total_new, total_matched)
    notifier.notify_text(
        f"📚 <b>Radar CPSI — carga histórica concluída</b>\n"
        f"Período: {args.start} a {args.end}\n"
        f"Novos editais adicionados: {total_new}\n"
        f"Total de matches avaliados: {total_matched}\n"
        f"Registros marcados como <code>backfill</code> (sem notificação individual)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
