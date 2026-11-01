"""CTA gravado na imagem do story.

Por que no pixel e não num sticker: a Graph API publica story só com a mídia —
não aceita sticker de link, enquete, caixa de pergunta nem texto. O que o app
faz por cima da foto, a API não faz. Então o chamado para a ação precisa estar
na própria imagem, e é isto que este módulo desenha.

O desenho é sempre o mesmo, de propósito:

- uma faixa escura em degradê na base, que dá leitura sobre qualquer foto;
- `LINE STORE` pequeno, espaçado, como assinatura;
- o **título** (`titulo`), em serifa, que fala da foto;
- o **botão** (`acao`), em pílula clara, que diz o que fazer.

Tudo fica entre as alturas `TOPO_SEGURO` e `BASE_SEGURA`: em cima o Instagram
põe a barra de progresso e o @ da conta; embaixo, o campo "Enviar mensagem".
Texto ali é texto coberto.

A ação mais forte para esta loja é **responder o story**: a resposta cai no
direct, e é no direct que a venda acontece. A segunda é **tocar no @**, que é
o que vira "visita ao perfil" na métrica. O texto da ação é livre — a fila diz
qual usar em cada foto.

O que NÃO entra no CTA: preço e urgência. Preço velho dentro da imagem é o
risco que nenhuma validação alcança depois de gravado, e "últimas peças" numa
foto que repete a cada duas semanas é falso. A validação da fila recusa os dois.
"""
from __future__ import annotations

import hashlib
import io
import os
import textwrap
from dataclasses import dataclass
from typing import Callable

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

FONTES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
FONTE_TITULO = os.path.join(FONTES_DIR, "PlayfairDisplay-Medium.ttf")
FONTE_ACAO = os.path.join(FONTES_DIR, "Inter-SemiBold.otf")
FONTE_MARCA = os.path.join(FONTES_DIR, "Inter-Medium.otf")

LARGURA, ALTURA = 1080, 1920
# Zonas que a interface do Instagram cobre (medidas em tela 1080x1920).
TOPO_SEGURO = 250
BASE_SEGURA = ALTURA - 215

# Se a foto já está perto de 9:16, recorta para preencher. Fora disso, cabe
# inteira sobre um fundo desfocado dela mesma — cortar uma colagem ou uma foto
# quadrada pela metade estraga mais do que a borda desfocada.
TOLERANCIA_RECORTE = 0.08

COR_TEXTO = (250, 246, 240)
COR_PILULA = (244, 237, 227)
COR_PILULA_TEXTO = (52, 33, 22)
COR_SOMBRA = (22, 15, 10)

TITULO_MAX = 60
ACAO_MAX = 40
# Muda quando o desenho muda: força renderizar de novo o que já foi gravado.
VERSAO_DESENHO = "1"


class CtaError(ValueError):
    """CTA que não dá para desenhar — nada foi gravado."""


@dataclass(frozen=True)
class Cta:
    acao: str
    titulo: str = ""

    def assinatura(self, origem: str) -> str:
        """Muda quando o texto, a foto de origem ou o desenho mudam."""
        base = "\x1f".join((VERSAO_DESENHO, origem, self.titulo, self.acao))
        return hashlib.sha256(base.encode("utf-8")).hexdigest()[:12]


def problemas_do_cta(bruto) -> list[str]:
    """Valida o campo `cta` de um item da fila. Lista vazia = ok."""
    if not isinstance(bruto, dict):
        return ["cta deve ser um mapa com `acao` (e `titulo`, opcional)"]
    problemas: list[str] = []
    desconhecidos = set(bruto) - {"acao", "titulo"}
    if desconhecidos:
        problemas.append(f"cta com campo desconhecido: {', '.join(sorted(desconhecidos))}")
    acao = str(bruto.get("acao") or "").strip()
    titulo = str(bruto.get("titulo") or "").strip()
    if not acao:
        problemas.append("cta.acao é obrigatória — é ela que diz o que fazer")
    if len(acao) > ACAO_MAX:
        problemas.append(f"cta.acao com {len(acao)} caracteres (máx. {ACAO_MAX}, cabe numa linha)")
    if len(titulo) > TITULO_MAX:
        problemas.append(f"cta.titulo com {len(titulo)} caracteres (máx. {TITULO_MAX})")

    # Gravado no pixel, o texto não envelhece junto com a loja: preço e
    # urgência ficam falsos na primeira repetição, e não dá para editar depois.
    from .curadoria import compile_exclusions, excluded_by, load_exclusions
    from .queue_file import menciona_preco

    texto = f"{titulo}\n{acao}"
    if menciona_preco(texto):
        problemas.append("cta com preço — preço gravado na imagem envelhece e ninguém vê")
    termo = excluded_by(texto, compile_exclusions(load_exclusions()))
    if termo:
        problemas.append(
            f"cta com termo de urgência/campanha ('{termo}', de queue/exclusoes.yaml) — "
            "o story repete a cada duas semanas e a urgência vira mentira"
        )
    return problemas


def ler_cta(bruto) -> Cta:
    problemas = problemas_do_cta(bruto)
    if problemas:
        raise CtaError("; ".join(problemas))
    return Cta(acao=str(bruto["acao"]).strip(), titulo=str(bruto.get("titulo") or "").strip())


def _fonte(caminho: str, tamanho: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(caminho, tamanho)


def enquadrar(foto: Image.Image) -> Image.Image:
    """Leva qualquer foto a 1080x1920 sem distorcer."""
    foto = ImageOps.exif_transpose(foto).convert("RGB")
    proporcao = foto.width / foto.height
    alvo = LARGURA / ALTURA
    if abs(proporcao - alvo) / alvo <= TOLERANCIA_RECORTE:
        return ImageOps.fit(foto, (LARGURA, ALTURA), Image.LANCZOS)
    fundo = ImageOps.fit(foto, (LARGURA, ALTURA), Image.LANCZOS)
    fundo = fundo.filter(ImageFilter.GaussianBlur(40))
    fundo = Image.blend(fundo, Image.new("RGB", fundo.size, COR_SOMBRA), 0.25)
    frente = ImageOps.contain(foto, (LARGURA, ALTURA), Image.LANCZOS)
    fundo.paste(frente, ((LARGURA - frente.width) // 2, (ALTURA - frente.height) // 2))
    return fundo


def _degrade(altura_inicio: int) -> Image.Image:
    """Camada RGBA: transparente em `altura_inicio`, escura na base."""
    camada = Image.new("RGBA", (LARGURA, ALTURA), (0, 0, 0, 0))
    desenho = ImageDraw.Draw(camada)
    faixa = ALTURA - altura_inicio
    for y in range(altura_inicio, ALTURA):
        t = (y - altura_inicio) / faixa
        alfa = int(235 * (t ** 1.2))
        desenho.line([(0, y), (LARGURA, y)], fill=(*COR_SOMBRA, alfa))
    return camada


def _quebrar(texto: str, fonte: ImageFont.FreeTypeFont, largura_max: int) -> list[str]:
    """Quebra no menor número de linhas e, com ele fixo, nas linhas mais iguais.

    Quebrar só pelo limite deixa palavra órfã ("A mochila que vai com / tudo."),
    que lê como erro. Fixado o número de linhas, aperta a largura até o ponto
    em que mais uma linha seria necessária: as linhas saem parecidas.
    """
    def cabe(linhas: list[str], limite: float) -> bool:
        return all(fonte.getlength(linha) <= limite for linha in linhas)

    melhor: list[str] | None = None
    for largura in range(len(texto), 0, -1):
        linhas = textwrap.wrap(texto, width=largura)
        if not cabe(linhas, largura_max):
            continue
        if melhor is None:
            melhor = linhas
        elif len(linhas) > len(melhor):
            break
        else:
            melhor = linhas
    return melhor or [texto]


def _espacado(desenho, xy, texto, fonte, cor, espaco) -> None:
    x, y = xy
    for letra in texto:
        desenho.text((x, y), letra, font=fonte, fill=cor)
        x += fonte.getlength(letra) + espaco


def desenhar(foto: Image.Image, cta: Cta) -> Image.Image:
    """Devolve a imagem 1080x1920 com o CTA gravado."""
    base = enquadrar(foto).convert("RGBA")

    # Botão: tamanho fixo de fonte, encolhe só se a frase não couber.
    tamanho = 42
    fonte_acao = _fonte(FONTE_ACAO, tamanho)
    while fonte_acao.getlength(cta.acao) > LARGURA - 260 and tamanho > 30:
        tamanho -= 2
        fonte_acao = _fonte(FONTE_ACAO, tamanho)
    caixa = fonte_acao.getbbox(cta.acao)
    texto_l, texto_a = caixa[2] - caixa[0], caixa[3] - caixa[1]
    pad_x, pad_y = 46, 30
    pil_l, pil_a = texto_l + 2 * pad_x, texto_a + 2 * pad_y
    pil_y = BASE_SEGURA - pil_a
    pil_x = (LARGURA - pil_l) // 2

    # Título: até 3 linhas, encolhe até caber.
    linhas: list[str] = []
    fonte_titulo = None
    altura_linha = 0
    if cta.titulo:
        for tamanho in range(84, 55, -4):
            fonte_titulo = _fonte(FONTE_TITULO, tamanho)
            linhas = _quebrar(cta.titulo, fonte_titulo, LARGURA - 160)
            if len(linhas) <= 3:
                break
        altura_linha = int(fonte_titulo.size * 1.18)

    titulo_altura = altura_linha * len(linhas)
    titulo_y = pil_y - 44 - titulo_altura
    fonte_marca = _fonte(FONTE_MARCA, 26)
    marca_y = (titulo_y if linhas else pil_y) - 58

    inicio_degrade = max(TOPO_SEGURO, marca_y - 420)
    base = Image.alpha_composite(base, _degrade(inicio_degrade))
    desenho = ImageDraw.Draw(base)

    marca, espaco = "LINE STORE", 9
    marca_l = sum(fonte_marca.getlength(c) for c in marca) + espaco * (len(marca) - 1)
    _espacado(
        desenho, ((LARGURA - marca_l) / 2, marca_y), marca, fonte_marca,
        (*COR_TEXTO, 215), espaco,
    )

    # Sombra difusa atrás do título: o degradê sozinho não segura serifa fina
    # sobre foto clara ou colagem.
    if linhas:
        halo = Image.new("RGBA", base.size, (0, 0, 0, 0))
        desenho_halo = ImageDraw.Draw(halo)
        for i, linha in enumerate(linhas):
            desenho_halo.text(
                (LARGURA / 2, titulo_y + i * altura_linha), linha, font=fonte_titulo,
                fill=(*COR_SOMBRA, 200), anchor="ma", stroke_width=6,
                stroke_fill=(*COR_SOMBRA, 200),
            )
        base = Image.alpha_composite(base, halo.filter(ImageFilter.GaussianBlur(18)))
        desenho = ImageDraw.Draw(base)
    for i, linha in enumerate(linhas):
        y = titulo_y + i * altura_linha
        desenho.text(
            (LARGURA / 2, y), linha, font=fonte_titulo, fill=COR_TEXTO, anchor="ma",
        )

    # Sombra suave sob a pílula, para ela não "flutuar" sobre foto clara.
    sombra = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(sombra).rounded_rectangle(
        (pil_x, pil_y + 8, pil_x + pil_l, pil_y + pil_a + 8),
        radius=pil_a // 2, fill=(0, 0, 0, 90),
    )
    base = Image.alpha_composite(base, sombra.filter(ImageFilter.GaussianBlur(14)))
    desenho = ImageDraw.Draw(base)
    desenho.rounded_rectangle(
        (pil_x, pil_y, pil_x + pil_l, pil_y + pil_a), radius=pil_a // 2, fill=COR_PILULA,
    )
    desenho.text(
        (pil_x + pad_x - caixa[0], pil_y + pad_y - caixa[1]), cta.acao,
        font=fonte_acao, fill=COR_PILULA_TEXTO,
    )
    return base.convert("RGB")


def renderizar(origem: bytes, cta: Cta) -> bytes:
    """Bytes da foto original → bytes do JPEG com CTA, pronto para a API."""
    try:
        foto = Image.open(io.BytesIO(origem))
        foto.load()
    except Exception as exc:  # Pillow levanta tipos variados
        raise CtaError(f"não consegui abrir a imagem: {exc}") from exc
    saida = io.BytesIO()
    desenhar(foto, cta).save(saida, "JPEG", quality=90, optimize=True, progressive=True)
    return saida.getvalue()


# --------------------------------------------------------------------------
# Aplicação na fila
# --------------------------------------------------------------------------

DESTINO_SUBDIR = "media/stories-cta"


@dataclass(frozen=True)
class Resultado:
    gerados: list[str]
    mantidos: list[str]
    removidos: list[str]
    falhas: list[str]


def aplicar(
    itens: list[dict],
    *,
    ler_origem: Callable[[str], bytes],
    raiz: str,
    repo: str,
    branch: str = "main",
    forcar: bool = False,
) -> Resultado:
    """Gera a imagem com CTA de cada item que pede, e troca a `url` dele.

    Mexe nos dicionários no lugar. Cada item com `cta` ganha:

    - `url_original`: a foto sem texto, de onde a imagem é gerada de novo;
    - `url`: a imagem com CTA, servida pelo jsDelivr a partir deste repo;
    - `cta_render`: a assinatura do que foi desenhado.

    A assinatura entra no nome do arquivo de propósito: o jsDelivr guarda em
    cache um caminho de `@main` por dias, então trocar o texto e regravar no
    mesmo nome publicaria o CTA velho. Nome novo, cache novo.

    Item que perdeu o `cta` volta para a `url_original` — tirar o texto da
    fila tira o texto do story.
    """
    from .rehost import public_url

    gerados: list[str] = []
    mantidos: list[str] = []
    removidos: list[str] = []
    falhas: list[str] = []
    destino_dir = os.path.join(raiz, DESTINO_SUBDIR)

    for item in itens:
        item_id = str(item.get("id") or "")
        if str(item.get("media_type") or "").upper() != "STORIES":
            continue
        anterior = _arquivo_gerado(item, raiz)
        if item.get("cta") is None:
            if item.get("url_original"):
                item["url"] = item.pop("url_original")
                item.pop("cta_render", None)
                _apagar(anterior)
                removidos.append(item_id)
            continue
        try:
            cta = ler_cta(item["cta"])
            origem = str(item.get("url_original") or item.get("url") or "")
            if origem.lower().endswith((".mp4", ".mov")):
                raise CtaError("vídeo não recebe CTA gravado")
            assinatura = cta.assinatura(origem)
            nome = f"{item_id}-{assinatura}.jpg"
            caminho = os.path.join(destino_dir, nome)
            if not forcar and item.get("cta_render") == assinatura and os.path.exists(caminho):
                mantidos.append(item_id)
                continue
            imagem = renderizar(ler_origem(origem), cta)
        except Exception as exc:  # um item ruim não para os outros
            falhas.append(f"{item_id}: {exc}")
            continue

        os.makedirs(destino_dir, exist_ok=True)
        with open(caminho, "wb") as handle:
            handle.write(imagem)
        if anterior and os.path.abspath(anterior) != os.path.abspath(caminho):
            _apagar(anterior)
        item["url_original"] = origem
        item["url"] = public_url(repo, branch, f"{DESTINO_SUBDIR}/{nome}")
        item["cta_render"] = assinatura
        gerados.append(item_id)

    return Resultado(gerados, mantidos, removidos, falhas)


def _arquivo_gerado(item: dict, raiz: str) -> str:
    """Caminho local da imagem com CTA que o item usa hoje, se for nossa."""
    url = str(item.get("url") or "")
    marca = f"/{DESTINO_SUBDIR}/"
    if not item.get("url_original") or marca not in url:
        return ""
    return os.path.join(raiz, DESTINO_SUBDIR, url.rsplit("/", 1)[1])


def _apagar(caminho: str) -> None:
    if caminho and os.path.exists(caminho):
        os.remove(caminho)
