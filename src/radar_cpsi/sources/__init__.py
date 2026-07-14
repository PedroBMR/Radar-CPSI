"""Fontes de dados plugáveis do Radar CPSI.

Cada fonte implementa a interface `Source` (ver base.py). Para adicionar uma nova
fonte, crie um módulo aqui, implemente `Source` e registre em `build_sources()`.
"""

from __future__ import annotations

from ..config import KeywordConfig
from ..http_client import HttpClient
from .base import Source
from .pncp import PncpSource
from .querido_diario import QueridoDiarioSource


def build_sources(config: KeywordConfig, http: HttpClient) -> list[Source]:
    """Instancia todas as fontes ativas, na ordem de prioridade (PNCP primeiro)."""
    return [
        PncpSource(config, http),
        QueridoDiarioSource(config, http),
    ]


__all__ = ["Source", "PncpSource", "QueridoDiarioSource", "build_sources"]
