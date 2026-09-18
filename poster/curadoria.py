"""Ranking do acervo — gera candidatos, não a fila final.

Limites da API que moldam o desenho (v22+):
- `impressions`, `plays`, `video_views` e `clips_replays_count` foram depreciadas
  em media insights; `views` só existe para mídia criada a partir de ~jul/2024.
- Logo, o ranking **universal** do acervo só pode usar `like_count` e
  `comments_count`. Insights (`saved`, `shares`, `reach`) enriquecem o recorte
  recente — nunca o histórico inteiro.

Normalização: a base de seguidores multiplicou de tamanho ao longo do acervo, então
número absoluto compara épocas incomparáveis. O score de cada post é o desempenho dele dividido
pela **mediana** da janela de ±45 dias em volta dele. Mediana, e não média,
porque um viral distorce a média e rebaixa todo o resto da janela.

    score = (like_count + comments_count × P) / mediana_da_janela

Score 1,0 = mediano para a época. Score 3,0 = 3× a mediana da época.

O que isto NÃO resolve: ranquear por engajamento seleciona post bonito, não post
que vende. Serve para manter o perfil vivo entre campanhas; não substitui a
decisão editorial de quando criar urgência.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Iterable

import yaml

from .graph import GraphClient, GraphError

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG_PATH = os.path.join(REPO_ROOT, "state", "catalog.json")
CANDIDATES_PATH = os.path.join(REPO_ROOT, "queue", "candidates.yaml")

MEDIA_FIELDS = (
    "id,timestamp,media_type,media_product_type,permalink,caption,"
    "like_count,comments_count,media_url,thumbnail_url"
)
INSIGHT_METRICS = ("views", "reach", "saved", "shares", "total_interactions")
# Mídia criada a partir desta data tem insights novos; antes disso, a API
# devolve erro para as métricas que substituíram `impressions`.
INSIGHTS_CUTOFF = datetime(2024, 7, 2, tzinfo=timezone.utc)

COMMENT_WEIGHT = 7.0  # comentário custa muito mais que curtida (faixa útil: 5–10)
WINDOW_DAYS = 45

EXCLUSIONS_PATH = os.path.join(REPO_ROOT, "queue", "exclusoes.yaml")
# Campanha de urgência não é post ruim — é post irrepetível. A lista completa e
# editável está em queue/exclusoes.yaml; estes são os termos de fallback.
DEFAULT_EXCLUSIONS = (
    "reajuste",
    "promo",
    "promoçã*",
    "desconto*",
    "cupom",
    "liquidaçã*",
    "black friday",
    "última peça",
    "últimas peças",
    "esgotad*",
    "último dia",
    "por tempo limitado",
)


@dataclass
class MediaPost:
    id: str
    timestamp: datetime
    media_type: str = ""
    media_product_type: str = ""
    permalink: str = ""
    caption: str = ""
    like_count: int = 0
    comments_count: int = 0
    media_url: str = ""
    thumbnail_url: str = ""
    insights: dict[str, int] = field(default_factory=dict)

    @property
    def has_insights_support(self) -> bool:
        return self.timestamp >= INSIGHTS_CUTOFF

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(timespec="seconds"),
            "media_type": self.media_type,
            "media_product_type": self.media_product_type,
            "permalink": self.permalink,
            "caption": self.caption,
            "like_count": self.like_count,
            "comments_count": self.comments_count,
            "media_url": self.media_url,
            "thumbnail_url": self.thumbnail_url,
            "insights": self.insights,
        }


@dataclass(frozen=True)
class ScoredPost:
    post: MediaPost
    raw: float
    window_median: float
    score: float
    window_size: int


def parse_media(row: dict[str, Any]) -> MediaPost:
    stamp = str(row.get("timestamp") or "").strip()
    parsed = (
        datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if stamp
        else datetime.now(timezone.utc)
    )
    insights = row.get("insights")
    return MediaPost(
        id=str(row.get("id") or ""),
        timestamp=parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc),
        media_type=str(row.get("media_type") or ""),
        media_product_type=str(row.get("media_product_type") or ""),
        permalink=str(row.get("permalink") or ""),
        caption=str(row.get("caption") or ""),
        like_count=int(row.get("like_count") or 0),
        comments_count=int(row.get("comments_count") or 0),
        media_url=str(row.get("media_url") or ""),
        thumbnail_url=str(row.get("thumbnail_url") or ""),
        insights={k: int(v) for k, v in (insights or {}).items()},
    )


def raw_score(post: MediaPost, comment_weight: float = COMMENT_WEIGHT) -> float:
    return post.like_count + post.comments_count * comment_weight


def score_catalog(
    posts: Iterable[MediaPost],
    *,
    comment_weight: float = COMMENT_WEIGHT,
    window_days: int = WINDOW_DAYS,
) -> list[ScoredPost]:
    """Score relativo à mediana da janela de ±`window_days` de cada post."""
    ordenados = sorted(posts, key=lambda p: p.timestamp)
    brutos = {p.id: raw_score(p, comment_weight) for p in ordenados}
    janela = timedelta(days=window_days)

    resultado: list[ScoredPost] = []
    for post in ordenados:
        vizinhos = [
            brutos[outro.id]
            for outro in ordenados
            if abs(outro.timestamp - post.timestamp) <= janela
        ]
        mediana = median(vizinhos) if vizinhos else 0.0
        bruto = brutos[post.id]
        resultado.append(
            ScoredPost(
                post=post,
                raw=bruto,
                window_median=mediana,
                score=(bruto / mediana) if mediana > 0 else 0.0,
                window_size=len(vizinhos),
            )
        )
    resultado.sort(key=lambda s: (s.score, s.raw), reverse=True)
    return resultado


def collect_media(
    client: GraphClient,
    ig_user_id: str,
    *,
    page_limit: int = 50,
    max_pages: int = 10,
    cursor: str | None = None,
    since: datetime | None = None,
) -> tuple[list[MediaPost], str | None]:
    """Pagina `/{ig-user-id}/media`. Devolve (posts, cursor para o próximo lote).

    O backfill do acervo inteiro não sai numa execução — o rate limit da Graph API
    obriga lotes. Daí o cursor persistido: o job roda em partes ao longo de dias e
    depois disso só o incremental.

    Com `since`, para ao alcançar post mais antigo que a data e devolve cursor
    `None`: a API entrega do mais novo para o mais antigo, então dali para trás só
    há post velho. Cursor nulo faz a próxima execução recomeçar do topo, que é o
    que se quer num recorte por data — o que é novo entra, o resto já está no
    catálogo.
    """
    posts: list[MediaPost] = []
    after = cursor
    for _ in range(max_pages):
        params: dict[str, Any] = {"fields": MEDIA_FIELDS, "limit": page_limit}
        if after:
            params["after"] = after
        payload = client.get(f"{ig_user_id}/media", params)
        rows = payload.get("data") or []
        pagina = [parse_media(row) for row in rows]

        if since is not None:
            recentes = [post for post in pagina if post.timestamp >= since]
            posts.extend(recentes)
            if len(recentes) < len(pagina):
                return posts, None
        else:
            posts.extend(pagina)

        after = ((payload.get("paging") or {}).get("cursors") or {}).get("after")
        if not rows or not (payload.get("paging") or {}).get("next"):
            after = None
            break
    return posts, after


def fetch_insights(client: GraphClient, post: MediaPost) -> dict[str, int]:
    """Insights só do recorte recente — o histórico não tem essas métricas."""
    if not post.has_insights_support:
        return {}
    try:
        payload = client.get(
            f"{post.id}/insights", {"metric": ",".join(INSIGHT_METRICS)}
        )
    except GraphError as exc:
        print(f"insights indisponíveis para {post.id}: {exc}")
        return {}
    valores: dict[str, int] = {}
    for row in payload.get("data") or []:
        nome = str(row.get("name") or "")
        pontos = row.get("values") or []
        if nome and pontos:
            valor = pontos[0].get("value")
            if isinstance(valor, int):
                valores[nome] = valor
    return valores


def load_catalog(path: str = CATALOG_PATH) -> tuple[list[MediaPost], str | None]:
    if not os.path.exists(path):
        return [], None
    with open(path, "r", encoding="utf-8") as handle:
        conteudo = handle.read().strip()
    if not conteudo:
        return [], None
    data = json.loads(conteudo)
    posts = [parse_media(row) for row in data.get("media", [])]
    return posts, data.get("cursor") or None


def save_catalog(
    posts: list[MediaPost], cursor: str | None, path: str = CATALOG_PATH
) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = {
        "version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cursor": cursor,
        "media": [p.to_json() for p in sorted(posts, key=lambda p: p.timestamp)],
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def merge_catalog(atual: list[MediaPost], novos: list[MediaPost]) -> list[MediaPost]:
    """Novo vence o antigo (contadores mudam); ordem final é cronológica."""
    indice = {post.id: post for post in atual}
    for post in novos:
        antigo = indice.get(post.id)
        if antigo and not post.insights and antigo.insights:
            post.insights = antigo.insights
        indice[post.id] = post
    return sorted(indice.values(), key=lambda p: p.timestamp)


def strip_accents(text: str) -> str:
    decomposto = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def normalize(text: str) -> str:
    """Minúsculas e sem acento — "PROMOÇÃO" e "promocao" viram a mesma coisa."""
    return strip_accents(text).lower()


def compile_exclusions(terms: Iterable[str]) -> list[tuple[str, re.Pattern[str]]]:
    """Cada termo vira regex de palavra inteira; `*` no fim vira prefixo."""
    compilados: list[tuple[str, re.Pattern[str]]] = []
    for termo in terms:
        limpo = str(termo).strip()
        if not limpo:
            continue
        alvo = normalize(limpo)
        prefixo = alvo.endswith("*")
        alvo = alvo.rstrip("*")
        if not alvo:
            continue
        corpo = re.escape(alvo).replace(r"\ ", r"\s+")
        sufixo = r"\w*" if prefixo else ""
        compilados.append(
            (limpo, re.compile(rf"(?<!\w){corpo}{sufixo}(?!\w)"))
        )
    return compilados


def load_exclusions(path: str = EXCLUSIONS_PATH) -> list[str]:
    if not os.path.exists(path):
        return list(DEFAULT_EXCLUSIONS)
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or []
    if isinstance(data, dict):
        data = data.get("exclusoes") or data.get("termos") or []
    return [str(t) for t in data] if isinstance(data, list) else list(DEFAULT_EXCLUSIONS)


def excluded_by(caption: str, patterns: list[tuple[str, re.Pattern[str]]]) -> str | None:
    """Devolve o termo que barrou a legenda, ou None se ela é reciclável."""
    texto = normalize(caption or "")
    for termo, padrao in patterns:
        if padrao.search(texto):
            return termo
    return None


def split_recyclable(
    scored: list[ScoredPost], patterns: list[tuple[str, re.Pattern[str]]]
) -> tuple[list[ScoredPost], list[tuple[ScoredPost, str]]]:
    """Separa o que pode ser republicado do que é campanha com data.

    O excluído sai dos candidatos mas **continua na mediana da janela**: ele fez
    parte da realidade daquela época, e tirá-lo da base de comparação inflaria o
    score de todo o resto.
    """
    reciclaveis: list[ScoredPost] = []
    excluidos: list[tuple[ScoredPost, str]] = []
    for item in scored:
        termo = excluded_by(item.post.caption, patterns)
        if termo:
            excluidos.append((item, termo))
        else:
            reciclaveis.append(item)
    return reciclaveis, excluidos


def candidates_document(scored: list[ScoredPost], *, top_n: int = 20) -> list[dict[str, Any]]:
    """Itens prontos para revisão humana — `reviewed_price` fica false de propósito."""
    documento: list[dict[str, Any]] = []
    for item in scored[:top_n]:
        post = item.post
        documento.append(
            {
                "id": f"{post.timestamp.date().isoformat()}-{post.id}",
                "source_media_id": post.id,
                "permalink": post.permalink,
                "published_at": post.timestamp.date().isoformat(),
                "media_type": "REELS" if post.media_product_type == "REELS" else "IMAGE",
                "url": "",  # preencher com a mídia rehospedada no bucket
                # Link assinado da Meta: serve para baixar o original agora, expira em
                # algumas horas e por isso nunca pode ir para `url`.
                "source_media_url": post.media_url,
                "caption": post.caption,
                "reviewed_price": False,  # revisão humana obrigatória
                "weight": round(min(5.0, max(1.0, item.score)), 2),
                "metrics": {
                    "score": round(item.score, 2),
                    "like_count": post.like_count,
                    "comments_count": post.comments_count,
                    "window_median": round(item.window_median, 2),
                    "window_size": item.window_size,
                    **{k: v for k, v in post.insights.items()},
                },
            }
        )
    return documento


HEADER = """# Candidatos gerados por poster/curadoria.py — NÃO é a fila.
#
# Campanhas de urgência (reajuste, promoção, últimas peças) já foram removidas
# daqui: elas funcionam porque têm data, e republicar depois vira mentira. Os
# termos ficam em queue/exclusoes.yaml. Elas continuam contando na mediana da
# época — só não entram como candidatas.
#
# Antes de mover para posts.yaml, a revisão humana precisa:
#   1. conferir o preço da peça (score alto não sabe que a bolsa reajustou);
#   2. descartar modelo fora de linha (post campeão de peça que não se produz
#      mais gera DM que termina em não);
#   3. baixar a mídia de `source_media_url` (link da Meta, expira em horas),
#      rehospedar e preencher `url`;
#   4. marcar reviewed_price: true.
"""


def write_candidates_document(
    documento: list[dict[str, Any]], *, path: str = CANDIDATES_PATH
) -> str:
    """Grava um documento de candidatos já montado (e possivelmente rehospedado)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    corpo = yaml.safe_dump(documento, allow_unicode=True, sort_keys=False, width=100)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(HEADER + "\n" + corpo)
    return path


def write_candidates(
    scored: list[ScoredPost], *, path: str = CANDIDATES_PATH, top_n: int = 20
) -> str:
    return write_candidates_document(
        candidates_document(scored, top_n=top_n), path=path
    )


def candidates_markdown(documento: list[dict[str, Any]], *, titulo: str = "") -> str:
    """Relatório legível dos candidatos — vira o corpo da issue de aprovação.

    Traz os dois links que a revisão precisa: o post original (para ver o que é)
    e a mídia rehospedada (que vai virar `url` na fila).
    """
    linhas: list[str] = []
    if titulo:
        linhas += [f"## {titulo}", ""]
    linhas += [
        "Score é o desempenho do post dividido pela mediana da própria época "
        "(±45 dias) — 3,0 significa três vezes o mediano daquele mês. Campanha "
        "com data já foi removida da lista.",
        "",
        "| # | Post | Formato | Score | Salvos | Mídia pronta |",
        "|---|---|---|---|---|---|",
    ]
    for posicao, linha in enumerate(documento, start=1):
        metricas = linha.get("metrics") or {}
        midia = linha.get("url") or ""
        linhas.append(
            f"| {posicao} "
            f"| [{linha.get('published_at', '')}]({linha.get('permalink', '')}) "
            f"| {linha.get('media_type', '')} "
            f"| {metricas.get('score', '—')} "
            f"| {metricas.get('saved', '—')} "
            f"| {'[baixada](' + midia + ')' if midia else '⚠️ não rehospedada'} |"
        )
    linhas += [
        "",
        "### Para aprovar",
        "",
        "1. Abra `queue/candidates.yaml` e apague os itens que não devem sair.",
        "2. Reescreva a legenda de cada um que ficar — repetir a legenda original "
        "é o que derruba alcance em conteúdo reciclado.",
        "3. Escolha o formato: `REELS` leva legenda e entra no feed; `STORIES` "
        "some em 24h e **não aceita legenda**; `CAROUSEL` precisa de 2 a 10 mídias.",
        "4. Confira o preço da peça e marque `reviewed_price: true`.",
        "5. Mova os aprovados para `queue/posts.yaml`.",
        "",
        "Item sem `reviewed_price: true` é recusado na validação — de propósito.",
    ]
    return "\n".join(linhas) + "\n"
