"""Escolha do próximo item da fila.

Dois modos: `order` (primeiro elegível, previsível para depurar) e `weighted`
(sorteio ponderado por `weight`, que é o padrão — evita o perfil virar uma
sequência sempre igual). A elegibilidade é a parte que importa: item já
publicado só volta se tiver `repeat_after_days` e o prazo tiver vencido.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .queue_file import QueueItem
from .state import PublishedEntry, last_published_at

MODES = ("weighted", "order")


@dataclass(frozen=True)
class Skipped:
    item_id: str
    reason: str


@dataclass(frozen=True)
class Selection:
    item: QueueItem | None
    eligible: list[QueueItem]
    skipped: list[Skipped]


def select_next(
    items: list[QueueItem],
    published: list[PublishedEntry],
    *,
    mode: str = "weighted",
    now: datetime | None = None,
    rng: random.Random | None = None,
) -> Selection:
    if mode not in MODES:
        raise ValueError(f"modo de seleção inválido: {mode} (use {', '.join(MODES)})")
    now = now or datetime.now(timezone.utc)
    rng = rng or random.Random()

    eligible: list[QueueItem] = []
    skipped: list[Skipped] = []

    for item in items:
        published_at = last_published_at(published, item.id) or item.last_published
        if published_at is None:
            eligible.append(item)
            continue
        if item.repeat_after_days is None:
            skipped.append(
                Skipped(item.id, f"já publicado em {published_at.date().isoformat()}")
            )
            continue
        liberado = published_at + timedelta(days=item.repeat_after_days)
        if liberado > now:
            skipped.append(
                Skipped(item.id, f"repete só a partir de {liberado.date().isoformat()}")
            )
            continue
        eligible.append(item)

    if not eligible:
        return Selection(None, [], skipped)
    if mode == "order":
        return Selection(eligible[0], eligible, skipped)
    return Selection(_weighted_pick(eligible, rng), eligible, skipped)


def _weighted_pick(items: list[QueueItem], rng: random.Random) -> QueueItem:
    total = sum(item.weight for item in items)
    draw = rng.random() * total
    acumulado = 0.0
    for item in items:
        acumulado += item.weight
        if draw < acumulado:
            return item
    return items[-1]  # só cai aqui por arredondamento de ponto flutuante
