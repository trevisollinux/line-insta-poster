"""Memória das falhas de publicação — para uma mídia ruim não travar a fila.

O item só entra em `state/published.json` depois de publicar. É a regra certa:
gravar antes geraria post perdido em silêncio. Mas ela tem um efeito colateral
que só apareceu em 23/09, com uma foto que a Meta recusava: o item continua
sendo o primeiro elegível, então **toda** execução seguinte escolhe a mesma
mídia, falha igual, e a fila para para sempre. Um item ruim segurava os outros.

Aqui ficam as falhas para que a seleção possa pular:

- Falhou agora: fica **em espera** por algumas horas. Erro transitório da API
  não merece quarentena, e a espera dá tempo de ele passar sozinho.
- Falhou muitas vezes: entra em **quarentena** e sai da rotação até alguém
  olhar. Nesse ponto não é mais transitório.

Publicar com sucesso apaga o registro: o histórico de falhas só interessa
enquanto explica por que um item não está saindo.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

from . import REPO_ROOT

FALHAS_PATH = os.path.join(REPO_ROOT, "state", "falhas.json")

# Quanto tempo um item espera depois de falhar. Seis horas cobrem a janela
# entre dois disparos de story — o item não volta na execução seguinte, mas
# volta no dia seguinte se o problema tiver passado.
ESPERA_HORAS = 6

# Falhas acumuladas até a quarentena. Três é o bastante para separar "a API
# teve um soluço" de "esta mídia não serve".
LIMITE = 3


def carregar(path: str = FALHAS_PATH) -> dict[str, dict]:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as handle:
        conteudo = handle.read().strip()
    if not conteudo:
        return {}
    dados = json.loads(conteudo)
    registros = dados.get("falhas") if isinstance(dados, dict) else None
    return registros if isinstance(registros, dict) else {}


def gravar(registros: dict[str, dict], path: str = FALHAS_PATH) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = {
        "version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "falhas": registros,
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def registrar(
    registros: dict[str, dict],
    item_id: str,
    motivo: str,
    *,
    agora: datetime | None = None,
) -> dict[str, dict]:
    momento = (agora or datetime.now(timezone.utc)).astimezone(timezone.utc)
    atual = dict(registros.get(item_id) or {})
    atual["tentativas"] = int(atual.get("tentativas") or 0) + 1
    atual["ultimo_erro"] = motivo
    atual["em"] = momento.isoformat(timespec="seconds")
    novos = dict(registros)
    novos[item_id] = atual
    return novos


def limpar(registros: dict[str, dict], item_id: str) -> dict[str, dict]:
    novos = dict(registros)
    novos.pop(item_id, None)
    return novos


def _quando(registro: dict) -> datetime | None:
    bruto = str(registro.get("em") or "")
    if not bruto:
        return None
    try:
        return datetime.fromisoformat(bruto.replace("Z", "+00:00"))
    except ValueError:
        return None


def em_quarentena(registro: dict, *, limite: int = LIMITE) -> bool:
    return int(registro.get("tentativas") or 0) >= limite


def em_espera(
    registro: dict, *, agora: datetime | None = None, horas: int = ESPERA_HORAS
) -> bool:
    quando = _quando(registro)
    if quando is None:
        return False
    momento = (agora or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return momento - quando < timedelta(hours=horas)


def bloqueados(
    registros: dict[str, dict],
    *,
    agora: datetime | None = None,
    limite: int = LIMITE,
    horas: int = ESPERA_HORAS,
) -> dict[str, str]:
    """Itens que a seleção deve pular agora, com o motivo de cada um."""
    saida: dict[str, str] = {}
    for item_id, registro in registros.items():
        tentativas = int(registro.get("tentativas") or 0)
        if em_quarentena(registro, limite=limite):
            saida[item_id] = (
                f"em quarentena após {tentativas} falha(s): "
                f"{registro.get('ultimo_erro') or 'sem motivo registrado'}"
            )
        elif em_espera(registro, agora=agora, horas=horas):
            saida[item_id] = f"falhou há pouco ({tentativas}x) — esperando {horas}h"
    return saida
