"""Subcomandos `dm-*` da linha de comando (registrados em `poster/cli.py`)."""
from __future__ import annotations

import argparse
import json
import sys

from ..config import env_str
from ..graph import GraphClient, GraphError
from . import fluxos as fluxos_mod
from .estado import Estado
from .motor import Evento, decidir

EXIT_OK, EXIT_FAIL, EXIT_NOTHING = 0, 1, 2


def _carregar(caminho: str) -> fluxos_mod.Fluxos | None:
    try:
        return fluxos_mod.carregar(caminho)
    except fluxos_mod.FluxosInvalidos as exc:
        print(f"dm/fluxos.yaml inválido:\n{exc}", file=sys.stderr)
        return None


def cmd_validar(args: argparse.Namespace) -> int:
    fluxos = _carregar(args.fluxos)
    if fluxos is None:
        return EXIT_FAIL
    print(f"ok: {len(fluxos.gatilhos)} gatilhos, {len(fluxos.passos)} passos")
    if fluxos.pendentes:
        # Aviso, não falha: o exemplo versionado tem TROCAR de propósito, e é o
        # `dm-exportar` (o deploy) que se recusa a seguir com ele.
        print("ainda não pode ir ao ar (o deploy recusa):")
        for pendente in fluxos.pendentes:
            print(f"  - {pendente}")
    return EXIT_OK


def cmd_simular(args: argparse.Namespace) -> int:
    fluxos = _carregar(args.fluxos)
    if fluxos is None:
        return EXIT_FAIL
    estado = Estado()
    for rodada in range(1, args.vezes + 1):
        if args.vezes > 1:
            print(f"— {rodada}ª vez")
        botao = args.onde == "botao"
        evento = Evento(
            tipo=args.onde,
            id=f"sim-{rodada}",
            usuario="cliente-simulado",
            texto="" if botao else args.texto,
            comentario_id=f"comentario-{rodada}" if args.onde == "comentario" else "",
            media_id=args.post,
            passo=args.texto if botao else "",
        )
        acoes = decidir(evento, fluxos, estado)
        if not acoes:
            print("(nenhuma resposta — fica para gente)")
        for acao in acoes:
            print(acao.descrever())
            if acao.registrar:
                estado.registrar_entrega(*acao.registrar)
    return EXIT_OK


def cmd_exportar(args: argparse.Namespace) -> int:
    fluxos = _carregar(args.fluxos)
    if fluxos is None:
        return EXIT_FAIL
    if fluxos.pendentes and not args.permitir_pendente:
        print("dm/fluxos.yaml ainda tem texto de exemplo — preencha antes do deploy:")
        for pendente in fluxos.pendentes:
            print(f"  - {pendente}")
        return EXIT_NOTHING
    with open(args.saida, "w", encoding="utf-8") as handle:
        json.dump(fluxos_mod.exportar(fluxos), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(f"exportado: {args.saida}")
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
                "Token abaixo — vai no secret IG_PAGE_ACCESS_TOKEN. Não cole em issue "
                "nem em log.",
                file=sys.stderr,
            )
            print(pagina.get("access_token", ""))
            return EXIT_OK
    print(f"nenhuma Página deste token está ligada ao Instagram {ig_user_id}", file=sys.stderr)
    return EXIT_FAIL


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

    exportar = sub.add_parser("dm-exportar", help="gera o JSON que o Worker lê")
    exportar.add_argument("--fluxos", default=fluxos_mod.FLUXOS_PATH)
    exportar.add_argument("--saida", default="worker/src/fluxos.json")
    exportar.add_argument(
        "--permitir-pendente", action="store_true", help="exporta mesmo com TROCAR (testes)"
    )
    exportar.set_defaults(func=cmd_exportar)

    pagina = sub.add_parser("dm-token-pagina", help="imprime o token da Página para o Worker")
    pagina.set_defaults(func=cmd_token_pagina)
