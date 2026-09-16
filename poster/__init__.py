"""line-insta-poster — automação de publicação no Instagram da LINE STORE.

A fila fica versionada em `queue/posts.yaml`, o que já saiu em
`state/published.json`, e o GitHub Actions é o agendador. Autenticação via
Facebook Login for Business (`graph.facebook.com`), com a mídia hospedada em
bucket público — a Graph API busca a URL na hora de criar o container.

Entrada de linha de comando: `python -m poster.cli --help`.
"""
from __future__ import annotations

import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

__all__ = [
    "REPO_ROOT",
    "alerts",
    "config",
    "curadoria",
    "graph",
    "publisher",
    "queue_file",
    "selection",
    "state",
    "token",
]
