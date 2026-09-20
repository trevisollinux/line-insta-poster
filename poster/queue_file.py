"""Fila curada (`queue/posts.yaml`) — leitura e validação.

A fila é versionada no repositório de propósito: dá diff, review e rollback de
graça, e é editável pelo celular. A validação aqui é o portão que impede a
automação de publicar item incompleto — em especial sem `reviewed_price`.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUEUE_PATH = os.path.join(REPO_ROOT, "queue", "posts.yaml")

MEDIA_TYPES = {"IMAGE", "REELS", "STORIES", "CAROUSEL"}
CAPTIONED_TYPES = {"IMAGE", "REELS", "CAROUSEL"}  # STORIES não aceita legenda
IMAGE_EXTENSIONS = (".jpg", ".jpeg")
VIDEO_EXTENSIONS = (".mp4", ".mov")

CAPTION_MAX_CHARS = 2200
CAPTION_MAX_HASHTAGS = 30
CAPTION_MAX_MENTIONS = 20
CAROUSEL_MIN_ITEMS = 2
CAROUSEL_MAX_ITEMS = 10

HASHTAG_RE = re.compile(r"(?<!\w)#\w+")
MENTION_RE = re.compile(r"(?<!\w)@[\w.]+")


class QueueError(ValueError):
    """Fila inválida. A mensagem lista todos os problemas, não só o primeiro."""


@dataclass(frozen=True)
class QueueItem:
    id: str
    media_type: str
    urls: tuple[str, ...]
    caption: str = ""
    reviewed_price: bool = False
    weight: float = 1.0
    cover_url: str | None = None
    share_to_feed: bool = True
    repeat_after_days: int | None = None
    last_published: datetime | None = None
    notes: str = ""
    # Tipo de conteúdo (bastidor, cliente, produto), vindo da subpasta do
    # Drive. Não muda nada na publicação: existe para a análise.
    tipo: str = ""
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @property
    def url(self) -> str:
        return self.urls[0]

    @property
    def is_video(self) -> bool:
        return self.media_type == "REELS" or (
            self.media_type == "STORIES" and looks_like_video(self.urls[0])
        )


def load_queue(path: str = QUEUE_PATH) -> list[QueueItem]:
    """Lê e valida a fila inteira. Levanta `QueueError` com todos os problemas."""
    if not os.path.exists(path):
        raise QueueError(f"fila não encontrada: {path}")
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or []
    return parse_queue(data)


def parse_queue(data: Any) -> list[QueueItem]:
    if isinstance(data, dict) and "posts" in data:
        data = data.get("posts") or []
    if not isinstance(data, list):
        raise QueueError("a fila deve ser uma lista de itens")

    problems: list[str] = []
    items: list[QueueItem] = []
    seen: set[str] = set()

    for index, entry in enumerate(data):
        label = f"item #{index + 1}"
        if not isinstance(entry, dict):
            problems.append(f"{label}: deve ser um mapa YAML")
            continue
        item_id = str(entry.get("id") or "").strip()
        if item_id:
            label = f"item '{item_id}'"
            if item_id in seen:
                problems.append(f"{label}: id duplicado na fila")
            seen.add(item_id)
        try:
            items.append(_parse_item(entry, label))
        except QueueError as exc:
            problems.append(str(exc))

    if problems:
        raise QueueError("fila inválida:\n- " + "\n- ".join(problems))
    return items


def _parse_item(entry: dict[str, Any], label: str) -> QueueItem:
    problems: list[str] = []

    item_id = str(entry.get("id") or "").strip()
    if not item_id:
        problems.append("id é obrigatório")

    media_type = str(entry.get("media_type") or "IMAGE").strip().upper()
    if media_type not in MEDIA_TYPES:
        problems.append(
            f"media_type '{media_type}' inválido (use {', '.join(sorted(MEDIA_TYPES))})"
        )

    urls = _parse_urls(entry, media_type, problems)
    caption = str(entry.get("caption") or "").strip()
    if caption and media_type == "STORIES":
        problems.append("STORIES não aceita caption")
    problems.extend(_caption_problems(caption))

    # A flag existe para impedir preço velho **na legenda**. STORIES não tem
    # legenda, então exigi-la ali seria burocracia sem proteção. O risco que
    # sobra — preço queimado dentro da imagem — nenhuma validação alcança.
    reviewed_price = entry.get("reviewed_price")
    exige_preco = media_type in CAPTIONED_TYPES
    if exige_preco and reviewed_price is not True:
        problems.append(
            "reviewed_price precisa ser true — preço do post tem de ser conferido "
            "à mão antes de publicar"
        )

    weight = _parse_weight(entry.get("weight", 1), problems)
    repeat_after_days = _parse_repeat(entry.get("repeat_after_days"), problems)
    last_published = _parse_timestamp(entry.get("last_published"), problems)

    cover_url = str(entry.get("cover_url") or "").strip() or None
    if cover_url and not cover_url.startswith("https://"):
        problems.append("cover_url precisa ser https")
    if cover_url and media_type != "REELS":
        problems.append("cover_url só vale para REELS")

    if problems:
        raise QueueError(f"{label}: " + "; ".join(problems))

    return QueueItem(
        id=item_id,
        media_type=media_type,
        tipo=str(entry.get("tipo") or "").strip(),
        urls=tuple(urls),
        caption=caption,
        reviewed_price=reviewed_price is True,
        weight=weight,
        cover_url=cover_url,
        share_to_feed=bool(entry.get("share_to_feed", True)),
        repeat_after_days=repeat_after_days,
        last_published=last_published,
        notes=str(entry.get("notes") or "").strip(),
        raw=entry,
    )


def _parse_urls(
    entry: dict[str, Any], media_type: str, problems: list[str]
) -> list[str]:
    raw = entry.get("urls") if entry.get("urls") is not None else entry.get("url")
    urls = [str(u).strip() for u in raw] if isinstance(raw, list) else [str(raw or "").strip()]
    urls = [u for u in urls if u]

    if not urls:
        problems.append("url é obrigatória")
        return urls
    for url in urls:
        if not url.startswith("https://"):
            problems.append(f"url precisa ser https: {url}")

    if media_type == "CAROUSEL":
        if not CAROUSEL_MIN_ITEMS <= len(urls) <= CAROUSEL_MAX_ITEMS:
            problems.append(
                f"CAROUSEL precisa de {CAROUSEL_MIN_ITEMS} a {CAROUSEL_MAX_ITEMS} urls"
            )
    elif len(urls) > 1:
        problems.append(f"{media_type} aceita uma url só")

    if media_type == "IMAGE":
        for url in urls:
            if looks_like_video(url):
                problems.append(f"IMAGE com arquivo de vídeo: {url}")
    if media_type == "REELS" and not looks_like_video(urls[0]):
        problems.append(f"REELS precisa de vídeo (.mp4/.mov): {urls[0]}")
    return urls


def _caption_problems(caption: str) -> list[str]:
    problems: list[str] = []
    if len(caption) > CAPTION_MAX_CHARS:
        problems.append(
            f"caption com {len(caption)} caracteres (máx. {CAPTION_MAX_CHARS})"
        )
    hashtags = len(HASHTAG_RE.findall(caption))
    if hashtags > CAPTION_MAX_HASHTAGS:
        problems.append(f"caption com {hashtags} hashtags (máx. {CAPTION_MAX_HASHTAGS})")
    mentions = len(MENTION_RE.findall(caption))
    if mentions > CAPTION_MAX_MENTIONS:
        problems.append(f"caption com {mentions} menções (máx. {CAPTION_MAX_MENTIONS})")
    return problems


def _parse_weight(value: Any, problems: list[str]) -> float:
    try:
        weight = float(value)
    except (TypeError, ValueError):
        problems.append(f"weight inválido: {value!r}")
        return 1.0
    if weight <= 0:
        problems.append("weight precisa ser maior que zero")
        return 1.0
    return weight


def _parse_repeat(value: Any, problems: list[str]) -> int | None:
    if value is None:
        return None
    try:
        days = int(value)
    except (TypeError, ValueError):
        problems.append(f"repeat_after_days inválido: {value!r}")
        return None
    if days <= 0:
        problems.append("repeat_after_days precisa ser maior que zero")
        return None
    return days


def _parse_timestamp(value: Any, problems: list[str]) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        problems.append(f"last_published não é uma data ISO: {value!r}")
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def looks_like_video(url: str) -> bool:
    path = url.split("?", 1)[0].lower()
    return path.endswith(VIDEO_EXTENSIONS)
