"""Decide o que responder a cada evento. Não toca a rede.

Esta é a versão de referência, usada em `dm-simular`. Quem decide em produção
é `worker/src/motor.js`; `tests/dm_casos.json` roda nas duas e garante que
concordam.

A regra mais importante está no que o motor **não** faz: mensagem que não casa
com nenhum gatilho não recebe resposta. O direct da loja é onde se vende, e
quem responde "quanto custa a caramelo?" é gente. O bot só entra quando alguém
pede com a palavra combinada, toca num botão dele ou responde um story.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable

from .estado import Estado
from .fluxos import Fluxos, Passo, montar_alternativa, montar_mensagem


@dataclass(frozen=True)
class Evento:
    """Já traduzido do webhook (no Worker, `worker/src/motor.js`)."""

    tipo: str  # "comentario" | "story" | "dm" | "botao"
    id: str
    usuario: str
    texto: str = ""
    comentario_id: str = ""
    media_id: str = ""
    passo: str = ""  # destino do botão tocado

    @property
    def onde(self) -> str:
        return self.tipo


@dataclass(frozen=True)
class Acao:
    tipo: str  # "enviar" | "responder_comentario"
    destinatario: dict | None = None  # {"id": IGSID} ou {"comment_id": id}
    mensagem: dict | None = None
    alternativa: dict | None = None  # se o template for recusado
    comentario_id: str = ""
    texto: str = ""  # resposta pública ao comentário
    registrar: tuple[str, str] | None = None  # (usuario, passo) após enviar

    def descrever(self) -> str:
        if self.tipo == "responder_comentario":
            return f"responde em público no comentário {self.comentario_id}: {self.texto!r}"
        corpo = self.mensagem or {}
        texto = corpo.get("text") or (
            corpo.get("attachment", {}).get("payload", {}).get("text", "")
        )
        botoes = corpo.get("attachment", {}).get("payload", {}).get("buttons", [])
        extra = f" [botões: {', '.join(b['title'] for b in botoes)}]" if botoes else ""
        return f"DM para {self.destinatario}: {texto!r}{extra}"

    def como_dict(self) -> dict:
        """Forma comparável com o Worker (casos compartilhados nos testes)."""
        bruto = {
            "tipo": self.tipo,
            "destinatario": self.destinatario,
            "mensagem": self.mensagem,
            "alternativa": self.alternativa,
            "comentario_id": self.comentario_id,
            "texto": self.texto,
            "registrar": list(self.registrar) if self.registrar else None,
        }
        return {k: v for k, v in bruto.items() if v}


def decidir(
    evento: Evento,
    fluxos: Fluxos,
    estado: Estado,
    *,
    sortear: Callable[[tuple[str, ...]], str] = lambda opcoes: random.choice(opcoes),
) -> list[Acao]:
    if evento.tipo == "botao":
        passo = fluxos.passos.get(evento.passo)
        if not passo:
            return []  # botão de uma versão antiga do arquivo
        return _enviar(passo, {"id": evento.usuario}, evento.usuario, estado)

    gatilho = fluxos.gatilho_para(evento.onde, evento.texto, evento.media_id)
    if not gatilho:
        return []
    passo = fluxos.passos[gatilho.passo]

    if evento.tipo == "comentario":
        # Resposta privada: o destinatário é o comentário, não a pessoa. É o
        # único jeito de mandar DM para quem nunca escreveu no direct. Vale uma
        # vez por comentário, até 7 dias depois dele.
        acoes = _enviar(passo, {"comment_id": evento.comentario_id}, evento.usuario, estado)
        if gatilho.resposta_publica:
            acoes.append(
                Acao(
                    tipo="responder_comentario",
                    comentario_id=evento.comentario_id,
                    texto=sortear(gatilho.resposta_publica),
                )
            )
        return acoes

    return _enviar(passo, {"id": evento.usuario}, evento.usuario, estado)


def _enviar(passo: Passo, destinatario: dict, usuario: str, estado: Estado) -> list[Acao]:
    if passo.uma_vez and estado.ja_entregue(usuario, passo.id):
        if not passo.se_repetido:
            return []
        return [
            Acao(
                tipo="enviar",
                destinatario=destinatario,
                mensagem=montar_mensagem(passo, repetido=True),
            )
        ]
    return [
        Acao(
            tipo="enviar",
            destinatario=destinatario,
            mensagem=montar_mensagem(passo),
            alternativa=montar_alternativa(passo) if passo.botoes else None,
            registrar=(usuario, passo.id) if passo.uma_vez else None,
        )
    ]
