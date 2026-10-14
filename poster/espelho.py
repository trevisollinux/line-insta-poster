"""Confere se a mídia hospedada no jsDelivr está de pé antes de mandar à Meta.

Em 14/10 o story do dia falhou cinco vezes seguidas: o jsDelivr devolveu 404
(ou estourou o tempo) para fotos que estavam no repositório de mídia desde
setembro. A Meta, ao buscar a URL, recebeu a página de erro e respondeu
`2207052 — Only photo or video can be accepted`. O vídeo do mesmo lote saiu
normalmente; o problema era o cache do CDN para aqueles arquivos, não o
arquivo.

Por isso, antes de criar o container:

1. baixa o começo da URL e confere se veio imagem/vídeo;
2. se não veio, pede ao jsDelivr para limpar o cache daquele arquivo
   (`purge.jsdelivr.net`, API pública) e tenta de novo;
3. se ainda não veio e é foto, usa o mesmo arquivo pelo
   `raw.githubusercontent.com`, que serve .jpg como `image/jpeg`. Vídeo não
   tem essa saída: o raw entrega .mp4 como octet-stream e a Meta recusa
   (ver rehost.py).

Se nada funcionar, devolve a URL original e deixa a API decidir — travar a
publicação aqui trocaria um aviso por um dia sem story.
"""
from __future__ import annotations

import re
import time
import urllib.request
from typing import Callable

JSDELIVR = re.compile(r"^https://cdn\.jsdelivr\.net/gh/([^/]+)/([^/@]+)@([^/]+)/(.+)$")
PURGE_HOST = "https://purge.jsdelivr.net/gh"
RAW_HOST = "https://raw.githubusercontent.com"
TIPOS_ACEITOS = ("image/", "video/")

Abridor = Callable[..., object]


def _partes(url: str) -> tuple[str, str, str, str] | None:
    achado = JSDELIVR.match(url)
    return achado.groups() if achado else None  # type: ignore[return-value]


def url_purge(url: str) -> str | None:
    partes = _partes(url)
    if not partes:
        return None
    dono, repo, ref, caminho = partes
    return f"{PURGE_HOST}/{dono}/{repo}@{ref}/{caminho}"


def url_raw(url: str) -> str | None:
    partes = _partes(url)
    if not partes:
        return None
    dono, repo, ref, caminho = partes
    return f"{RAW_HOST}/{dono}/{repo}/{ref}/{caminho}"


def serve_midia(url: str, *, abrir: Abridor = urllib.request.urlopen, timeout: int = 30) -> str:
    """Motivo de a URL não servir mídia, ou texto vazio se serve."""
    try:
        with abrir(url, timeout=timeout) as resposta:  # type: ignore[attr-defined]
            tipo = (resposta.headers.get("Content-Type") or "").lower()
            resposta.read(1024)
    except OSError as exc:
        return str(exc)
    if not tipo.startswith(TIPOS_ACEITOS):
        return f"tipo {tipo or 'vazio'}"
    return ""


def url_que_funciona(
    url: str,
    *,
    is_video: bool,
    abrir: Abridor = urllib.request.urlopen,
    esperar: Callable[[float], None] = time.sleep,
) -> str:
    """A URL a mandar para a Meta: a original, ou a alternativa que respondeu."""
    if not _partes(url):
        return url
    problema = serve_midia(url, abrir=abrir)
    if not problema:
        return url

    print(f"  aviso: jsDelivr não entregou a mídia ({problema}) — limpando o cache")
    try:
        with abrir(url_purge(url), timeout=30):  # type: ignore[attr-defined]
            pass
        esperar(5)
        if not serve_midia(url, abrir=abrir):
            print("  jsDelivr voltou a entregar depois da limpeza")
            return url
    except OSError as exc:
        print(f"  aviso: limpeza do cache falhou ({exc})")

    if is_video:
        return url
    alternativa = url_raw(url)
    problema = serve_midia(alternativa, abrir=abrir)
    if problema:
        print(f"  aviso: link direto do GitHub também falhou ({problema})")
        return url
    print(f"  usando o link direto do GitHub: {alternativa}")
    return alternativa
