"""Fonte primária: PNCP — Portal Nacional de Contratações Públicas.

Usa o endpoint de busca full-text que alimenta o portal público
(https://pncp.gov.br/api/search/). Filtramos por `tipos_documento=edital` e por
termos de busca (config.query_terms["pncp"]), com paginação e filtro de data
client-side sobre `data_publicacao_pncp`.

Observação de validação: a API `consulta/v1` expõe um filtro por
`codigoModalidadeContratacao`, mas nenhum código fixo corresponde a "CPSI" — por
isso a busca textual é a abordagem correta. O filtro fino CPSI+vídeo é aplicado
depois pelo KeywordMatcher no pipeline.
"""

from __future__ import annotations

import logging
from typing import Any, Iterator

from ..config import KeywordConfig
from ..http_client import HttpClient
from ..models import Edital
from .base import Source

logger = logging.getLogger(__name__)

SEARCH_URL = "https://pncp.gov.br/api/search/"
PORTAL_BASE = "https://pncp.gov.br"
PAGE_SIZE = 50
MAX_PAGES = 200  # trava de segurança para o backfill (50 * 200 = 10k por termo)


class PncpSource(Source):
    name = "pncp"

    def __init__(self, config: KeywordConfig, http: HttpClient) -> None:
        super().__init__(config, http)
        self._query_terms = config.query_terms_for("pncp") or ["solução inovadora"]

    def fetch(self, *, since: str | None = None, until: str | None = None) -> Iterator[Edital]:
        seen_ids: set[str] = set()
        for term in self._query_terms:
            yield from self._fetch_term(term, since, until, seen_ids)

    def _fetch_term(
        self, term: str, since: str | None, until: str | None, seen_ids: set[str]
    ) -> Iterator[Edital]:
        page = 1
        while page <= MAX_PAGES:
            params = {
                "q": term,
                "tipos_documento": "edital",
                "pagina": page,
                "tam_pagina": PAGE_SIZE,
                "ordenacao": "-data",  # mais recentes primeiro
            }
            payload = self.http.get_json(SEARCH_URL, params=params)
            items = payload.get("items") or []
            if not items:
                break

            stop_page = False
            for item in items:
                pub = _date_only(item.get("data_publicacao_pncp"))
                # Como vem ordenado por data desc, se passamos do `since` podemos parar.
                if since and pub and pub < since:
                    stop_page = True
                    continue
                if until and pub and pub > until:
                    continue
                edital = self._to_edital(item)
                if edital is None:
                    continue
                if edital.native_id and edital.native_id in seen_ids:
                    continue
                if edital.native_id:
                    seen_ids.add(edital.native_id)
                yield edital

            total = int(payload.get("total") or 0)
            if stop_page or page * PAGE_SIZE >= total:
                break
            page += 1

    def _to_edital(self, item: dict[str, Any]) -> Edital | None:
        title = (item.get("title") or "").strip()
        if not title:
            return None
        item_url = item.get("item_url") or ""
        link = f"{PORTAL_BASE}{item_url}" if item_url.startswith("/") else (item_url or PORTAL_BASE)
        return Edital(
            source=self.name,
            title=title,
            link=link,
            orgao=item.get("orgao_nome"),
            municipio=item.get("municipio_nome"),
            uf=item.get("uf"),
            data_publicacao=_date_only(item.get("data_publicacao_pncp")),
            descricao=item.get("description"),
            native_id=item.get("numero_controle_pncp") or item.get("id"),
        )


def _date_only(value: str | None) -> str | None:
    if not value:
        return None
    return str(value)[:10]  # "2026-07-10T11:47:12" -> "2026-07-10"
