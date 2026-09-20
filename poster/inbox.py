"""Importa o que a curadoria humana largou na pasta do Drive.

Fluxo: lê a pasta → descarta o que já veio antes → baixa o que é publicável →
grava no repositório de mídia → entra em `queue/stories.yaml`.

**Não há aprovação humana neste caminho.** O que cai na pasta vai ao ar como
story sozinho, um por execução do cron. A decisão está em quem sobe a foto, não
em quem revisa depois — versões anteriores deste texto prometiam um
`reviewed_price: false` que a fila de stories não usa mais, e prometer trava que
não existe é pior que não ter trava.

Por que story não exige a flag: ela protege preço velho na legenda, e story não
leva legenda (a API não aceita). O que ninguém cobre é preço queimado dentro da
imagem — se sair errado, apague pelo app; o story dura 24h. Feed e Reels, em
`queue/posts.yaml`, continuam exigindo aprovação.
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
DRAFTS_PATH = os.path.join(REPO_ROOT, "queue", "stories.yaml")
MEDIA_SUBDIR = "inbox"

DRAFTS_HEADER = """# Stories vindos da pasta do Drive — esta fila PUBLICA sozinha.
#
# Um item por execução, sem repetir: o que já saiu fica em state/published.json.
# Story não leva legenda (a API não aceita), some em 24h, e por isso não exige
# reviewed_price — aquela flag protege preço na legenda, e aqui não há legenda.
#
# O que ela NÃO protege: preço queimado dentro da imagem. Se algo sair errado,
# apague o story pelo app; ele dura 24h.
#
# Para mandar uma destas mídias ao feed, copie o item para queue/posts.yaml,
# troque media_type, escreva a legenda e marque reviewed_price: true.
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
        elif arquivo.motivo_recusa:
            recusados.append(arquivo)
        else:
            novos.append(arquivo)
    return novos, repetidos, recusados


def draft(arquivo: DriveFile, url: str) -> dict:
    """Item de story pronto para publicar — um por execução, sem repetir."""
    return {
        "id": os.path.splitext(os.path.basename(url))[0],
        "media_type": "STORIES",
        "url": url,
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
            f"{len(importados)} mídia(s) importada(s) e já hospedada(s). "
            "PNG e WebP são convertidos para JPEG na importação:",
            "",
            "| Arquivo | Tipo | Mídia |",
            "|---|---|---|",
        ]
        for arquivo, url in importados:
            tipo = "vídeo" if arquivo.mime_type.startswith("video/") else "foto"
            linhas.append(f"| {arquivo.name} | {tipo} | [ver]({url}) |")
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
        "### O que acontece agora",
        "",
        "Estas mídias entram em `queue/stories.yaml` e **publicam sozinhas** como "
        "story, uma por execução, sem repetir.",
        "",
        "Para tirar alguma da fila, apague o item do arquivo. Para mandar ao feed, "
        "copie para `queue/posts.yaml`, troque o `media_type`, escreva a legenda e "
        "marque `reviewed_price: true`.",
    ]
    return "\n".join(linhas) + "\n"
