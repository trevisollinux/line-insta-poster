"""Alerta de falha.

Ausência de post não é detectável sozinha: se o job morrer calado, ninguém
percebe até abrir o perfil. Por isso toda falha passa por aqui — webhook (se
configurado), Summary do Actions e stderr — antes do exit code diferente de zero.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

from .graph import redact


def alert(message: str, *, webhook: str = "", context: dict | None = None) -> None:
    text = redact(message)
    print(f"ALERTA: {text}", file=sys.stderr)
    write_summary(f"### ⚠️ Instagram — falha\n\n{text}\n")
    if not webhook:
        return
    payload = {"text": f"[LINE STORE] {text}", "context": context or {}}
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        webhook,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            response.read()
    except (urllib.error.URLError, urllib.error.HTTPError) as exc:
        # Falhar o alerta não pode mascarar a falha original.
        print(f"ALERTA: webhook não entregue ({exc})", file=sys.stderr)


def write_summary(markdown: str) -> None:
    """Escreve no Summary do run quando estiver rodando no GitHub Actions."""
    path = os.getenv("GITHUB_STEP_SUMMARY", "").strip()
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(redact(markdown).rstrip() + "\n\n")
    except OSError as exc:  # pragma: no cover - runner sem permissão de escrita
        print(f"summary não escrito: {exc}", file=sys.stderr)
