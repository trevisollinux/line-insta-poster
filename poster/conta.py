"""Métricas da conta — o único lugar onde alcance vira negócio.

O histórico dos posts diz quantas pessoas viram cada publicação. Não diz
quantos seguidores a conta tem, quantas pessoas abriram o perfil, nem quantas
clicaram no link da bio. Sem esses três, não dá para saber se 982 de alcance é
bom ou ruim para o tamanho da conta, nem se alguma coisa disso virou visita à
loja.

Diferente das métricas de story, estas **não somem**: a API devolve os últimos
dias a cada chamada. Por isso a captura pede uma janela de dias e regrava todas
as datas que vierem — um dia perdido pelo agendador se conserta sozinho na
captura seguinte, o que importa num cron que entrega 25%.
"""
from __future__ import annotations

import csv
import os
from datetime import datetime, timedelta, timezone

from .graph import GraphClient, GraphError

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(REPO_ROOT, "state", "conta.csv")

# Métricas de conta por dia. A lista é preferência, não contrato: a API recusa
# o pedido inteiro por causa de uma métrica que a conta não tem, e o nome da
# recusada vem na mensagem de erro — daí a negociação, igual à dos stories.
#
# O que cada uma responde, e é por isso que estão aqui:
#   reach              — quantas pessoas distintas foram alcançadas no dia
#   profile_views      — quantas abriram o perfil
#   website_clicks     — quantas clicaram no link da bio (a ponte para a loja)
#   accounts_engaged   — quantas interagiram de alguma forma
#   total_interactions — o volume de interação
METRICAS = (
    "reach",
    "profile_views",
    "website_clicks",
    "accounts_engaged",
    "total_interactions",
)
METRICAS_MINIMAS = ("reach",)

CAMPOS = (
    "data",
    "seguidores",
    "publicacoes",
    *METRICAS,
    "capturado_em",
)


def perfil(client: GraphClient, ig_user_id: str) -> dict[str, int]:
    """Retrato de agora: seguidores e total de publicações.

    Não é série histórica — é o valor no instante da leitura. A série nasce de
    guardar um retrato por dia, que é o que a captura faz.
    """
    payload = client.get(ig_user_id, {"fields": "followers_count,media_count"})
    return {
        "seguidores": int(payload.get("followers_count") or 0),
        "publicacoes": int(payload.get("media_count") or 0),
    }


def insights(
    client: GraphClient,
    ig_user_id: str,
    *,
    dias: int = 7,
    metricas: tuple[str, ...] = METRICAS,
    agora: datetime | None = None,
) -> dict[str, dict[str, int]]:
    """Métricas por data local da API, no formato {data: {metrica: valor}}.

    Pede uma janela em vez do dia de ontem: assim a captura que não rodou
    ontem se conserta hoje, sem ninguém perceber. É o contrário do coletor de
    story, onde o que não foi lido a tempo está perdido para sempre.
    """
    fim = (agora or datetime.now(timezone.utc)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    inicio = fim - timedelta(days=dias)

    tentativa = list(metricas)
    ultimo_erro: GraphError | None = None
    for _ in range(3):
        if not tentativa:
            break
        try:
            payload = client.get(
                f"{ig_user_id}/insights",
                {
                    "metric": ",".join(tentativa),
                    "period": "day",
                    "since": int(inicio.timestamp()),
                    "until": int(fim.timestamp()),
                },
            )
        except GraphError as exc:
            ultimo_erro = exc
            recusadas = [m for m in tentativa if m in str(exc)]
            if recusadas:
                tentativa = [m for m in tentativa if m not in recusadas]
                continue
            if tentativa != list(METRICAS_MINIMAS):
                tentativa = list(METRICAS_MINIMAS)
                continue
            break
        return _por_data(payload)

    if ultimo_erro is not None:
        raise ultimo_erro
    return {}


def _por_data(payload: dict) -> dict[str, dict[str, int]]:
    saida: dict[str, dict[str, int]] = {}
    for linha in payload.get("data") or []:
        nome = str(linha.get("name") or "")
        for ponto in linha.get("values") or []:
            bruto = ponto.get("value")
            if not isinstance(bruto, (int, float)):
                continue
            fim = str(ponto.get("end_time") or "")
            if not fim:
                continue
            # `end_time` é o fim da janela: 2026-09-20T07:00:00+0000 fecha o
            # dia 19. Um dia a menos, senão a série inteira fica deslocada.
            data = (_parse(fim) - timedelta(days=1)).date().isoformat()
            saida.setdefault(data, {})[nome] = int(bruto)
    return saida


def _parse(bruto: str) -> datetime:
    texto = bruto.replace("Z", "+00:00")
    if len(texto) >= 5 and texto[-5] in "+-" and ":" not in texto[-5:]:
        texto = f"{texto[:-2]}:{texto[-2:]}"
    return datetime.fromisoformat(texto)


def carregar(path: str = CSV_PATH) -> list[dict[str, str]]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def mesclar(
    existentes: list[dict[str, str]], novas: list[dict[str, str]]
) -> list[dict[str, str]]:
    """Uma linha por data, valendo a leitura mais recente.

    Aqui não vale o maior, ao contrário das métricas de story: seguidor pode
    cair, e uma leitura feita no meio do dia é parcial de propósito. O último
    valor lido é o mais próximo do fechado.
    """
    por_data = {linha.get("data", ""): dict(linha) for linha in existentes}
    for nova in novas:
        data = nova.get("data", "")
        if not data:
            continue
        combinada = dict(por_data.get(data) or {})
        combinada.update({k: v for k, v in nova.items() if v not in ("", None)})
        por_data[data] = combinada
    return [por_data[d] for d in sorted(por_data)]


def gravar(linhas: list[dict[str, str]], path: str = CSV_PATH) -> list[dict[str, str]]:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(CAMPOS))
        writer.writeheader()
        for linha in linhas:
            writer.writerow({campo: linha.get(campo, "") for campo in CAMPOS})
    return linhas


def montar_linhas(
    series: dict[str, dict[str, int]],
    retrato: dict[str, int],
    *,
    agora: datetime | None = None,
) -> list[dict[str, str]]:
    """Junta a série de métricas com o retrato do perfil.

    O retrato é de agora e entra só na data mais recente da série — carimbar o
    número de seguidores de hoje em todos os dias da janela inventaria um
    histórico que ninguém mediu.
    """
    captura = (agora or datetime.now(timezone.utc)).astimezone(timezone.utc)
    linhas: list[dict[str, str]] = []
    datas = sorted(series)
    for data in datas:
        linha: dict[str, str] = {"data": data, "capturado_em": captura.isoformat(timespec="seconds")}
        for metrica, valor in series[data].items():
            linha[metrica] = str(valor)
        if data == datas[-1]:
            for campo, valor in retrato.items():
                linha[campo] = str(valor)
        linhas.append(linha)
    return linhas
