"""Estado do que já foi publicado (`state/published.json`).

Arquivo commitado pelo próprio workflow. Regra que não se negocia: só entra aqui
depois que `media_publish` devolveu um id. Gravar antes gera post perdido em
silêncio — o item some da fila sem nunca ter ido ao ar.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(REPO_ROOT, "state", "published.json")
STATE_VERSION = 1


@dataclass(frozen=True)
class PublishedEntry:
    item_id: str
    media_id: str
    container_id: str
    media_type: str
    published_at: str
    permalink: str | None = None
    # Copiado do item no momento da publicação. É a única ponte entre o que a
    # API mede (media_id) e que tipo de foto era — a fila muda, o estado não.
    tipo: str = ""

    @property
    def published_datetime(self) -> datetime:
        parsed = datetime.fromisoformat(self.published_at.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def load_state(path: str = STATE_PATH) -> list[PublishedEntry]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as handle:
        content = handle.read().strip()
    if not content:
        return []
    data = json.loads(content)
    rows = data.get("published", []) if isinstance(data, dict) else data
    entries: list[PublishedEntry] = []
    for row in rows:
        entries.append(
            PublishedEntry(
                item_id=str(row.get("item_id", "")),
                media_id=str(row.get("media_id", "")),
                container_id=str(row.get("container_id", "")),
                media_type=str(row.get("media_type", "")),
                tipo=str(row.get("tipo", "") or ""),
                published_at=str(row.get("published_at", "")),
                permalink=row.get("permalink"),
            )
        )
    return entries


def save_state(entries: list[PublishedEntry], path: str = STATE_PATH) -> None:
    payload = {
        "version": STATE_VERSION,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "published": [asdict(entry) for entry in entries],
    }
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def append_entry(entry: PublishedEntry, path: str = STATE_PATH) -> list[PublishedEntry]:
    """Relê o arquivo antes de gravar — o workflow pode ter commitado no meio."""
    entries = load_state(path)
    entries.append(entry)
    save_state(entries, path)
    return entries


def last_published_at(
    entries: list[PublishedEntry], item_id: str
) -> datetime | None:
    stamps = [
        entry.published_datetime
        for entry in entries
        if entry.item_id == item_id and entry.published_at
    ]
    return max(stamps) if stamps else None
