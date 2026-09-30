"""Trava de proporção para foto de story — o Instagram estica o que não é 9:16.

A Graph API aceita foto de story em qualquer proporção e não avisa: ela
simplesmente estica a imagem até preencher a tela vertical. Duas fotos saíram
assim e foram apagadas à mão — a de 23/09 (1440x1851) e a de 29/09
(2688x4119). A falha é silenciosa, então a trava precisa vir antes.

Ela existe em dois pontos:

- na importação do Drive, para a foto torta nem entrar na fila;
- na publicação, como segunda barreira para o que já estava na fila ou foi
  acrescentado à mão.

A foto recusada não é corrigida — nem com faixa, nem com fundo desfocado, nem
com recorte. Decisão do Gustavo em 23/09: "não queremos com branco ou embaçado
ao fundo". O conserto é reenquadrar a foto e largá-la de novo na pasta.

Vídeo fica de fora: o Instagram põe tarja em vídeo fora de 9:16, não estica.
"""
from __future__ import annotations

import io
import urllib.request
from typing import Callable

# 9:16, a tela do story.
PROPORCAO_STORY = 9 / 16

# Folga relativa. As fotos de celular medem 0,561 a 0,563; as do Photoroom em
# 768x1344 e 714x1248 ficam em 0,571-0,572 (1,6 % acima) e a diferença não se
# vê. As que esticaram estavam em 0,653 (16 %) e 0,778 (38 %). Três por cento
# separa com folga os dois grupos.
TOLERANCIA = 0.03

# Uma foto de story cabe com sobra nisto; o limite só evita baixar algo enorme
# por engano na checagem da publicação.
MAX_BYTES = 30 * 1024 * 1024

# Tag EXIF de orientação e os valores em que a foto é exibida girada 90°.
ORIENTACAO_EXIF = 0x0112
GIRADA_90 = {5, 6, 7, 8}


class ProporcaoError(RuntimeError):
    """Não deu para medir a imagem (download ou arquivo ilegível)."""


def problema(largura: int, altura: int, *, tolerancia: float = TOLERANCIA) -> str:
    """Motivo da recusa, ou texto vazio quando a foto serve para story."""
    if largura <= 0 or altura <= 0:
        return f"dimensões inválidas ({largura}x{altura})"
    razao = largura / altura
    desvio = abs(razao / PROPORCAO_STORY - 1)
    if desvio <= tolerancia:
        return ""
    forma = "larga" if razao > PROPORCAO_STORY else "estreita"
    return (
        f"foto fora do formato de story: {largura}x{altura} é {forma} demais "
        f"para 9:16 e sairia esticada — reenquadre para 1080x1920"
    )


def medir_bytes(dados: bytes) -> tuple[int, int]:
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - ambiente sem Pillow
        raise ProporcaoError(
            "Pillow não instalado — necessário para medir a foto "
            "(pip install -r requirements.txt)"
        ) from exc
    try:
        with Image.open(io.BytesIO(dados)) as imagem:
            largura, altura = imagem.size
            # Celular costuma gravar a foto em pé com os pixels deitados e uma
            # marca EXIF mandando girar 90°. Sem olhar a marca, uma foto 9:16
            # boa mediria como horizontal e seria recusada.
            orientacao = imagem.getexif().get(ORIENTACAO_EXIF, 1)
    except OSError as exc:
        raise ProporcaoError(f"não consegui ler a imagem: {exc}") from exc
    if orientacao in GIRADA_90:
        return altura, largura
    return largura, altura


def medir_arquivo(caminho: str) -> tuple[int, int]:
    with open(caminho, "rb") as handle:
        return medir_bytes(handle.read())


def medir_url(
    url: str,
    *,
    opener: Callable[..., object] = urllib.request.urlopen,
    timeout: int = 60,
) -> tuple[int, int]:
    try:
        with opener(url, timeout=timeout) as resposta:  # type: ignore[attr-defined]
            dados = resposta.read(MAX_BYTES + 1)
    except OSError as exc:
        raise ProporcaoError(f"não consegui baixar a imagem para medir: {exc}") from exc
    if len(dados) > MAX_BYTES:
        raise ProporcaoError("imagem grande demais para medir")
    return medir_bytes(dados)
