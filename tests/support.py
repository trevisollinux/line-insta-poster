"""Dublês usados pelos testes — nenhum teste toca a rede."""
from __future__ import annotations

import json
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class FakeClient:
    """Responde `get`/`post` a partir de respostas programadas por (método, caminho)."""

    def __init__(self, respostas: dict[tuple[str, str], Any] | None = None) -> None:
        self.respostas = respostas or {}
        self.chamadas: list[tuple[str, str, dict]] = []

    def get(self, path: str, params: dict | None = None) -> dict:
        return self._responder("GET", path, params or {})

    def post(self, path: str, params: dict | None = None) -> dict:
        return self._responder("POST", path, params or {})

    def _responder(self, metodo: str, path: str, params: dict) -> dict:
        self.chamadas.append((metodo, path, params))
        chave = (metodo, path)
        resposta = self.respostas.get(chave)
        if resposta is None:
            raise AssertionError(f"chamada inesperada: {metodo} {path} {params}")
        if isinstance(resposta, list):
            if not resposta:
                raise AssertionError(f"respostas esgotadas para {metodo} {path}")
            item = resposta.pop(0)
        else:
            item = resposta
        if isinstance(item, Exception):
            raise item
        return item

    def paths(self, metodo: str | None = None) -> list[str]:
        return [c[1] for c in self.chamadas if metodo is None or c[0] == metodo]


class FakeTransport:
    """Transporte HTTP falso no formato que `GraphClient` espera."""

    def __init__(self, respostas: list[tuple[int, Any]]) -> None:
        self.respostas = list(respostas)
        self.requisicoes: list[tuple[str, str, bytes | None, dict]] = []

    def __call__(self, metodo: str, url: str, body: bytes | None, headers: dict):
        self.requisicoes.append((metodo, url, body, headers))
        if not self.respostas:
            raise AssertionError(f"transporte sem resposta para {metodo} {url}")
        status, payload = self.respostas.pop(0)
        if isinstance(payload, Exception):
            raise payload
        corpo = payload if isinstance(payload, str) else json.dumps(payload)
        return status, corpo


def item(**kwargs) -> dict:
    """Item de fila válido, sobrescrevível campo a campo."""
    base = {
        "id": "item-1",
        "media_type": "IMAGE",
        "url": "https://media.example/foto.jpg",
        "caption": "legenda",
        "reviewed_price": True,
    }
    base.update(kwargs)
    return base
