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
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

import yaml

from .queue_file import menciona_preco

from . import REPO_ROOT
from .drive import DriveFile
from .rehost import public_url

IMPORTED_PATH = os.path.join(REPO_ROOT, "state", "inbox.json")
DRAFTS_PATH = os.path.join(REPO_ROOT, "queue", "stories.yaml")
POSTS_PATH = os.path.join(REPO_ROOT, "queue", "posts.yaml")

# Subpasta cujo conteúdo vai para o feed em vez do story.
PASTA_FEED = "feed"

# A linha que a Lélia escreve na primeira linha da legenda para dizer que o
# preço está conferido. Sem ela o post fica parado na fila.
#
# Por que a marca vive no texto e não num botão: quem escreve o preço é quem
# confere o preço, e a conferência acontece no momento em que ela escreve —
# não num segundo passo que alguém faz depois, sem a peça na mão.
MARCA_PRECO = re.compile(
    r"^pre[cç]o\s*(conferido|ok|checado)?\s*[:=-]?\s*(sim|ok|true|conferido)?$",
    re.IGNORECASE,
)
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
# O campo `tipo` vem do nome da subpasta do Drive (bastidor, cliente, produto).
# Item sem tipo veio da raiz e publica igual — só não entra na comparação de
# qual conteúdo rende.
#
# Para mandar uma destas mídias ao feed, copie o item para queue/posts.yaml,
# troque media_type, escreva a legenda e marque reviewed_price: true.
"""


def parse_legenda(texto: str) -> tuple[str, bool]:
    """Separa a marca de preço conferido do corpo da legenda.

    Só a PRIMEIRA linha é lida como marca. Varrer o texto inteiro faria uma
    legenda que menciona "preço ok" no meio virar aprovação — e a trava do
    preço é a única coisa entre um reajuste e um post errado no perfil.
    """
    linhas = texto.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if linhas and MARCA_PRECO.match(linhas[0].strip()):
        return "\n".join(linhas[1:]).strip(), True
    return texto.strip(), False


def separar_legendas(
    arquivos: list[DriveFile],
) -> tuple[list[DriveFile], dict[str, DriveFile], list[DriveFile]]:
    """Divide em (mídias, legendas por nome-base, legendas sem mídia).

    Legenda órfã não some calada: ela vira aviso no relatório. Um .txt cujo
    nome não bate com nenhuma foto é quase sempre erro de digitação, e o
    sintoma sem este aviso seria um post publicado sem legenda.
    """
    midias = [a for a in arquivos if not a.e_legenda]
    bases = {a.base for a in midias}
    legendas: dict[str, DriveFile] = {}
    orfas: list[DriveFile] = []
    for arquivo in arquivos:
        if not arquivo.e_legenda:
            continue
        if arquivo.base in bases:
            legendas[arquivo.base] = arquivo
        else:
            orfas.append(arquivo)
    return midias, legendas, orfas


def draft_feed(arquivo: DriveFile, url: str, texto: str) -> dict:
    """Item de feed vindo do Drive, com a legenda do arquivo de texto ao lado.

    Vídeo vira REELS e imagem vira IMAGE: o Instagram não publica vídeo no
    feed como outra coisa, então deduzir isso do tipo do arquivo evita um
    campo a mais para alguém preencher errado.
    """
    caption, preco_ok = parse_legenda(texto)
    return {
        "id": os.path.splitext(os.path.basename(url))[0],
        "media_type": "REELS" if arquivo.mime_type.startswith("video/") else "IMAGE",
        "url": url,
        "caption": caption,
        "reviewed_price": preco_ok,
        "origem": f"Drive: {arquivo.name}",
    }


POSTS_HEADER = """# Fila de publicação do feed e dos Reels.
#
# Item cuja LEGENDA fala de preço só é publicado se `reviewed_price: true`. A
# flag não é decoração: o acervo tem post com preço pré-reajuste, e publicar um
# deles queima confiança no DM. Quem marca a flag é quem conferiu o preço, não
# o script.
#
# Legenda sem preço não precisa da marca — não há o que conferir. Exigir sempre
# viraria ritual, e ritual vira hábito: a pessoa marca sem olhar, inclusive nos
# posts que têm preço.
#
# Duas origens chegam aqui:
#
# 1. A subpasta `Feed/` do Drive. A mídia entra com a legenda do arquivo de
#    texto de mesmo nome ao lado dela, e `reviewed_price` vem `true` só quando
#    a primeira linha desse texto é `preço conferido`.
# 2. Edição à mão, inclusive os candidatos de queue/candidates.yaml.
#
# ATENÇÃO: a importação reescreve este arquivo para acrescentar item novo.
# Os itens são preservados; comentário escrito no meio da lista, não.
#
# Formato completo e comentado: queue/posts.example.yaml
"""


@dataclass(frozen=True)
class Imported:
    drive_id: str
    name: str
    path: str
    url: str
    imported_at: str


def slugify(nome: str) -> str:
    """Nome de arquivo e rótulo de tipo, sem acento e sem espaço.

    O acento é dobrado para a letra base antes de filtrar. Sem isso,
    "Promoção" virava "promo-o" e "Últimas peças" virava "ltimas-pe-as" — o
    filtro comia a letra acentuada inteira. Passava despercebido em nome de
    arquivo; como rótulo de tipo de conteúdo, seria uma categoria ilegível
    aparecendo na análise.
    """
    base = os.path.splitext(nome)[0].lower()
    base = unicodedata.normalize("NFKD", base)
    base = "".join(c for c in base if not unicodedata.combining(c))
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
    """Item de story pronto para publicar — um por execução, sem repetir.

    `tipo` vem do nome da subpasta do Drive, quando há. É o que permite
    perguntar depois qual conteúdo rendeu: foto na raiz entra sem tipo, e
    sem tipo ela não responde essa pergunta — mas publica igual.
    """
    item = {
        "id": os.path.splitext(os.path.basename(url))[0],
        "media_type": "STORIES",
        "url": url,
        "origem": f"Drive: {arquivo.name}",
    }
    tipo = slugify(arquivo.pasta) if arquivo.pasta else ""
    if tipo:
        item["tipo"] = tipo
    return item


def load_drafts(path: str = DRAFTS_PATH) -> list[dict]:
    """Rascunho não aprovado continua valendo na rodada seguinte."""
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as handle:
        dados = yaml.safe_load(handle) or []
    return [linha for linha in dados if isinstance(linha, dict)] if isinstance(dados, list) else []


def write_drafts(
    rascunhos: list[dict], path: str = DRAFTS_PATH, *, header: str = ""
) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    corpo = yaml.safe_dump(rascunhos, allow_unicode=True, sort_keys=False, width=100)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write((header or DRAFTS_HEADER) + "\n" + corpo)
    return path


def media_public_url(repo: str, branch: str, nome_arquivo: str) -> str:
    return public_url(repo, branch, f"{MEDIA_SUBDIR}/{nome_arquivo}")


def _parado(item: dict) -> bool:
    """Mesma régua da validação da fila — duas réguas diriam coisas diferentes.

    Se o relatório dissesse "pronto" e a fila recusasse (ou o contrário),
    ninguém confiaria em nenhum dos dois.
    """
    return menciona_preco(item.get("caption") or "") and not item.get("reviewed_price")


def report_markdown(
    importados: list[tuple[DriveFile, str]],
    recusados: list[DriveFile],
    repetidos: list[DriveFile],
    falhas: list[tuple[str, str]],
    *,
    orfas: list[DriveFile] | None = None,
    posts: list[dict] | None = None,
) -> str:
    linhas = ["## Fotos novas na pasta do Drive", ""]
    if importados:
        linhas += [
            f"{len(importados)} mídia(s) importada(s) e já hospedada(s). "
            "PNG e WebP são convertidos para JPEG na importação. A coluna "
            "*Conteúdo* vem do nome da subpasta do Drive:",
            "",
            "| Arquivo | Formato | Conteúdo | Mídia |",
            "|---|---|---|---|",
        ]
        for arquivo, url in importados:
            formato = "vídeo" if arquivo.mime_type.startswith("video/") else "foto"
            conteudo = slugify(arquivo.pasta) if arquivo.pasta else "— (raiz)"
            linhas.append(
                f"| {arquivo.name} | {formato} | {conteudo} | [ver]({url}) |"
            )
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

    if orfas:
        linhas += ["", "### Legendas sem mídia", ""]
        for arquivo in orfas:
            linhas.append(
                f"- **{arquivo.name}** — nenhuma mídia com esse nome. O nome do "
                "texto precisa ser igual ao da foto."
            )

    if posts:
        parados = [p for p in posts if _parado(p)]
        linhas += ["", "### Posts de feed", ""]
        for item in posts:
            marca = "**parado**" if _parado(item) else "pronto"
            trecho = (item.get("caption") or "").splitlines()
            resumo_cap = trecho[0][:60] if trecho else "_sem legenda_"
            linhas.append(f"- {marca} · {item['media_type']} · {resumo_cap}")
        if parados:
            linhas += [
                "",
                f"{len(parados)} post(s) **não** vão ao ar: a legenda fala de preço "
                "e falta a primeira linha `preço conferido` no arquivo de texto. "
                "Corrija o texto no Drive e rode a importação de novo, ou marque "
                "`reviewed_price: true` na fila.",
            ]
        linhas += [
            "",
            "Legenda sem preço não precisa da marca — sem preço não há o que "
            "conferir.",
        ]

    linhas += [
        "",
        "### O que acontece agora",
        "",
        "Estas mídias entram em `queue/stories.yaml` e **publicam sozinhas** como "
        "story, uma por execução, sem repetir. O que veio da subpasta `Feed/` vai "
        "para `queue/posts.yaml` e só sai com o preço conferido.",
        "",
        "Para tirar alguma da fila, apague o item do arquivo. Para mandar ao feed, "
        "copie para `queue/posts.yaml`, troque o `media_type`, escreva a legenda e "
        "marque `reviewed_price: true`.",
    ]
    return "\n".join(linhas) + "\n"
