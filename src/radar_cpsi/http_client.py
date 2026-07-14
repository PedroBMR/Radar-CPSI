"""Cliente HTTP com retry e backoff exponencial.

Compartilhado pelas fontes (PNCP, Querido Diário). Trata erros transitórios
(timeouts, 429, 5xx) com espera crescente; erros definitivos sobem imediatamente.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": "Radar-CPSI/0.1 (+https://github.com/) monitor de editais CPSI",
    "Accept": "application/json",
}

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class HttpClient:
    def __init__(
        self,
        *,
        timeout: float = 30.0,
        max_retries: int = 6,
        backoff_base: float = 1.5,
        min_interval: float = 0.5,
    ) -> None:
        # O PNCP às vezes derruba conexões keep-alive (RemoteProtocolError).
        # Limitamos keepalive a poucos segundos para forçar conexão nova e
        # reduzir a chance de reaproveitar um socket já fechado pelo servidor.
        self._client = httpx.Client(
            timeout=timeout,
            headers=DEFAULT_HEADERS,
            follow_redirects=True,
            limits=httpx.Limits(max_keepalive_connections=5, keepalive_expiry=5.0),
        )
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.min_interval = min_interval  # rate-limit básico entre requisições
        self._last_request_at = 0.0

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "HttpClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request_at = time.monotonic()

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            try:
                resp = self._client.get(url, params=params)
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                wait = self.backoff_base ** attempt
                logger.warning(
                    "GET %s falhou (%s), tentativa %d/%d, aguardando %.1fs",
                    url, type(exc).__name__, attempt, self.max_retries, wait,
                )
                time.sleep(wait)
                continue

            if resp.status_code in RETRYABLE_STATUS:
                retry_after = _parse_retry_after(resp)
                wait = retry_after if retry_after is not None else self.backoff_base ** attempt
                logger.warning(
                    "GET %s retornou %d, tentativa %d/%d, aguardando %.1fs",
                    url, resp.status_code, attempt, self.max_retries, wait,
                )
                last_exc = httpx.HTTPStatusError(
                    f"status {resp.status_code}", request=resp.request, response=resp
                )
                time.sleep(wait)
                continue

            resp.raise_for_status()
            return resp.json()

        assert last_exc is not None
        raise last_exc


def _parse_retry_after(resp: httpx.Response) -> float | None:
    value = resp.headers.get("Retry-After")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None
