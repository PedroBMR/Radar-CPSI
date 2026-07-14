"""Modelo de domínio: um edital encontrado por uma fonte."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Edital:
    """Representa um edital captado de uma fonte.

    `dedup_key` é o identificador estável usado para deduplicação. Quando a fonte
    fornece um ID nativo (ex.: numero_controle_pncp), usamos ele; caso contrário,
    derivamos um hash a partir de fonte + link + título.
    """

    source: str                    # "pncp" | "querido_diario" | ...
    title: str
    link: str
    orgao: str | None = None       # órgão / entidade
    municipio: str | None = None
    uf: str | None = None
    data_publicacao: str | None = None   # ISO date/datetime da publicação (string da fonte)
    descricao: str | None = None
    native_id: str | None = None   # ID nativo da fonte, se houver
    origem: str = "diario"         # "diario" | "backfill"
    data_captura: str = field(default_factory=_now_iso)

    # Preenchidos pelo matcher antes de salvar (para auditoria).
    cpsi_hits: str | None = None
    video_hits: str | None = None

    @property
    def dedup_key(self) -> str:
        if self.native_id:
            base = f"{self.source}:{self.native_id}"
        else:
            base = f"{self.source}:{self.link}:{self.title}"
        return hashlib.sha256(base.encode("utf-8")).hexdigest()

    def searchable_text(self) -> tuple[str, ...]:
        """Campos que devem ser avaliados pelo KeywordMatcher."""
        return tuple(
            t for t in (self.title, self.descricao, self.orgao) if t
        )
