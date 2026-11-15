"""Traduz o JSON do webhook da Meta em eventos simples.

O webhook do Instagram chega em dois formatos no mesmo corpo:

- `entry[].messaging[]` — mensagens, respostas a story, toques em botão
- `entry[].changes[]`   — comentários (campo `comments`)

Tudo que não interessa é descartado aqui, para o motor só ver o que pode
disparar resposta. Principalmente o **eco**: a Meta reenvia como evento cada
mensagem que *nós* mandamos (`is_echo`). Responder ao eco é o laço infinito
clássico de bot.
"""
from __future__ import annotations

from dataclasses import dataclass

from .fluxos import PREFIXO_PAYLOAD


@dataclass(frozen=True)
class Evento:
    tipo: str  # "comentario" | "story" | "dm" | "botao"
    id: str  # mid ou id do comentário — chave de deduplicação
    usuario: str  # IGSID de quem escreveu
    texto: str = ""
    comentario_id: str = ""
    media_id: str = ""
    passo: str = ""  # destino do botão tocado

    @property
    def onde(self) -> str:
        return self.tipo


def extrair(corpo: dict, *, conta_id: str = "") -> list[Evento]:
    """Eventos acionáveis do corpo do webhook. `conta_id` é o IG_USER_ID da loja."""
    if corpo.get("object") != "instagram":
        return []
    eventos: list[Evento] = []
    for entrada in corpo.get("entry") or []:
        for item in entrada.get("messaging") or []:
            evento = _de_mensagem(item, conta_id)
            if evento:
                eventos.append(evento)
        for mudanca in entrada.get("changes") or []:
            evento = _de_comentario(mudanca, conta_id)
            if evento:
                eventos.append(evento)
    return eventos


def _de_mensagem(item: dict, conta_id: str) -> Evento | None:
    usuario = str((item.get("sender") or {}).get("id") or "")
    if not usuario or (conta_id and usuario == conta_id):
        return None

    postback = item.get("postback")
    if postback:
        passo = _passo_do_payload(postback.get("payload"))
        if not passo:
            return None
        mid = str(postback.get("mid") or f"pb-{usuario}-{item.get('timestamp')}")
        return Evento(tipo="botao", id=mid, usuario=usuario, passo=passo)

    mensagem = item.get("message")
    if not mensagem or mensagem.get("is_echo") or mensagem.get("is_deleted"):
        return None
    mid = str(mensagem.get("mid") or "")
    if not mid:
        return None

    # Resposta rápida tocada: mesma coisa que botão.
    rapida = mensagem.get("quick_reply")
    if rapida:
        passo = _passo_do_payload(rapida.get("payload"))
        if passo:
            return Evento(tipo="botao", id=mid, usuario=usuario, passo=passo)

    texto = str(mensagem.get("text") or "")
    if (mensagem.get("reply_to") or {}).get("story"):
        return Evento(tipo="story", id=mid, usuario=usuario, texto=texto)
    if not texto:
        return None  # foto, áudio, reação: humano responde
    return Evento(tipo="dm", id=mid, usuario=usuario, texto=texto)


def _de_comentario(mudanca: dict, conta_id: str) -> Evento | None:
    if mudanca.get("field") != "comments":
        return None
    valor = mudanca.get("value") or {}
    autor = valor.get("from") or {}
    usuario = str(autor.get("id") or "")
    comentario_id = str(valor.get("id") or "")
    if not usuario or not comentario_id:
        return None
    if conta_id and usuario == conta_id:
        return None  # a própria loja respondendo: não é gatilho
    return Evento(
        tipo="comentario",
        id=comentario_id,
        usuario=usuario,
        texto=str(valor.get("text") or ""),
        comentario_id=comentario_id,
        media_id=str((valor.get("media") or {}).get("id") or ""),
    )


def _passo_do_payload(payload: object) -> str:
    texto = str(payload or "")
    return texto[len(PREFIXO_PAYLOAD):] if texto.startswith(PREFIXO_PAYLOAD) else ""
