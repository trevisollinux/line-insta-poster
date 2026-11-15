"""Subcomandos `dm-*` da linha de comando (registrados em `poster/cli.py`)."""
from __future__ import annotations

import argparse
import sys

from ..config import env_str
from ..graph import GraphClient, GraphError
from . import fluxos as fluxos_mod
from .envio import Enviador, processar
from .estado import Estado
from .eventos import Evento

EXIT_OK, EXIT_FAIL = 0, 1


def cmd_validar(args: argparse.Namespace) -> int:
    try:
        fluxos = fluxos_mod.carregar(args.fluxos)
    except fluxos_mod.FluxosInvalidos as exc:
        print(f"dm/fluxos.yaml inválido:\n{exc}", file=sys.stderr)
        return EXIT_FAIL
    print(f"ok: {len(fluxos.gatilhos)} gatilhos, {len(fluxos.passos)} passos")
    if fluxos.pendentes:
        # Aviso, não falha: o exemplo versionado tem TROCAR de propósito, e o
        # servidor é quem se recusa a ligar com ele.
        print("ainda não pode ir ao ar (o servidor recusa):")
        for pendente in fluxos.pendentes:
            print(f"  - {pendente}")
    return EXIT_OK


def cmd_simular(args: argparse.Namespace) -> int:
    try:
        fluxos = fluxos_mod.carregar(args.fluxos)
    except fluxos_mod.FluxosInvalidos as exc:
        print(f"dm/fluxos.yaml inválido:\n{exc}", file=sys.stderr)
        return EXIT_FAIL
    estado = Estado()
    enviador = Enviador(None, dry_run=True, log=print)
    usuario = "cliente-simulado"
    for rodada in range(1, args.vezes + 1):
        if args.vezes > 1:
            print(f"— {rodada}ª vez")
        evento = Evento(
            tipo=args.onde,
            id=f"sim-{rodada}",
            usuario=usuario,
            texto="" if args.onde == "botao" else args.texto,
            comentario_id=f"comentario-{rodada}" if args.onde == "comentario" else "",
            media_id=args.post,
            passo=args.texto if args.onde == "botao" else "",
        )
        if not processar(evento, fluxos, estado, enviador):
            print("(nenhuma resposta — fica para gente)")
    return EXIT_OK


def cmd_token_pagina(args: argparse.Namespace) -> int:
    """Troca o token de usuário pelo da Página ligada à conta do Instagram."""
    token, ig_user_id = env_str("IG_ACCESS_TOKEN"), env_str("IG_USER_ID")
    if not token or not ig_user_id:
        print("defina IG_ACCESS_TOKEN e IG_USER_ID", file=sys.stderr)
        return EXIT_FAIL
    try:
        resposta = GraphClient(token).get(
            "me/accounts", {"fields": "id,name,access_token,instagram_business_account"}
        )
    except GraphError as exc:
        print(f"falha ao listar as Páginas: {exc}", file=sys.stderr)
        return EXIT_FAIL
    for pagina in resposta.get("data") or []:
        if (pagina.get("instagram_business_account") or {}).get("id") == ig_user_id:
            print(f"Página: {pagina.get('name')} ({pagina.get('id')})", file=sys.stderr)
            print(
                "Token abaixo — vai no IG_PAGE_ACCESS_TOKEN do servidor. Não cole em "
                "issue nem em log.",
                file=sys.stderr,
            )
            print(pagina.get("access_token", ""))
            return EXIT_OK
    print(f"nenhuma Página deste token está ligada ao Instagram {ig_user_id}", file=sys.stderr)
    return EXIT_FAIL


def cmd_servir(args: argparse.Namespace) -> int:
    from .servidor import DMConfig, servir

    try:
        cfg = DMConfig.from_env()
        if args.fluxos:
            cfg.fluxos = args.fluxos
        servir(cfg)
    except (RuntimeError, fluxos_mod.FluxosInvalidos) as exc:
        print(f"servidor de DM não subiu:\n{exc}", file=sys.stderr)
        return EXIT_FAIL
    return EXIT_OK


def registrar(sub) -> None:
    validar = sub.add_parser("dm-validar", help="valida dm/fluxos.yaml (sem rede)")
    validar.add_argument("--fluxos", default=fluxos_mod.FLUXOS_PATH)
    validar.set_defaults(func=cmd_validar)

    simular = sub.add_parser("dm-simular", help="mostra o que o bot responderia (sem rede)")
    simular.add_argument("onde", choices=("comentario", "story", "dm", "botao"))
    simular.add_argument("texto", help="o que a pessoa escreveu; em `botao`, o id do passo")
    simular.add_argument("--post", default="", help="id da mídia comentada")
    simular.add_argument("--vezes", type=int, default=1, help="repete (testa `uma_vez`)")
    simular.add_argument("--fluxos", default=fluxos_mod.FLUXOS_PATH)
    simular.set_defaults(func=cmd_simular)

    pagina = sub.add_parser("dm-token-pagina", help="imprime o token da Página para o servidor")
    pagina.set_defaults(func=cmd_token_pagina)

    servir = sub.add_parser("dm-servir", help="sobe o servidor do webhook de DM")
    servir.add_argument("--fluxos", default="", help="padrão: DM_FLUXOS ou dm/fluxos.yaml")
    servir.set_defaults(func=cmd_servir)
