"""Motor de palavras-chave configurável.

Regra de match relevante:
    (tem algum termo de CPSI)  E  (tem algum termo de videomonitoramento)

Comparação é insensível a acentos e a maiúsculas/minúsculas, e respeita limites
de palavra para termos alfanuméricos (evita casar "cameras" dentro de "camerata").
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .config import KeywordConfig


def normalize(text: str) -> str:
    """Minúsculas + remoção de acentos, para comparação robusta."""
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text)
    without_accents = "".join(ch for ch in nfkd if not unicodedata.combining(ch))
    return without_accents.lower()


def _compile_term(term: str) -> re.Pattern[str]:
    """Compila um termo em regex normalizada, com limites de palavra flexíveis.

    Espaços no termo casam com qualquer sequência de espaços em branco, para
    tolerar quebras de linha e múltiplos espaços comuns em PDFs/diários.
    """
    norm = normalize(term).strip()
    # Divide em tokens e junta com \s+ (um ou mais espaços em branco).
    tokens = [re.escape(tok) for tok in norm.split()]
    body = r"\s+".join(tokens)
    # \b só funciona bem em bordas alfanuméricas; usamos lookarounds para não
    # exigir borda quando o termo começa/termina com caractere não-palavra.
    left = r"(?<![0-9a-z])" if norm[:1].isalnum() else ""
    right = r"(?![0-9a-z])" if norm[-1:].isalnum() else ""
    return re.compile(left + body + right, re.IGNORECASE)


@dataclass(frozen=True)
class MatchResult:
    """Resultado da avaliação de um texto contra os grupos de keywords."""

    is_match: bool
    cpsi_hits: list[str]
    video_hits: list[str]

    @property
    def summary(self) -> str:
        return (
            f"CPSI[{', '.join(self.cpsi_hits) or '-'}] "
            f"VIDEO[{', '.join(self.video_hits) or '-'}]"
        )


class KeywordMatcher:
    """Avalia textos contra os grupos configurados de palavras-chave."""

    def __init__(self, config: KeywordConfig) -> None:
        self._config = config
        self._cpsi = [(t, _compile_term(t)) for t in config.cpsi_signals]
        self._video = [(t, _compile_term(t)) for t in config.video_group]

    @classmethod
    def from_default(cls) -> "KeywordMatcher":
        return cls(KeywordConfig.load())

    def _hits(self, normalized: str, patterns: list[tuple[str, re.Pattern[str]]]) -> list[str]:
        return [term for term, pat in patterns if pat.search(normalized)]

    def evaluate(self, *texts: str) -> MatchResult:
        """Avalia um ou mais trechos de texto (título, descrição, excerpts...).

        Os textos são concatenados; um match pode vir de campos diferentes.
        """
        normalized = normalize(" \n ".join(t for t in texts if t))
        cpsi_hits = self._hits(normalized, self._cpsi)
        video_hits = self._hits(normalized, self._video)
        is_match = bool(cpsi_hits) and bool(video_hits)
        return MatchResult(is_match=is_match, cpsi_hits=cpsi_hits, video_hits=video_hits)
