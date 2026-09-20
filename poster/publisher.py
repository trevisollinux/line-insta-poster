"""Fluxo de publicação: container → polling → media_publish → estado.

Ordem que não muda:
  1. cria o container (`POST /{ig-user-id}/media`)
  2. espera ele ficar FINISHED (vídeo sempre precisa; imagem passa direto, mas o
     código trata igual)
  3. publica (`POST /{ig-user-id}/media_publish`)
  4. só então grava em `state/published.json`

Container expira em 24h — por isso nada é criado "adiantado" para publicar depois.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from .graph import GraphClient, GraphError
from .queue_file import QueueItem, looks_like_video
from .state import PublishedEntry

TERMINAL_OK = "FINISHED"
TERMINAL_FAIL = {"ERROR", "EXPIRED"}


class PublishError(RuntimeError):
    """Falha no fluxo de publicação — o item NÃO deve ser marcado como publicado."""


@dataclass
class PublishOutcome:
    item_id: str
    media_id: str
    container_id: str
    media_type: str
    published_at: datetime
    permalink: str | None = None
    tipo: str = ""
    quota_usage: int | None = None
    quota_total: int | None = None
    children: list[str] = field(default_factory=list)

    def to_entry(self) -> PublishedEntry:
        return PublishedEntry(
            item_id=self.item_id,
            media_id=self.media_id,
            container_id=self.container_id,
            media_type=self.media_type,
            published_at=self.published_at.isoformat(timespec="seconds"),
            permalink=self.permalink,
            tipo=self.tipo,
        )


def container_params(item: QueueItem) -> dict[str, Any]:
    """Parâmetros de `POST /{ig-user-id}/media` para um item não-carrossel."""
    if item.media_type == "CAROUSEL":
        raise ValueError("carrossel monta os parâmetros em carousel_child_params")
    params: dict[str, Any] = {}
    if item.media_type == "IMAGE":
        params["image_url"] = item.url
        params["caption"] = item.caption
    elif item.media_type == "REELS":
        params["media_type"] = "REELS"
        params["video_url"] = item.url
        params["caption"] = item.caption
        params["share_to_feed"] = "true" if item.share_to_feed else "false"
        if item.cover_url:
            params["cover_url"] = item.cover_url
    elif item.media_type == "STORIES":
        params["media_type"] = "STORIES"
        if item.is_video:
            params["video_url"] = item.url
        else:
            params["image_url"] = item.url
    else:  # pragma: no cover - queue_file já barra tipos desconhecidos
        raise ValueError(f"media_type não suportado: {item.media_type}")
    return {k: v for k, v in params.items() if v not in (None, "")}


def carousel_child_params(url: str, is_video: bool) -> dict[str, Any]:
    params: dict[str, Any] = {"is_carousel_item": "true"}
    if is_video:
        params["media_type"] = "VIDEO"
        params["video_url"] = url
    else:
        params["image_url"] = url
    return params


def publishing_limit(client: GraphClient, ig_user_id: str) -> tuple[int | None, int | None]:
    """Consumo do limite de publicação/24h — a conta observada devolve 100.

    O número varia por conta, então nada aqui é fixo: o job lê `quota_total` da
    própria API antes de criar container.
    """
    try:
        payload = client.get(
            f"{ig_user_id}/content_publishing_limit",
            {"fields": "config,quota_usage"},
        )
    except GraphError as exc:
        print(f"content_publishing_limit indisponível: {exc}")
        return None, None
    rows = payload.get("data") or []
    if not rows:
        return None, None
    row = rows[0]
    usage = row.get("quota_usage")
    total = (row.get("config") or {}).get("quota_total")
    return (
        usage if isinstance(usage, int) else None,
        total if isinstance(total, int) else None,
    )


def create_container(client: GraphClient, ig_user_id: str, item: QueueItem) -> tuple[str, list[str]]:
    """Cria o(s) container(s). Devolve (container_id, ids dos filhos)."""
    if item.media_type != "CAROUSEL":
        payload = client.post(f"{ig_user_id}/media", container_params(item))
        return _require_id(payload, "container"), []

    children: list[str] = []
    for url in item.urls:
        child = client.post(
            f"{ig_user_id}/media", carousel_child_params(url, looks_like_video(url))
        )
        children.append(_require_id(child, "container filho do carrossel"))
    parent = client.post(
        f"{ig_user_id}/media",
        {
            "media_type": "CAROUSEL",
            "children": ",".join(children),
            "caption": item.caption,
        },
    )
    return _require_id(parent, "container do carrossel"), children


def wait_for_container(
    client: GraphClient,
    container_id: str,
    *,
    interval: int = 60,
    timeout: int = 300,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> str:
    """Espera FINISHED. ERROR/EXPIRED/estouro de tempo abortam sem publicar."""
    started = monotonic()
    while True:
        payload = client.get(container_id, {"fields": "status_code,status"})
        status = str(payload.get("status_code") or "").upper()
        if status == TERMINAL_OK:
            return status
        if status in TERMINAL_FAIL:
            detalhe = payload.get("status") or ""
            raise PublishError(
                f"container {container_id} terminou como {status}. {detalhe}".strip()
            )
        if monotonic() - started + interval > timeout:
            raise PublishError(
                f"container {container_id} ainda em {status or 'estado desconhecido'} "
                f"após {timeout}s — abortado sem publicar"
            )
        sleep(interval)


def publish_container(client: GraphClient, ig_user_id: str, container_id: str) -> str:
    payload = client.post(f"{ig_user_id}/media_publish", {"creation_id": container_id})
    return _require_id(payload, "media_publish")


def fetch_permalink(client: GraphClient, media_id: str) -> str | None:
    try:
        payload = client.get(media_id, {"fields": "permalink"})
    except GraphError as exc:
        print(f"permalink indisponível: {exc}")
        return None
    permalink = payload.get("permalink")
    return str(permalink) if permalink else None


def publish_item(
    client: GraphClient,
    ig_user_id: str,
    item: QueueItem,
    *,
    poll_interval: int = 60,
    poll_timeout: int = 300,
    min_quota_left: int = 1,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> PublishOutcome:
    usage, total = publishing_limit(client, ig_user_id)
    if usage is not None and total is not None:
        restante = total - usage
        print(f"limite de publicação: {usage}/{total} usados nas últimas 24h")
        if restante < min_quota_left:
            raise PublishError(
                f"limite de publicação quase estourado ({usage}/{total}) — "
                "nada publicado nesta execução"
            )

    try:
        container_id, children = create_container(client, ig_user_id, item)
        wait_for_container(
            client,
            container_id,
            interval=poll_interval,
            timeout=poll_timeout,
            sleep=sleep,
            monotonic=monotonic,
        )
        media_id = publish_container(client, ig_user_id, container_id)
    except GraphError as exc:
        raise PublishError(f"item '{item.id}' não publicado: {exc}") from exc

    return PublishOutcome(
        item_id=item.id,
        media_id=media_id,
        container_id=container_id,
        media_type=item.media_type,
        published_at=now(),
        permalink=fetch_permalink(client, media_id),
        tipo=item.tipo,
        quota_usage=usage,
        quota_total=total,
        children=children,
    )


def _require_id(payload: dict[str, Any], label: str) -> str:
    value = str(payload.get("id") or "").strip()
    if not value:
        raise PublishError(f"{label} não devolveu id: {payload}")
    return value
