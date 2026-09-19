"""Importa o que a curadoria humana largou na pasta do Drive.

Fluxo: lê a pasta → descarta o que já veio antes → baixa o que é publicável →
grava no repositório de mídia → emite rascunhos de fila para aprovação.

Rascunho nasce com `reviewed_price: false` de propósito: ele **não** pode ser
publicado por acidente, porque a validação da fila recusa item sem essa marca.
Entre a foto aparecer na pasta e ela ir ao ar existe uma decisão humana, e é
assim que deve continuar.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

import yaml

from . import REPO_ROOT
from .drive import DriveFile
from .rehost import public_url

IMPORTED_PATH = os.path.join(REPO_ROOT, "state", "inbox.json")
DRAFTS_PATH = os.path.join(REPO_ROOT, "queue", "drafts.yaml")
MEDIA_SUBDIR = "inbox"

DRAFTS_HEADER = """# Rascunhos vindos da pasta do Drive — NÃO é a fila.
#
# Cada item nasce com reviewed_price: false e por isso não pode ser publicado:
# a validação recusa. Para colocar no ar, mova para queue/posts.yaml depois de:
#   1. escrever a legenda (STORIES não aceita legenda);
#   2. conferir o preço da peça;
#   3. marcar reviewed_price: true.
#
# `url` já aponta para a mídia no repositório line-store-media.
"""


@dataclass(frozen=True)
class Imported:
    drive_id: str
    name: str
    path: str
    url: str
    imported_at: str


def slugify(nome: str) -> str:
    base = os.path.splitext(nome)[0].lower()
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return base[:60] or "midia"


def media_filename(arquivo: DriveFile, *, hoje: str = "") -> str:
    """Nome legível e sem colisão: data, apelido do arquivo e pedaço do id."""
    dia = hoje or datetime.now(timezone.utc).date().isoformat()
    return f"{dia}-{slugify(arquivo.name)}-{arquivo.id[:6]}{arquivo.extension}"


def load_imported(path: str = IMPORTED_PATH) -> dict[str, Imported]:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        conteudo = handle.read().strip()
    if not conteudo:
        return {}
    dados = json.loads(conteudo)
    return {
        str(linha["drive_id"]): Imported(
            drive_id=str(linha.get("drive_id", "")),
            name=str(linha.get("name", "")),
            path=str(linha.get("path", "")),
            url=str(linha.get("url", "")),
            imported_at=str(linha.get("imported_at", "")),
        )
        for linha in dados.get("imported", [])
    }


def save_imported(registros: dict[str, Imported], path: str = IMPORTED_PATH) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = {
        "version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "imported": [asdict(r) for r in registros.values()],
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def triagem(
    arquivos: list[DriveFile], ja_importados: dict[str, Imported]
) -> tuple[list[DriveFile], list[DriveFile], list[DriveFile]]:
    """Separa em (novos publicáveis, já importados, recusados por formato)."""
    novos: list[DriveFile] = []
    repetidos: list[DriveFile] = []
    recusados: list[DriveFile] = []
    for arquivo in arquivos:
        if arquivo.id in ja_importados:
            repetidos.append(arquivo)
        elif not arquivo.publicavel:
            recusados.append(arquivo)
        else:
            novos.append(arquivo)
    return novos, repetidos, recusados


def draft(arquivo: DriveFile, url: str) -> dict:
    """Item de fila pré-preenchido, faltando o que só pessoa decide."""
    return {
        "id": os.path.splitext(os.path.basename(url))[0],
        "media_type": "REELS" if arquivo.mime_type.startswith("video/") else "IMAGE",
        "url": url,
        "caption": "",  # escrever antes de publicar
        "reviewed_price": False,  # trava proposital
        "origem": f"Drive: {arquivo.name}",
    }


def load_drafts(path: str = DRAFTS_PATH) -> list[dict]:
    """Rascunho não aprovado continua valendo na rodada seguinte."""
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as handle:
        dados = yaml.safe_load(handle) or []
    return [linha for linha in dados if isinstance(linha, dict)] if isinstance(dados, list) else []


def write_drafts(rascunhos: list[dict], path: str = DRAFTS_PATH) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    corpo = yaml.safe_dump(rascunhos, allow_unicode=True, sort_keys=False, width=100)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(DRAFTS_HEADER + "\n" + corpo)
    return path


def media_public_url(repo: str, branch: str, nome_arquivo: str) -> str:
    return public_url(repo, branch, f"{MEDIA_SUBDIR}/{nome_arquivo}")


def report_markdown(
    importados: list[tuple[DriveFile, str]],
    recusados: list[DriveFile],
    repetidos: list[DriveFile],
    falhas: list[tuple[str, str]],
) -> str:
    linhas = ["## Fotos novas na pasta do Drive", ""]
    if importados:
        linhas += [
            f"{len(importados)} mídia(s) importada(s) e já hospedada(s):",
            "",
            "| Arquivo | Tipo | Mídia |",
            "|---|---|---|",
        ]
        for arquivo, url in importados:
            tipo = "vídeo" if arquivo.mime_type.startswith("video/") else "foto"
            linhas.append(f"| {arquivo.name} | {tipo} | [ver]({url}) |")
        linhas += [
            "",
            "Os rascunhos estão em `queue/drafts.yaml`, com `reviewed_price: false` "
            "— nenhum deles pode ir ao ar por acidente.",
        ]
    else:
        linhas.append("Nenhuma mídia nova nesta rodada.")

    if recusados:
        linhas += ["", "### Recusados pelo formato", ""]
        for arquivo in recusados:
            linhas.append(f"- **{arquivo.name}** — {arquivo.motivo_recusa}")

    if falhas:
        linhas += ["", "### Falharam no download", ""]
        for nome, motivo in falhas:
            linhas.append(f"- **{nome}** — {motivo}")

    if repetidos:
        linhas += ["", f"{len(repetidos)} arquivo(s) já importado(s) antes, ignorados."]

    linhas += [
        "",
        "### Para publicar",
        "",
        "1. Abra `queue/drafts.yaml` e escreva a legenda de cada um "
        "(`STORIES` não aceita legenda).",
        "2. Confira o preço da peça.",
        "3. Marque `reviewed_price: true` e mova para `queue/posts.yaml`.",
    ]
    return "\n".join(linhas) + "\n"
