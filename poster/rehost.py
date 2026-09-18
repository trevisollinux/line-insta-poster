"""Rehospedagem: baixa a mídia de um post e guarda onde a Graph API alcance.

Por que existe: o `media_url` que a API devolve é link assinado de entrega para
player. Ele serve para **baixar** o original, e não como origem de publicação —
usá-lo direto falha com `2207076`, e ainda expira em horas.

O download roda no runner do Actions, que busca a URL fresca pela API na hora.
Assim não há janela de expiração entre coletar e publicar.

Destino padrão é o próprio repositório (`media/`), servido por
`raw.githubusercontent.com`. Isso resolve o teste e os primeiros posts; como
operação permanente o lugar da mídia é um bucket — repositório guarda histórico
para sempre, e apagar o arquivo não o torna inacessível por commit SHA.
"""
from __future__ import annotations

import os
import shutil
import urllib.request
from dataclasses import dataclass

from . import REPO_ROOT
from .graph import GraphClient, GraphError

MEDIA_DIR = os.path.join(REPO_ROOT, "media")
# jsDelivr espelha o repositório público e serve com o tipo declarado.
# raw.githubusercontent.com NÃO serve: entrega .mp4 como application/octet-stream
# com nosniff, e a Meta recusa. Isso foi verificado publicando de verdade.
CDN_HOST = "https://cdn.jsdelivr.net/gh"

IMAGE_EXT = ".jpg"
VIDEO_EXT = ".mp4"
MAX_BYTES = 90 * 1024 * 1024  # acima disso o GitHub recusa o push


class RehostError(RuntimeError):
    """Não deu para trazer a mídia — nada foi gravado."""


@dataclass(frozen=True)
class MediaSource:
    media_id: str
    url: str
    media_type: str
    media_product_type: str = ""

    @property
    def is_video(self) -> bool:
        return self.media_type.upper() == "VIDEO" or self.media_product_type.upper() in {
            "REELS",
            "STORY",
        }

    @property
    def extension(self) -> str:
        return VIDEO_EXT if self.is_video else IMAGE_EXT


def media_source(client: GraphClient, media_id: str) -> MediaSource:
    """Pede a URL da mídia na hora do uso — link antigo já pode ter expirado."""
    try:
        payload = client.get(
            media_id, {"fields": "media_url,media_type,media_product_type"}
        )
    except GraphError as exc:
        raise RehostError(f"mídia {media_id} não pôde ser lida: {exc}") from exc

    url = str(payload.get("media_url") or "").strip()
    if not url:
        raise RehostError(
            f"mídia {media_id} não expõe media_url — acontece com post de Shopping "
            "ou áudio licenciado. Baixe pelo app e suba o arquivo à mão."
        )
    return MediaSource(
        media_id=media_id,
        url=url,
        media_type=str(payload.get("media_type") or ""),
        media_product_type=str(payload.get("media_product_type") or ""),
    )


def download(
    url: str,
    destino: str,
    *,
    opener=urllib.request.urlopen,
    max_bytes: int = MAX_BYTES,
) -> int:
    """Grava a mídia em disco e devolve o tamanho em bytes.

    Baixa para um arquivo `.parcial` e só promove no fim: assim um download
    interrompido, vazio ou grande demais nunca vira mídia publicável.
    """
    os.makedirs(os.path.dirname(destino) or ".", exist_ok=True)
    parcial = f"{destino}.parcial"
    try:
        with opener(url, timeout=120) as resposta, open(parcial, "wb") as saida:
            shutil.copyfileobj(resposta, saida)
        tamanho = os.path.getsize(parcial)
        if tamanho == 0:
            raise RehostError("download veio vazio")
        if tamanho > max_bytes:
            raise RehostError(
                f"arquivo com {tamanho // (1024 * 1024)} MB — acima do que o GitHub "
                "aceita; esta mídia precisa de um bucket"
            )
        os.replace(parcial, destino)
        return tamanho
    except OSError as exc:
        raise RehostError(f"download falhou: {exc}") from exc
    finally:
        if os.path.exists(parcial):
            os.remove(parcial)


def public_url(repo: str, branch: str, caminho: str) -> str:
    """URL que a Graph API aceita ingerir, para `image_url`/`video_url`."""
    return f"{CDN_HOST}/{repo.strip('/')}@{branch}/{caminho.lstrip('/')}"


def rehost(
    client: GraphClient,
    media_id: str,
    *,
    nome: str = "",
    diretorio: str = MEDIA_DIR,
    repo: str = "",
    branch: str = "main",
    opener=urllib.request.urlopen,
) -> tuple[str, str, int]:
    """Baixa e devolve (caminho relativo, url pública, bytes)."""
    origem = media_source(client, media_id)
    base = (nome or media_id).strip().strip("/")
    if not base.endswith(origem.extension):
        base += origem.extension
    destino = os.path.join(diretorio, base)
    tamanho = download(origem.url, destino, opener=opener)

    relativo = os.path.relpath(destino, REPO_ROOT).replace(os.sep, "/")
    return relativo, (public_url(repo, branch, relativo) if repo else ""), tamanho


def rehost_candidates(
    client: GraphClient,
    candidatos: list[dict],
    *,
    diretorio: str = MEDIA_DIR,
    repo: str = "",
    branch: str = "main",
    opener=urllib.request.urlopen,
) -> tuple[list[dict], list[tuple[str, str]]]:
    """Baixa a mídia de cada candidato e preenche `url` com o endereço público.

    Devolve (candidatos atualizados, falhas). Falha em um não derruba os outros:
    post de Shopping e áudio licenciado não expõem `media_url`, e é melhor
    entregar 14 prontos e dizer qual faltou do que perder a rodada inteira.
    """
    atualizados: list[dict] = []
    falhas: list[tuple[str, str]] = []
    for candidato in candidatos:
        media_id = str(candidato.get("source_media_id") or "")
        try:
            caminho, url, _ = rehost(
                client,
                media_id,
                nome=str(candidato.get("id") or media_id),
                diretorio=diretorio,
                repo=repo,
                branch=branch,
                opener=opener,
            )
        except RehostError as exc:
            falhas.append((media_id, str(exc)))
            atualizados.append(candidato)
            continue
        copia = dict(candidato)
        copia["url"] = url
        copia["media_path"] = caminho
        atualizados.append(copia)
    return atualizados, falhas
