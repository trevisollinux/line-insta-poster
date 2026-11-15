"""Executa as ações do motor pela Graph API.

Mensagens saem por `POST /me/messages` com o **token da Página** — não o token
de usuário que a publicação usa. O de Página derivado de um token de usuário de
longa duração não expira, e por isso o servidor não depende da renovação
mensal que regrava o secret do GitHub (ele nem enxerga esse secret).
"""
from __future__ import annotations

import json
import sys
import time
from typing import Callable

from ..alerts import alert
from ..graph import GraphError
from .estado import Estado
from .eventos import Evento
from .fluxos import Fluxos
from .motor import Acao, decidir

# Mesmo erro alertado de novo só depois disso. Sem permissão, *toda* mensagem
# falha — um alerta por cliente seria spam no canal.
JANELA_ALERTA = 3600


class Enviador:
    def __init__(
        self,
        client,
        *,
        dry_run: bool = False,
        alert_webhook: str = "",
        log: Callable[[str], None] = lambda m: print(m, file=sys.stderr, flush=True),
        relogio: Callable[[], float] = time.time,
    ) -> None:
        self.client = client
        self.dry_run = dry_run
        self.alert_webhook = alert_webhook
        self.log = log
        self.relogio = relogio
        self._alertados: dict[str, float] = {}

    def executar(self, acao: Acao, estado: Estado) -> bool:
        if self.dry_run:
            self.log(f"[dry-run] {acao.descrever()}")
            if acao.registrar:
                estado.registrar_entrega(*acao.registrar)
            return True
        try:
            if acao.tipo == "responder_comentario":
                self.client.post(f"{acao.comentario_id}/replies", {"message": acao.texto})
            else:
                self._enviar_mensagem(acao)
        except GraphError as exc:
            self._alertar(exc, acao)
            return False
        if acao.registrar:
            estado.registrar_entrega(*acao.registrar)
        self.log(f"ok: {acao.descrever()}")
        return True

    def _enviar_mensagem(self, acao: Acao) -> None:
        try:
            self._post(acao.destinatario, acao.mensagem)
        except GraphError as exc:
            # Template recusado (formato, conta sem suporte, resposta privada
            # que não aceita botão) — tenta o texto simples antes de desistir.
            if exc.transient or not acao.alternativa:
                raise
            self.log(f"template recusado ({exc}); tentando texto simples")
            self._post(acao.destinatario, acao.alternativa)

    def _post(self, destinatario: dict | None, mensagem: dict | None) -> None:
        self.client.post(
            "me/messages",
            {
                "recipient": json.dumps(destinatario),
                "message": json.dumps(mensagem, ensure_ascii=False),
                "messaging_type": "RESPONSE",
            },
        )

    def _alertar(self, exc: GraphError, acao: Acao) -> None:
        chave = f"{acao.tipo}:{exc.code}"
        agora = self.relogio()
        ultimo = self._alertados.get(chave)
        if ultimo is not None and agora - ultimo < JANELA_ALERTA:
            self.log(f"falha (alerta já enviado na última hora): {exc}")
            return
        self._alertados[chave] = agora
        dica = ""
        if exc.code in (10, 200, 230, 3) or exc.status == 403:
            dica = (
                " — parece permissão: confira instagram_manage_messages / "
                "instagram_manage_comments no app e o acesso a mensagens nas "
                "configurações do Instagram (docs/DM.md)."
            )
        elif exc.code == 551 or "outside of allowed window" in str(exc):
            dica = " — fora da janela de 24h (ou resposta privada a comentário com mais de 7 dias)."
        alert(f"DM automática não enviada: {exc}{dica}", webhook=self.alert_webhook)


def processar(
    evento: Evento, fluxos: Fluxos, estado: Estado, enviador: Enviador
) -> list[Acao]:
    """Deduplica, decide e executa. Devolve as ações tentadas."""
    if not estado.marcar_visto(evento.id):
        return []
    acoes = decidir(evento, fluxos, estado)
    for acao in acoes:
        if not enviador.executar(acao, estado) and acao.tipo == "enviar":
            break  # sem a DM, a resposta pública ("te mandei no direct") seria mentira
    return acoes
