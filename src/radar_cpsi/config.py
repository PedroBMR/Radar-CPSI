"""Carregamento de configuração (settings + keywords).

Toda a configuração fica fora do código:
  - Palavras-chave e termos de busca: config/keywords.yaml
  - Segredos e flags de runtime: variáveis de ambiente / .env
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Raiz do projeto: .../Radar CPSI/  (dois níveis acima deste arquivo: src/radar_cpsi/config.py)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_KEYWORDS_PATH = PROJECT_ROOT / "config" / "keywords.yaml"
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "radar_cpsi.db"
DEFAULT_CHECKPOINT_DIR = PROJECT_ROOT / "data" / "checkpoints"

# Marco inicial da vigência da LC 182/2021 (90 dias após publicação em 02/06/2021).
LC182_START_DATE = "2021-09-01"


@dataclass(frozen=True)
class KeywordConfig:
    """Termos de filtragem carregados do YAML."""

    cpsi_signals: list[str]
    video_group: list[str]
    query_terms: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path | str | None = None) -> "KeywordConfig":
        path = Path(path) if path else DEFAULT_KEYWORDS_PATH
        with open(path, "r", encoding="utf-8") as fh:
            raw: dict[str, Any] = yaml.safe_load(fh) or {}

        cpsi = [str(t) for t in raw.get("cpsi_signals", [])]
        video = [str(t) for t in raw.get("video_group", [])]
        if not cpsi or not video:
            raise ValueError(
                f"Config de keywords inválida em {path}: "
                "'cpsi_signals' e 'video_group' são obrigatórios e não podem ser vazios."
            )
        return cls(
            cpsi_signals=cpsi,
            video_group=video,
            query_terms=dict(raw.get("query_terms", {}) or {}),
        )

    def query_terms_for(self, source: str) -> list[str]:
        return [str(t) for t in self.query_terms.get(source, [])]


@dataclass(frozen=True)
class Settings:
    """Configuração de runtime (segredos + flags)."""

    telegram_bot_token: str | None
    telegram_chat_id: str | None
    db_path: Path
    checkpoint_dir: Path
    dry_run: bool

    @classmethod
    def from_env(cls) -> "Settings":
        # Carrega .env se existir (silencioso em CI, onde os valores vêm de Secrets).
        try:
            from dotenv import load_dotenv

            load_dotenv(PROJECT_ROOT / ".env")
        except ImportError:  # dotenv é opcional em produção
            pass

        db_path = Path(os.environ.get("RADAR_DB_PATH") or DEFAULT_DB_PATH)
        dry_run = _as_bool(os.environ.get("RADAR_DRY_RUN"))
        return cls(
            telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN") or None,
            telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID") or None,
            db_path=db_path,
            checkpoint_dir=DEFAULT_CHECKPOINT_DIR,
            dry_run=dry_run,
        )

    @property
    def telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)


def _as_bool(value: str | None) -> bool:
    if not value:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on", "sim"}


def configure_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
