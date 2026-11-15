"""Servidor HTTP do webhook — stdlib, sem framework.

Rotas:
    GET  /webhook   verificação da Meta (hub.challenge) ao cadastrar a URL
    POST /webhook   eventos; assinatura conferida com o App Secret
    GET  /saude     para o monitor do provedor de hospedagem

O POST responde 200 **antes** de processar: a Meta espera resposta rápida e
reentrega o que demorar. O trabalho vai para uma fila com um único trabalhador,
o que mantém a ordem das mensagens de cada conversa sem precisar de trava.

Env:
    IG_USER_ID              id da conta Instagram (ignora eventos da própria loja)
    IG_PAGE_ACCESS_TOKEN    token da Página (`python -m poster.cli dm-token-pagina`)
    META_APP_SECRET         confere a assinatura X-Hub-Signature-256
    DM_VERIFY_TOKEN         frase combinada com a Meta na hora de cadastrar o webhook
    DM_DB                   caminho do SQLite (padrão state/dm.sqlite3)
    DM_FLUXOS               caminho dos fluxos (padrão dm/fluxos.yaml)
    DM_DRY_RUN              'true' só registra no log o que mandaria
    IG_ALERT_WEBHOOK        alerta de falha de envio
    PORT                    porta (padrão 8080)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import queue
import sys
import threading
import urllib.parse
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .. import REPO_ROOT
from ..config import env_bool, env_int, env_str
from ..graph import GRAPH_VERSION, GraphClient
from . import fluxos as fluxos_mod
from .envio import Enviador, processar
from .estado import Estado
from .eventos import extrair

MAX_CORPO = 1_000_000


def assinatura_valida(corpo: bytes, cabecalho: str, segredo: str) -> bool:
    if not segredo or not cabecalho.startswith("sha256="):
        return False
    esperado = hmac.new(segredo.encode("utf-8"), corpo, hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, cabecalho[len("sha256="):])


@dataclass
class DMConfig:
    ig_user_id: str
    page_token: str
    app_secret: str
    verify_token: str
    db: str
    fluxos: str
    dry_run: bool
    alert_webhook: str
    port: int
    graph_version: str = GRAPH_VERSION

    @classmethod
    def from_env(cls) -> "DMConfig":
        cfg = cls(
            ig_user_id=env_str("IG_USER_ID"),
            page_token=env_str("IG_PAGE_ACCESS_TOKEN"),
            app_secret=env_str("META_APP_SECRET"),
            verify_token=env_str("DM_VERIFY_TOKEN"),
            db=env_str("DM_DB") or os.path.join(REPO_ROOT, "state", "dm.sqlite3"),
            fluxos=env_str("DM_FLUXOS") or fluxos_mod.FLUXOS_PATH,
            dry_run=env_bool("DM_DRY_RUN"),
            alert_webhook=env_str("IG_ALERT_WEBHOOK"),
            port=env_int("PORT", 8080),
            graph_version=env_str("IG_GRAPH_VERSION", GRAPH_VERSION),
        )
        obrigatorias = {
            "IG_USER_ID": cfg.ig_user_id,
            "META_APP_SECRET": cfg.app_secret,
            "DM_VERIFY_TOKEN": cfg.verify_token,
        }
        if not cfg.dry_run:
            obrigatorias["IG_PAGE_ACCESS_TOKEN"] = cfg.page_token
        faltando = [nome for nome, valor in obrigatorias.items() if not valor]
        if faltando:
            raise RuntimeError(f"variáveis obrigatórias ausentes: {', '.join(faltando)}")
        return cfg


class Aplicacao:
    """O que o handler HTTP precisa, separado do socket para dar para testar."""

    def __init__(self, cfg: DMConfig, fluxos, estado: Estado, enviador: Enviador) -> None:
        self.cfg = cfg
        self.fluxos = fluxos
        self.estado = estado
        self.enviador = enviador
        self.fila: "queue.Queue[dict]" = queue.Queue()

    def verificar(self, consulta: dict[str, list[str]]) -> tuple[int, str]:
        modo = (consulta.get("hub.mode") or [""])[0]
        token = (consulta.get("hub.verify_token") or [""])[0]
        desafio = (consulta.get("hub.challenge") or [""])[0]
        if modo == "subscribe" and hmac.compare_digest(token, self.cfg.verify_token):
            return 200, desafio
        return 403, "verify_token não confere"

    def receber(self, corpo: bytes, assinatura: str) -> int:
        if not assinatura_valida(corpo, assinatura, self.cfg.app_secret):
            return 401
        try:
            dados = json.loads(corpo.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return 400
        self.fila.put(dados)
        return 200

    def tratar(self, dados: dict) -> None:
        for evento in extrair(dados, conta_id=self.cfg.ig_user_id):
            try:
                processar(evento, self.fluxos, self.estado, self.enviador)
            except Exception as exc:  # um evento ruim não derruba o trabalhador
                print(f"erro tratando {evento}: {exc!r}", file=sys.stderr, flush=True)

    def trabalhar(self) -> None:
        while True:
            dados = self.fila.get()
            try:
                self.tratar(dados)
            finally:
                self.fila.task_done()


def criar_handler(app: Aplicacao):
    class Handler(BaseHTTPRequestHandler):
        server_version = "line-dm/1"

        def do_GET(self) -> None:  # noqa: N802 - nome exigido pelo http.server
            url = urllib.parse.urlsplit(self.path)
            if url.path == "/saude":
                self._responder(200, "ok")
            elif url.path == "/webhook":
                self._responder(*app.verificar(urllib.parse.parse_qs(url.query)))
            else:
                self._responder(404, "")

        def do_POST(self) -> None:  # noqa: N802
            if urllib.parse.urlsplit(self.path).path != "/webhook":
                self._responder(404, "")
                return
            tamanho = int(self.headers.get("Content-Length") or 0)
            if tamanho <= 0 or tamanho > MAX_CORPO:
                self._responder(413 if tamanho else 400, "")
                return
            corpo = self.rfile.read(tamanho)
            status = app.receber(corpo, self.headers.get("X-Hub-Signature-256", ""))
            self._responder(status, "")

        def _responder(self, status: int, texto: str) -> None:
            dados = texto.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(dados)))
            self.end_headers()
            self.wfile.write(dados)

        def log_message(self, formato: str, *args) -> None:
            # A query do GET /webhook carrega o verify_token: não vai para log.
            linha = formato % args
            if "hub.verify_token" in linha:
                linha = linha.split("?", 1)[0] + "?…"
            print(linha, file=sys.stderr, flush=True)

    return Handler


def montar(cfg: DMConfig) -> Aplicacao:
    fluxos = fluxos_mod.carregar(cfg.fluxos)
    if fluxos.pendentes and not cfg.dry_run:
        raise RuntimeError(
            "dm/fluxos.yaml ainda tem texto de exemplo — preencha antes de ligar:\n"
            + "\n".join(f"- {p}" for p in fluxos.pendentes)
        )
    estado = Estado(cfg.db)
    estado.limpar_vistos()
    client = (
        GraphClient(cfg.page_token, version=cfg.graph_version) if cfg.page_token else None
    )
    enviador = Enviador(client, dry_run=cfg.dry_run, alert_webhook=cfg.alert_webhook)
    return Aplicacao(cfg, fluxos, estado, enviador)


def servir(cfg: DMConfig) -> None:
    app = montar(cfg)
    threading.Thread(target=app.trabalhar, daemon=True, name="dm-trabalhador").start()
    servidor = ThreadingHTTPServer(("0.0.0.0", cfg.port), criar_handler(app))
    modo = " (dry-run: nada é enviado)" if cfg.dry_run else ""
    print(
        f"DM: {len(app.fluxos.gatilhos)} gatilhos, {len(app.fluxos.passos)} passos, "
        f"porta {cfg.port}{modo}",
        file=sys.stderr,
        flush=True,
    )
    servidor.serve_forever()
