"""Fonte secundária: Querido Diário (Open Knowledge Brasil).

API pública que agrega diários oficiais de ~5.570 municípios brasileiros.
Endpoint: https://api.queridodiario.ok.org.br/gazettes

Parâmetros usados: querystring (busca), published_since / published_until (datas),
size + offset (paginação). Cada resultado é um diário (gazette) com trechos
(`excerpts`) — o KeywordMatcher no pipeline confirma se é CPSI+vídeo de verdade.
"""

from __future__ import annotations

import logging
from typing import Any, Iterator

import httpx

from ..config import KeywordConfig
from ..http_client import HttpClient
from ..models import Edital
from .base import Source

logger = logging.getLogger(__name__)

GAZETTES_URL = "https://api.queridodiario.ok.org.br/gazettes"
PAGE_SIZE = 50
MAX_PAGES = 200


class QueridoDiarioSource(Source):
    name = "querido_diario"

    def __init__(self, config: KeywordConfig, http: HttpClient) -> None:
        super().__init__(config, http)
        self._query_terms = config.query_terms_for("querido_diario") or [
            '"solução inovadora" videomonitoramento'
        ]

    def fetch(self, *, since: str | None = None, until: str | None = None) -> Iterator[Edital]:
        seen_urls: set[str] = set()
        for term in self._query_terms:
            yield from self._fetch_term(term, since, until, seen_urls)

    def _fetch_term(
        self, term: str, since: str | None, until: str | None, seen_urls: set[str]
    ) -> Iterator[Edital]:
        offset = 0
        pages = 0
        while pages < MAX_PAGES:
            params: dict[str, Any] = {
                "querystring": term,
                "size": PAGE_SIZE,
                "offset": offset,
                "sort_by": "descending_date",
            }
            if since:
                params["published_since"] = since
            if until:
                params["published_until"] = until

            try:
                payload = self.http.get_json(GAZETTES_URL, params=params)
            except httpx.HTTPStatusError as exc:
                # A API do Querido Diário responde 404 quando o offset ultrapassa
                # o total realmente paginável — tratamos como fim dos resultados.
                if exc.response is not None and exc.response.status_code == 404:
                    logger.info(
                        "Querido Diário: 404 em offset=%d para '%s' — fim da paginação.",
                        offset, term,
                    )
                    break
                raise

            gazettes = payload.get("gazettes") or []
            if not gazettes:
                break

            for gz in gazettes:
                url = gz.get("url")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                edital = self._to_edital(gz)
                if edital is not None:
                    yield edital

            total = int(payload.get("total_gazettes") or 0)
            offset += PAGE_SIZE
            pages += 1
            if offset >= total:
                break

    def _to_edital(self, gz: dict[str, Any]) -> Edital | None:
        url = gz.get("url")
        if not url:
            return None
        territory = gz.get("territory_name") or "Município"
        uf = gz.get("state_code")
        date = gz.get("date")
        excerpts = gz.get("excerpts") or []
        descricao = " [...] ".join(excerpts) if excerpts else None
        title = f"Diário Oficial — {territory}/{uf or '?'} ({date or 's/data'})"
        return Edital(
            source=self.name,
            title=title,
            link=url,
            orgao=f"Prefeitura/Diário de {territory}",
            municipio=territory,
            uf=uf,
            data_publicacao=date,
            descricao=descricao,
            native_id=gz.get("url"),  # URL do PDF é única e estável
        )
