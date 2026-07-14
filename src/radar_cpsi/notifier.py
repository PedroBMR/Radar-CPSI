"""Notificador via Telegram.

Três tipos de mensagem:
  1. Instantânea  — um edital novo compatível (coleta diária).
  2. Resumo diário — consolidado ao final da execução.
  3. Alerta de fonte — quando uma fonte falha de forma recorrente.

Secrets (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID) vêm de variáveis de ambiente.
Em modo dry-run (ou sem secrets), apenas registra no log — nada é enviado.
"""

from __future__ import annotations

import html
import logging
import sqlite3

from .config import Settings
from .http_client import HttpClient
from .models import Edital

logger = logging.getLogger(__name__)

API_BASE = "https://api.telegram.org"


class TelegramNotifier:
    def __init__(self, settings: Settings, http: HttpClient) -> None:
        self.settings = settings
        self.http = http
        self._enabled = settings.telegram_configured and not settings.dry_run
        if not settings.telegram_configured:
            logger.warning(
                "Telegram não configurado (faltam TELEGRAM_BOT_TOKEN/CHAT_ID). "
                "Mensagens serão apenas logadas."
            )
        elif settings.dry_run:
            logger.info("RADAR_DRY_RUN ativo — mensagens serão apenas logadas.")

    # -- API -----------------------------------------------------------------
    def _send(self, text: str) -> bool:
        if not self._enabled:
            logger.info("[DRY/OFF] Telegram:\n%s", text)
            return True
        url = f"{API_BASE}/bot{self.settings.telegram_bot_token}/sendMessage"
        try:
            self.http.get_json(
                url,
                params={
                    "chat_id": self.settings.telegram_chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": "false",
                },
            )
            return True
        except Exception as exc:  # notificação não deve derrubar a execução
            logger.error("Falha ao enviar mensagem ao Telegram: %s", exc)
            return False

    # -- mensagens -----------------------------------------------------------
    def notify_new_edital(self, edital: Edital | sqlite3.Row) -> bool:
        return self._send(_format_edital(edital, header="🚨 <b>Novo edital CPSI encontrado</b>"))

    def notify_daily_summary(self, new_count: int, editais: list[sqlite3.Row]) -> bool:
        if new_count == 0:
            return self._send("✅ <b>Radar CPSI</b> — nenhum edital novo hoje.")
        lines = [f"📋 <b>Radar CPSI — resumo diário</b>", f"{new_count} edital(is) novo(s):", ""]
        for row in editais[:20]:
            uf = row["uf"] or "?"
            title = html.escape(_truncate(row["title"], 90))
            link = html.escape(row["link"] or "")
            lines.append(f"• <a href=\"{link}\">{title}</a> — {uf}")
        if new_count > 20:
            lines.append(f"\n… e mais {new_count - 20}.")
        return self._send("\n".join(lines))

    def notify_source_failure(self, source: str, fails: int, error: str) -> bool:
        text = (
            f"⚠️ <b>Radar CPSI — fonte com falha recorrente</b>\n"
            f"Fonte: <code>{html.escape(source)}</code>\n"
            f"Falhas consecutivas: {fails}\n"
            f"Último erro: <code>{html.escape(_truncate(error, 200))}</code>"
        )
        return self._send(text)

    def notify_text(self, text: str) -> bool:
        return self._send(text)


def _format_edital(edital: Edital | sqlite3.Row, header: str) -> str:
    def g(field: str) -> str | None:
        if isinstance(edital, Edital):
            return getattr(edital, field, None)
        try:
            return edital[field]
        except (KeyError, IndexError):
            return None

    title = html.escape(g("title") or "(sem título)")
    orgao = html.escape(g("orgao") or "—")
    uf = html.escape(g("uf") or "—")
    municipio = html.escape(g("municipio") or "—")
    data = html.escape(g("data_publicacao") or "—")
    link = html.escape(g("link") or "")
    source = html.escape(g("source") or "—")
    return (
        f"{header}\n\n"
        f"<b>{title}</b>\n\n"
        f"🏛 Órgão: {orgao}\n"
        f"📍 Local: {municipio} / {uf}\n"
        f"📅 Publicação: {data}\n"
        f"🔎 Fonte: {source}\n"
        f"🔗 <a href=\"{link}\">Abrir edital</a>"
    )


def _truncate(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: limit - 1] + "…"
