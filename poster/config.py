"""Configuração por variável de ambiente — mesmo padrão dos scripts de sync.

Env obrigatórias na publicação:
- IG_USER_ID        id da conta Instagram Business
- IG_ACCESS_TOKEN   token long-lived do usuário com acesso à Página

Opcionais:
- IG_DRY_RUN            'true' valida a fila e escolhe o item sem chamar a API
- IG_SELECTION          'weighted' (padrão) ou 'order'
- IG_POLL_INTERVAL      segundos entre checagens do container (padrão 60)
- IG_POLL_TIMEOUT       teto do polling em segundos (padrão 300)
- IG_GRAPH_VERSION      versão da Graph API (padrão v21.0)
- IG_ALERT_WEBHOOK      URL que recebe POST JSON quando algo falha
- IG_MIN_QUOTA_LEFT     margem do limite de 25 posts/24h (padrão 1)
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from .graph import GRAPH_VERSION


def env_str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def env_int(name: str, default: int) -> int:
    try:
        return int(env_str(name, str(default)) or default)
    except ValueError:
        return default


def env_bool(name: str, default: bool = False) -> bool:
    return env_str(name, str(default)).lower() in {"1", "true", "yes", "y"}


@dataclass(frozen=True)
class PublishConfig:
    ig_user_id: str
    access_token: str
    dry_run: bool = False
    selection_mode: str = "weighted"
    poll_interval: int = 60
    poll_timeout: int = 300
    graph_version: str = GRAPH_VERSION
    alert_webhook: str = ""
    min_quota_left: int = 1

    @classmethod
    def from_env(cls, *, dry_run: bool = False) -> "PublishConfig":
        dry_run = dry_run or env_bool("IG_DRY_RUN")
        ig_user_id = env_str("IG_USER_ID")
        access_token = env_str("IG_ACCESS_TOKEN")
        missing = [
            name
            for name, value in (("IG_USER_ID", ig_user_id), ("IG_ACCESS_TOKEN", access_token))
            if not value
        ]
        if missing and not dry_run:
            raise RuntimeError(f"variáveis obrigatórias ausentes: {', '.join(missing)}")
        return cls(
            ig_user_id=ig_user_id,
            access_token=access_token,
            dry_run=dry_run,
            selection_mode=env_str("IG_SELECTION", "weighted").lower() or "weighted",
            poll_interval=env_int("IG_POLL_INTERVAL", 60),
            poll_timeout=env_int("IG_POLL_TIMEOUT", 300),
            graph_version=env_str("IG_GRAPH_VERSION", GRAPH_VERSION),
            alert_webhook=env_str("IG_ALERT_WEBHOOK"),
            min_quota_left=env_int("IG_MIN_QUOTA_LEFT", 1),
        )
