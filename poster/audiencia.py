"""Quando os seguidores estão online — o dado por trás do "melhor horário".

`online_followers` é métrica de audiência da conta, não de post: devolve, para
cada dia, quantos seguidores estavam online em cada hora. A API entrega em UTC;
aqui converte para o fuso da loja.

Vale lembrar o que ela mede: presença, não interesse. Audiência online às 21h não
garante que post às 21h renda mais — só diz onde há gente. O que rende é outra
pergunta, e essa o histórico dos posts responde melhor.
"""
from __future__ import annotations

from collections import defaultdict
from statistics import median

from .graph import GraphClient, GraphError

BRT_OFFSET = -3  # America/Sao_Paulo


def online_followers(client: GraphClient, ig_user_id: str) -> list[dict[str, int]]:
    """Série bruta: uma entrada por dia, com contagem por hora (UTC)."""
    try:
        payload = client.get(
            f"{ig_user_id}/insights",
            {"metric": "online_followers", "period": "lifetime"},
        )
    except GraphError as exc:
        raise GraphError(
            f"online_followers indisponível: {exc}. A métrica foi descontinuada em "
            "versões recentes da API para algumas contas; nesse caso o histórico "
            "dos próprios posts é a fonte que resta."
        ) from exc

    linhas = payload.get("data") or []
    if not linhas:
        return []
    return [
        {str(hora): int(valor) for hora, valor in (ponto.get("value") or {}).items()}
        for ponto in (linhas[0].get("values") or [])
    ]


def por_hora_local(
    serie: list[dict[str, int]], *, offset: int = BRT_OFFSET
) -> dict[int, float]:
    """Mediana de seguidores online por hora local.

    Mediana e não média pelo mesmo motivo do ranking: um dia atípico não pode
    decidir o horário de publicação do mês inteiro.
    """
    por_hora: dict[int, list[int]] = defaultdict(list)
    for dia in serie:
        for hora_utc, quantidade in dia.items():
            local = (int(hora_utc) + offset) % 24
            por_hora[local].append(quantidade)
    return {hora: median(valores) for hora, valores in sorted(por_hora.items())}


def melhores_horas(por_hora: dict[int, float], *, quantas: int = 3) -> list[tuple[int, float]]:
    return sorted(por_hora.items(), key=lambda par: par[1], reverse=True)[:quantas]
