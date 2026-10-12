"""Histórico de desempenho dos Reels — views, não só curtida.

Pelo acesso de anúncios só aparecem curtidas e comentários, e curtida mede
pouco: o Reel que mais curtiram não é necessariamente o que mais gente viu,
nem o que levou gente ao perfil. A rodada de reposts (a cada duas semanas)
precisa escolher por número, não por impressão.

Diferente do story, Reel não expira: a API devolve as insights dele a qualquer
momento. O que se perde sem captura periódica é a *curva* — quantas views ele
tinha no dia seguinte, numa semana. Sem ela não dá para comparar um Reel de
ontem com um de três semanas atrás (o mais velho sempre ganha no total), nem
saber quando um Reel para de crescer.

Por isso dois arquivos, como nos stories:

- `state/reels_metrics.csv`: uma linha por Reel, com a leitura mais completa;
- `state/reels_curva.csv`: um ponto por Reel por dia de vida (D+1, D+2…).

A coluna `origem` diz se o Reel saiu pelo robô (está em state/published.json)
ou foi postado à mão — os dois convivem no perfil e merecem ser comparados.
"""
from __future__ import annotations

import csv
import os
from datetime import datetime, timedelta, timezone

from . import curadoria
from .graph import GraphClient
from .metricas_stories import _maior, insights as _insights
from .state import PublishedEntry

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(REPO_ROOT, "state", "reels_metrics.csv")
CURVA_PATH = os.path.join(REPO_ROOT, "state", "reels_curva.csv")

BRT_OFFSET = -3  # America/Sao_Paulo

# Reel continua ganhando view por semanas, mas o grosso chega no primeiro mês.
# Janela maior só gasta chamada de API medindo Reel que já parou.
JANELA_DIAS = 60

# Métricas de Reel na v22+. `plays` e `ig_reels_aggregated_all_plays_count`
# foram descontinuadas em favor de `views`. `profile_visits` e `follows` são as
# que dizem se o Reel trouxe gente para a loja — nem toda conta/versão as
# entrega para Reel, e aí a negociação de metricas_stories.insights as tira da
# lista em vez de perder a leitura inteira.
METRICAS = (
    "views",
    "reach",
    "likes",
    "comments",
    "shares",
    "saved",
    "total_interactions",
    "profile_visits",
    "follows",
    "ig_reels_avg_watch_time",
)
METRICAS_MINIMAS = ("reach", "likes")

CAMPOS = (
    "media_id",
    "publicado_utc",
    "data_local",
    "hora_local",
    "origem",
    "item_id",
    "idade_dias",
    *METRICAS,
    "permalink",
    "legenda",
    "capturado_em",
)

METRICAS_CURVA = ("views", "reach", "likes", "shares", "saved", "profile_visits")
CAMPOS_CURVA = ("media_id", "data_local", "idade_dias", "capturado_em", *METRICAS_CURVA)

ORIGEM_ROBO = "robo"
ORIGEM_MANUAL = "manual"


def listar_reels(
    client: GraphClient,
    ig_user_id: str,
    *,
    janela_dias: int = JANELA_DIAS,
    agora: datetime | None = None,
) -> list[curadoria.MediaPost]:
    """Os Reels publicados dentro da janela, do mais novo para o mais velho."""
    agora = agora or datetime.now(timezone.utc)
    posts, _ = curadoria.collect_media(
        client, ig_user_id, since=agora - timedelta(days=janela_dias), max_pages=3
    )
    return [post for post in posts if post.media_product_type == "REELS" and post.id]


def insights(client: GraphClient, media_id: str) -> dict[str, int]:
    return _insights(client, media_id, metricas=METRICAS, minimas=METRICAS_MINIMAS)


def origens(published: list[PublishedEntry]) -> dict[str, str]:
    """media_id → item_id do que o robô publicou. O que não está aqui foi à mão."""
    return {entrada.media_id: entrada.item_id for entrada in published if entrada.media_id}


def _idade_dias(publicado: datetime, captura: datetime) -> int:
    # Arredondada, não truncada: o cron diário atrasa algumas horas de um dia
    # para o outro, e truncar faria um Reel pular de D+0 para D+2.
    return round((captura - publicado).total_seconds() / 86400)


def montar_linha(
    post: curadoria.MediaPost,
    medidas: dict[str, int],
    *,
    robo: dict[str, str],
    offset: int = BRT_OFFSET,
    agora: datetime | None = None,
) -> dict[str, str]:
    captura = (agora or datetime.now(timezone.utc)).astimezone(timezone.utc)
    publicado = post.timestamp.astimezone(timezone.utc)
    local = publicado + timedelta(hours=offset)
    legenda = " ".join(post.caption.split())
    linha = {
        "media_id": post.id,
        "publicado_utc": publicado.isoformat(timespec="seconds"),
        "data_local": local.strftime("%Y-%m-%d"),
        "hora_local": local.strftime("%H:%M"),
        "origem": ORIGEM_ROBO if post.id in robo else ORIGEM_MANUAL,
        "item_id": robo.get(post.id, ""),
        "idade_dias": str(_idade_dias(publicado, captura)),
        "permalink": post.permalink,
        "legenda": legenda[:80],
        "capturado_em": captura.isoformat(timespec="seconds"),
    }
    for metrica in METRICAS:
        valor = medidas.get(metrica)
        linha[metrica] = "" if valor is None else str(valor)
    # Curtida e comentário vêm de graça na listagem; se a insight falhou, a
    # linha ainda guarda isso em vez de ficar em branco.
    if not linha["likes"]:
        linha["likes"] = str(post.like_count)
    if not linha["comments"]:
        linha["comments"] = str(post.comments_count)
    return linha


def montar_ponto(linha: dict[str, str]) -> dict[str, str]:
    return {campo: linha.get(campo, "") for campo in CAMPOS_CURVA}


def carregar(path: str = CSV_PATH) -> list[dict[str, str]]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return [dict(linha) for linha in csv.DictReader(handle)]


def mesclar(
    existentes: list[dict[str, str]], novas: list[dict[str, str]]
) -> list[dict[str, str]]:
    """Uma linha por Reel. Contadores ficam com o maior valor já lido.

    Views e alcance só sobem; leitura menor é oscilação da API. A exceção é o
    tempo médio assistido, que pode cair de verdade — esse fica com o mais
    recente, como os campos descritivos.
    """
    por_id = {linha.get("media_id", ""): dict(linha) for linha in existentes}
    for nova in novas:
        media_id = nova.get("media_id", "")
        if not media_id:
            continue
        antiga = por_id.get(media_id)
        if antiga is None:
            por_id[media_id] = dict(nova)
            continue
        combinada = dict(antiga)
        combinada.update({k: v for k, v in nova.items() if v not in ("", None)})
        for metrica in METRICAS:
            if metrica == "ig_reels_avg_watch_time":
                continue
            combinada[metrica] = _maior(antiga.get(metrica), nova.get(metrica))
        por_id[media_id] = combinada
    return list(por_id.values())


def gravar(linhas: list[dict[str, str]], path: str = CSV_PATH) -> list[dict[str, str]]:
    ordenadas = sorted(linhas, key=lambda linha: linha.get("publicado_utc", ""))
    _escrever(path, CAMPOS, ordenadas)
    return ordenadas


def carregar_curva(path: str = CURVA_PATH) -> list[dict[str, str]]:
    return carregar(path)


def anexar_curva(
    existentes: list[dict[str, str]], pontos: list[dict[str, str]]
) -> list[dict[str, str]]:
    """Um ponto por (Reel, dia de vida); colisão vira o maior valor."""
    por_chave = {
        (linha.get("media_id", ""), linha.get("idade_dias", "")): dict(linha)
        for linha in existentes
    }
    for ponto in pontos:
        chave = (ponto.get("media_id", ""), ponto.get("idade_dias", ""))
        if not chave[0]:
            continue
        anterior = por_chave.get(chave)
        if anterior is None:
            por_chave[chave] = dict(ponto)
            continue
        combinado = dict(anterior)
        combinado.update({k: v for k, v in ponto.items() if v not in ("", None)})
        for metrica in METRICAS_CURVA:
            combinado[metrica] = _maior(anterior.get(metrica), ponto.get(metrica))
        por_chave[chave] = combinado
    return list(por_chave.values())


def gravar_curva(
    pontos: list[dict[str, str]], path: str = CURVA_PATH
) -> list[dict[str, str]]:
    def chave(ponto: dict[str, str]) -> tuple:
        idade = ponto.get("idade_dias", "")
        return (
            ponto.get("data_local", ""),
            ponto.get("media_id", ""),
            int(idade) if idade.lstrip("-").isdigit() else 0,
        )

    ordenados = sorted(pontos, key=chave)
    _escrever(path, CAMPOS_CURVA, ordenados)
    return ordenados


def _escrever(path: str, campos: tuple[str, ...], linhas: list[dict[str, str]]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(campos))
        writer.writeheader()
        for linha in linhas:
            writer.writerow({campo: linha.get(campo, "") for campo in campos})


def views_no_dia(curva: list[dict[str, str]], media_id: str, dia: int) -> str:
    """Views do Reel com `dia` dias de vida, ou "" se não houve leitura nesse dia."""
    for ponto in curva:
        if ponto.get("media_id") == media_id and ponto.get("idade_dias") == str(dia):
            return ponto.get("views", "")
    return ""


def resumo(linhas: list[dict[str, str]], curva: list[dict[str, str]]) -> str:
    """Markdown com um Reel por linha, do mais novo para o mais velho.

    As colunas D+1 e D+7 existem porque o total favorece quem é mais velho:
    comparar Reels de idades diferentes só é justo na mesma idade.
    """
    if not linhas:
        return "### Reels\n\nNenhum Reel medido ainda.\n"

    partes = [
        f"### Reels — {len(linhas)} medidos",
        "",
        "| data | origem | views | D+1 | D+7 | alcance | visitas ao perfil "
        "| curtidas | compart. | salvos | link |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for linha in sorted(linhas, key=lambda l: l.get("publicado_utc", ""), reverse=True):
        media_id = linha.get("media_id", "")
        celulas = [
            linha.get("data_local", ""),
            linha.get("origem", ""),
            linha.get("views") or "—",
            views_no_dia(curva, media_id, 1) or "—",
            views_no_dia(curva, media_id, 7) or "—",
            linha.get("reach") or "—",
            linha.get("profile_visits") or "—",
            linha.get("likes") or "—",
            linha.get("shares") or "—",
            linha.get("saved") or "—",
            f"[ver]({linha['permalink']})" if linha.get("permalink") else "",
        ]
        partes.append("| " + " | ".join(celulas) + " |")
    partes += [
        "",
        "> Compare Reels pela mesma idade (D+1, D+7), não pelo total: o mais "
        "velho sempre teve mais tempo para juntar view.",
    ]
    return "\n".join(partes) + "\n"
