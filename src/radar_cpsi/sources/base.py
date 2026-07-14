"""Interface comum para todas as fontes de dados."""

from __future__ import annotations

import abc
from typing import Iterator

from ..config import KeywordConfig
from ..http_client import HttpClient
from ..models import Edital


class Source(abc.ABC):
    """Contrato que toda fonte deve implementar.

    Uma fonte sabe consultar sua API/site e emitir objetos `Edital` brutos
    (ainda não filtrados pelo KeywordMatcher — a filtragem é responsabilidade
    do pipeline, para manter a fonte simples e testável).
    """

    #: identificador curto e estável, usado como valor da coluna `source`.
    name: str = "base"

    def __init__(self, config: KeywordConfig, http: HttpClient) -> None:
        self.config = config
        self.http = http

    @abc.abstractmethod
    def fetch(self, *, since: str | None = None, until: str | None = None) -> Iterator[Edital]:
        """Emite editais publicados no intervalo [since, until].

        `since`/`until` são datas ISO (YYYY-MM-DD). Quando None, a fonte usa seu
        padrão (ex.: coleta diária recente). Deve tratar paginação internamente.
        Pode levantar exceção em caso de falha — o pipeline captura e isola.
        """
        raise NotImplementedError
