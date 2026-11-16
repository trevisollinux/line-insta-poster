"""Lê e valida `dm/fluxos.yaml`.

A validação é estrita de propósito: um fluxo quebrado só se revela quando um
cliente comenta, e aí a resposta não sai (ou sai errada) para uma pessoa real.
Melhor o CI recusar o push.

Os limites (640 caracteres, 3 botões, 20 caracteres no botão) são os da Send API
para o template de botões. Passar deles faz a Meta recusar a mensagem inteira.
"""
from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, field

import yaml

from .. import REPO_ROOT

FLUXOS_PATH = os.path.join(REPO_ROOT, "dm", "fluxos.yaml")

ONDE = ("comentario", "story", "dm")
MAX_TEXTO_COM_BOTOES = 640
MAX_TEXTO = 1000
MAX_BOTOES = 3
MAX_TITULO_BOTAO = 20

# Texto de exemplo que ninguém trocou. Mandar "TROCAR" como cupom para um
# cliente queima mais confiança do que não responder: o arquivo valida (o CI
# fica verde), mas o `dm-exportar` (o deploy) se recusa enquanto houver um.
MARCADOR_PENDENTE = "TROCAR"

PREFIXO_PAYLOAD = "passo:"


class FluxosInvalidos(ValueError):
    """Um ou mais problemas no arquivo; a mensagem lista todos."""


@dataclass(frozen=True)
class Botao:
    titulo: str
    vai_para: str = ""  # id de passo (postback)
    url: str = ""  # link externo (web_url)


@dataclass(frozen=True)
class Passo:
    id: str
    texto: str
    botoes: tuple[Botao, ...] = ()
    uma_vez: bool = False
    se_repetido: str = ""


@dataclass(frozen=True)
class Gatilho:
    nome: str
    onde: str
    passo: str
    palavras: tuple[str, ...] = ()
    posts: tuple[str, ...] = ()
    resposta_publica: tuple[str, ...] = ()

    def casa(self, texto: str, media_id: str = "") -> bool:
        if self.posts and media_id not in self.posts:
            return False
        normal = normalizar(texto)
        return any(_contem_palavra(normal, normalizar(p)) for p in self.palavras)


@dataclass(frozen=True)
class Fluxos:
    passos: dict[str, Passo] = field(default_factory=dict)
    gatilhos: tuple[Gatilho, ...] = ()
    pendentes: tuple[str, ...] = ()  # textos com TROCAR: valida, mas não liga

    def gatilho_para(self, onde: str, texto: str, media_id: str = "") -> Gatilho | None:
        for gatilho in self.gatilhos:
            if gatilho.onde == onde and gatilho.casa(texto, media_id):
                return gatilho
        return None


def normalizar(texto: str) -> str:
    """Minúsculas e sem acento: 'CUPOM!', 'cupom' e 'cúpom' são a mesma palavra."""
    decomposto = unicodedata.normalize("NFKD", texto or "")
    sem_acento = "".join(c for c in decomposto if not unicodedata.combining(c))
    return " ".join(sem_acento.lower().split())


def _contem_palavra(texto: str, palavra: str) -> bool:
    # Fronteira de palavra: "quero" não pode disparar em "queroseno".
    return bool(palavra) and re.search(rf"(?<!\w){re.escape(palavra)}(?!\w)", texto) is not None


def carregar(caminho: str = FLUXOS_PATH) -> Fluxos:
    with open(caminho, encoding="utf-8") as handle:
        bruto = yaml.safe_load(handle) or {}
    return interpretar(bruto)


def interpretar(bruto: object) -> Fluxos:
    erros = _Erros()
    if not isinstance(bruto, dict):
        raise FluxosInvalidos("o arquivo precisa ter as chaves `passos` e `gatilhos`")

    passos: dict[str, Passo] = {}
    for pid, dados in (bruto.get("passos") or {}).items():
        passo = _ler_passo(str(pid), dados, erros)
        if passo:
            passos[passo.id] = passo

    gatilhos: list[Gatilho] = []
    nomes: set[str] = set()
    for i, dados in enumerate(bruto.get("gatilhos") or [], start=1):
        gatilho = _ler_gatilho(i, dados, erros)
        if not gatilho:
            continue
        if gatilho.nome in nomes:
            erros.append(f"gatilho '{gatilho.nome}': nome repetido")
        nomes.add(gatilho.nome)
        gatilhos.append(gatilho)

    # Referências: todo destino precisa existir.
    for gatilho in gatilhos:
        if gatilho.passo not in passos:
            erros.append(f"gatilho '{gatilho.nome}': passo '{gatilho.passo}' não existe")
    for passo in passos.values():
        for botao in passo.botoes:
            if botao.vai_para and botao.vai_para not in passos:
                erros.append(
                    f"passo '{passo.id}': botão '{botao.titulo}' vai para "
                    f"'{botao.vai_para}', que não existe"
                )

    if erros:
        raise FluxosInvalidos("\n".join(f"- {e}" for e in erros))
    return Fluxos(
        passos=passos, gatilhos=tuple(gatilhos), pendentes=tuple(dict.fromkeys(erros.pendentes))
    )


def _ler_passo(pid: str, dados: object, erros: list[str]) -> Passo | None:
    onde = f"passo '{pid}'"
    if not isinstance(dados, dict):
        erros.append(f"{onde}: precisa ser um mapa com `texto`")
        return None
    texto = str(dados.get("texto") or "").strip()
    if not texto:
        erros.append(f"{onde}: `texto` vazio")
    _checar_pendente(onde, texto, erros)

    botoes: list[Botao] = []
    for bdados in dados.get("botoes") or []:
        if not isinstance(bdados, dict):
            erros.append(f"{onde}: botão precisa ser um mapa com `titulo`")
            continue
        titulo = str(bdados.get("titulo") or "").strip()
        vai_para = str(bdados.get("vai_para") or "").strip()
        url = str(bdados.get("url") or "").strip()
        if not titulo:
            erros.append(f"{onde}: botão sem `titulo`")
        elif len(titulo) > MAX_TITULO_BOTAO:
            erros.append(
                f"{onde}: botão '{titulo}' tem {len(titulo)} caracteres "
                f"(máximo {MAX_TITULO_BOTAO})"
            )
        if bool(vai_para) == bool(url):
            erros.append(f"{onde}: botão '{titulo}' precisa de `vai_para` OU `url`")
        if url and not url.startswith("https://"):
            erros.append(f"{onde}: botão '{titulo}': url precisa começar com https://")
        _checar_pendente(f"{onde}, botão '{titulo}'", url, erros)
        botoes.append(Botao(titulo=titulo, vai_para=vai_para, url=url))

    if len(botoes) > MAX_BOTOES:
        erros.append(f"{onde}: {len(botoes)} botões (máximo {MAX_BOTOES})")
    limite = MAX_TEXTO_COM_BOTOES if botoes else MAX_TEXTO
    if len(texto) > limite:
        erros.append(f"{onde}: texto com {len(texto)} caracteres (máximo {limite})")

    se_repetido = str(dados.get("se_repetido") or "").strip()
    uma_vez = bool(dados.get("uma_vez", False))
    if se_repetido and not uma_vez:
        erros.append(f"{onde}: `se_repetido` só faz sentido com `uma_vez: true`")
    _checar_pendente(onde, se_repetido, erros)

    return Passo(
        id=pid, texto=texto, botoes=tuple(botoes), uma_vez=uma_vez, se_repetido=se_repetido
    )


def _ler_gatilho(i: int, dados: object, erros: list[str]) -> Gatilho | None:
    if not isinstance(dados, dict):
        erros.append(f"gatilho #{i}: precisa ser um mapa")
        return None
    nome = str(dados.get("nome") or f"#{i}").strip()
    onde = str(dados.get("onde") or "").strip()
    rotulo = f"gatilho '{nome}'"
    if onde not in ONDE:
        erros.append(f"{rotulo}: `onde` deve ser um de {', '.join(ONDE)}")

    palavras = tuple(str(p).strip() for p in dados.get("palavras") or [] if str(p).strip())
    if not palavras:
        # Sem palavra, todo comentário, DM ou resposta a story dispararia —
        # inclusive a cliente respondendo o CTA "qual sua cor?", que é venda e
        # é de gente (README, "Ação preferida: responder o story").
        erros.append(f"{rotulo}: `palavras` é obrigatório")

    posts = tuple(str(p).strip() for p in dados.get("posts") or [] if str(p).strip())
    publicas = tuple(
        str(p).strip() for p in dados.get("resposta_publica") or [] if str(p).strip()
    )
    if (posts or publicas) and onde != "comentario":
        erros.append(f"{rotulo}: `posts` e `resposta_publica` só valem em comentario")
    for texto in publicas:
        _checar_pendente(rotulo, texto, erros)

    passo = str(dados.get("passo") or "").strip()
    if not passo:
        erros.append(f"{rotulo}: `passo` vazio")
    return Gatilho(
        nome=nome, onde=onde, passo=passo, palavras=palavras, posts=posts,
        resposta_publica=publicas,
    )


class _Erros(list):
    """Lista de erros que também junta os textos ainda com TROCAR."""

    def __init__(self) -> None:
        super().__init__()
        self.pendentes: list[str] = []


def _checar_pendente(onde: str, texto: str, erros: list[str]) -> None:
    if MARCADOR_PENDENTE in texto and isinstance(erros, _Erros):
        erros.pendentes.append(f"{onde}: ainda tem '{MARCADOR_PENDENTE}'")


def montar_mensagem(passo: Passo, *, repetido: bool = False) -> dict:
    """Corpo `message` da Send API: texto puro ou template de botões."""
    if repetido:
        return {"text": passo.se_repetido}
    if not passo.botoes:
        return {"text": passo.texto}
    botoes = []
    for botao in passo.botoes:
        if botao.url:
            botoes.append({"type": "web_url", "url": botao.url, "title": botao.titulo})
        else:
            botoes.append(
                {
                    "type": "postback",
                    "title": botao.titulo,
                    "payload": PREFIXO_PAYLOAD + botao.vai_para,
                }
            )
    return {
        "attachment": {
            "type": "template",
            "payload": {"template_type": "button", "text": passo.texto, "buttons": botoes},
        }
    }


def montar_alternativa(passo: Passo) -> dict:
    """Se o template for recusado: texto com os links + respostas rápidas.

    Respostas rápidas viram o mesmo payload dos botões, então o fluxo continua
    igual — só muda a aparência.
    """
    linhas = [passo.texto]
    linhas += [f"{b.titulo}: {b.url}" for b in passo.botoes if b.url]
    mensagem: dict = {"text": "\n\n".join(linhas)[:MAX_TEXTO]}
    rapidas = [
        {"content_type": "text", "title": b.titulo, "payload": PREFIXO_PAYLOAD + b.vai_para}
        for b in passo.botoes
        if b.vai_para
    ]
    if rapidas:
        mensagem["quick_replies"] = rapidas
    return mensagem


def exportar(fluxos: Fluxos) -> dict:
    """JSON que o Worker lê: palavras já normalizadas, mensagens já montadas.

    O Worker não sabe ler YAML nem montar template — toda regra de formato fica
    deste lado, num lugar só, coberta pelos testes em Python.
    """
    return {
        "gatilhos": [
            {
                "nome": g.nome,
                "onde": g.onde,
                "passo": g.passo,
                "palavras": [normalizar(p) for p in g.palavras],
                "posts": list(g.posts),
                "resposta_publica": list(g.resposta_publica),
            }
            for g in fluxos.gatilhos
        ],
        "passos": {
            p.id: {
                "mensagem": montar_mensagem(p),
                "alternativa": montar_alternativa(p) if p.botoes else None,
                "uma_vez": p.uma_vez,
                "repetido": montar_mensagem(p, repetido=True) if p.se_repetido else None,
            }
            for p in fluxos.passos.values()
        },
    }
