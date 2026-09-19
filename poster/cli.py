"""Linha de comando: `python -m poster.cli <comando>`.

Comandos
  validate       valida a fila e mostra o que está elegível (não usa rede)
  publish        publica o próximo item da fila
  token          mostra quantos dias o token ainda tem
  refresh-token  renova o long-lived token e (opcional) grava no secret do repo
  curate         coleta o acervo, ranqueia e escreve queue/candidates.yaml

Códigos de saída: 0 sucesso, 1 falha (com alerta), 2 nada a fazer.
"""
from __future__ import annotations

import argparse
import os
import random
import sys
from datetime import datetime, timedelta, timezone

from . import audiencia, curadoria, drive, inbox as inbox_mod, queue_file, rehost as rehost_mod, state
from .alerts import alert, write_summary
from .config import PublishConfig, env_str
from .graph import GRAPH_VERSION, GraphClient, GraphError
from .publisher import PublishError, publish_item
from .selection import select_next
from .token import refresh_long_lived_token, token_info, update_repo_secret

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_NOTHING = 2


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        items = queue_file.load_queue(args.queue)
    except queue_file.QueueError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_FAIL
    published = state.load_state(args.state)
    formatos = tuple(t for t in (args.media_type or "").upper().split(",") if t)
    selection = select_next(items, published, mode="order", media_types=formatos or None)
    print(f"fila válida: {len(items)} itens, {len(selection.eligible)} elegíveis")
    for item in selection.eligible:
        print(f"  elegível  {item.id} ({item.media_type}, peso {item.weight:g})")
    for pulado in selection.skipped:
        print(f"  pulado    {pulado.item_id}: {pulado.reason}")
    return EXIT_OK


def cmd_publish(args: argparse.Namespace) -> int:
    try:
        config = PublishConfig.from_env(dry_run=args.dry_run)
    except RuntimeError as exc:
        alert(str(exc))
        return EXIT_FAIL

    try:
        items = queue_file.load_queue(args.queue)
    except queue_file.QueueError as exc:
        alert(str(exc), webhook=config.alert_webhook)
        return EXIT_FAIL

    published = state.load_state(args.state)
    seed = env_str("IG_SELECTION_SEED")
    formatos = tuple(t for t in (args.media_type or "").upper().split(",") if t)
    selection = select_next(
        items,
        published,
        mode=config.selection_mode,
        rng=random.Random(seed) if seed else None,
        media_types=formatos or None,
    )

    escopo = f" ({args.media_type.upper()})" if args.media_type else ""
    print(f"fila{escopo}: {len(items)} itens, {len(selection.eligible)} elegíveis")
    for pulado in selection.skipped:
        print(f"  pulado {pulado.item_id}: {pulado.reason}")

    if selection.item is None:
        write_summary(
            "### Instagram — nada a publicar\n\n"
            f"{len(items)} itens na fila, nenhum elegível. Abasteça `queue/posts.yaml`."
        )
        print("nenhum item elegível — nada publicado")
        return EXIT_NOTHING

    item = selection.item
    print(f"escolhido: {item.id} ({item.media_type})")

    if config.dry_run:
        write_summary(
            f"### Instagram — dry run\n\nEscolhido: `{item.id}` ({item.media_type})\n"
        )
        print("dry run — nada foi enviado à Graph API")
        return EXIT_OK

    client = GraphClient(config.access_token, version=config.graph_version)
    log_token_validity(config)

    try:
        outcome = publish_item(
            client,
            config.ig_user_id,
            item,
            poll_interval=config.poll_interval,
            poll_timeout=config.poll_timeout,
            min_quota_left=config.min_quota_left,
        )
    except PublishError as exc:
        alert(str(exc), webhook=config.alert_webhook, context={"item_id": item.id})
        return EXIT_FAIL

    state.append_entry(outcome.to_entry(), args.state)
    quota = (
        f"{outcome.quota_usage}/{outcome.quota_total}"
        if outcome.quota_usage is not None
        else "desconhecido"
    )
    print(f"publicado: {outcome.media_id} ({outcome.permalink or 'sem permalink'})")
    write_summary(
        "### Instagram — publicado\n\n"
        f"- item: `{item.id}` ({item.media_type})\n"
        f"- media id: `{outcome.media_id}`\n"
        f"- permalink: {outcome.permalink or '—'}\n"
        f"- limite 24h: {quota}\n"
    )
    return EXIT_OK


def cmd_token(args: argparse.Namespace) -> int:
    access_token = env_str("IG_ACCESS_TOKEN")
    app_id, app_secret = env_str("META_APP_ID"), env_str("META_APP_SECRET")
    faltando = [
        nome
        for nome, valor in (
            ("IG_ACCESS_TOKEN", access_token),
            ("META_APP_ID", app_id),
            ("META_APP_SECRET", app_secret),
        )
        if not valor
    ]
    if faltando:
        print(f"variáveis ausentes: {', '.join(faltando)}", file=sys.stderr)
        return EXIT_FAIL
    try:
        info = token_info(access_token, app_id, app_secret)
    except GraphError as exc:
        alert(f"validade do token não verificada: {exc}", webhook=env_str("IG_ALERT_WEBHOOK"))
        return EXIT_FAIL
    print(info.describe())
    print(f"escopos: {', '.join(info.scopes) or '—'}")
    write_summary(f"### Token do Instagram\n\n{info.describe()}\n")
    dias = info.days_left()
    if not info.is_valid or (dias is not None and dias <= args.warn_days):
        alert(f"token do Instagram: {info.describe()}", webhook=env_str("IG_ALERT_WEBHOOK"))
        return EXIT_FAIL
    return EXIT_OK


def cmd_refresh_token(args: argparse.Namespace) -> int:
    webhook = env_str("IG_ALERT_WEBHOOK")
    access_token = env_str("IG_ACCESS_TOKEN")
    app_id, app_secret = env_str("META_APP_ID"), env_str("META_APP_SECRET")
    if not (access_token and app_id and app_secret):
        alert(
            "renovação de token exige IG_ACCESS_TOKEN, META_APP_ID e META_APP_SECRET",
            webhook=webhook,
        )
        return EXIT_FAIL

    try:
        novo, expira = refresh_long_lived_token(access_token, app_id, app_secret)
    except GraphError as exc:
        alert(f"renovação do token falhou: {exc}", webhook=webhook)
        return EXIT_FAIL

    validade = expira.date().isoformat() if expira else "sem data informada"
    print(f"token renovado — válido até {validade}")

    if args.secret_repo:
        try:
            update_repo_secret(
                args.secret_repo, args.secret_name, novo, env_str("GH_SECRETS_TOKEN")
            )
        except (RuntimeError, OSError) as exc:
            alert(
                f"token renovado mas o secret {args.secret_name} NÃO foi atualizado: {exc}",
                webhook=webhook,
            )
            return EXIT_FAIL
        print(f"secret {args.secret_name} atualizado em {args.secret_repo}")

    write_summary(f"### Token renovado\n\nVálido até **{validade}**.\n")
    return EXIT_OK


def cmd_audience(args: argparse.Namespace) -> int:
    """Mostra em que horas os seguidores estão online."""
    access_token, ig_user_id = env_str("IG_ACCESS_TOKEN"), env_str("IG_USER_ID")
    if not (access_token and ig_user_id):
        print("IG_ACCESS_TOKEN e IG_USER_ID são obrigatórios", file=sys.stderr)
        return EXIT_FAIL

    client = GraphClient(access_token, version=env_str("IG_GRAPH_VERSION", GRAPH_VERSION))
    try:
        serie = audiencia.online_followers(client, ig_user_id)
    except GraphError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_FAIL

    if not serie:
        print("a API não devolveu dados de seguidores online")
        return EXIT_NOTHING

    por_hora = audiencia.por_hora_local(serie, offset=args.utc_offset)
    pico = max(por_hora.values()) or 1
    linhas = ["| hora | seguidores online (mediana) |", "|---|---|"]
    print(f"{len(serie)} dias de dados | fuso UTC{args.utc_offset:+d}\n")
    for hora, valor in por_hora.items():
        barra = "█" * int(valor / pico * 30)
        print(f"{hora:02d}h | {valor:8.0f} {barra}")
        linhas.append(f"| {hora:02d}h | {valor:.0f} |")

    melhores = audiencia.melhores_horas(por_hora)
    resumo = ", ".join(f"{h:02d}h ({v:.0f})" for h, v in melhores)
    print(f"\nmaior audiência: {resumo}")
    write_summary(
        "### Seguidores online por hora\n\n"
        + "\n".join(linhas)
        + f"\n\n**Maior audiência:** {resumo}\n\n"
        "Isto mede presença, não interesse: diz onde há gente, não o que rende.\n"
    )
    return EXIT_OK


def cmd_inbox(args: argparse.Namespace) -> int:
    """Importa o que a curadoria humana largou na pasta do Drive."""
    webhook = env_str("IG_ALERT_WEBHOOK")
    credencial = env_str("GDRIVE_SERVICE_ACCOUNT")
    pasta = args.folder_id or env_str("GDRIVE_FOLDER_ID")
    if not (credencial and pasta):
        print(
            "GDRIVE_SERVICE_ACCOUNT e GDRIVE_FOLDER_ID são obrigatórios",
            file=sys.stderr,
        )
        return EXIT_FAIL

    try:
        token = drive.access_token(credencial)
        # Confirma o acesso antes de listar: pasta não compartilhada devolve
        # lista vazia, indistinguível de pasta sem fotos.
        nome_pasta = drive.folder_name(token, pasta)
        print(f"pasta: '{nome_pasta}'")
        arquivos = drive.list_files(token, pasta)
    except drive.DriveError as exc:
        alert(str(exc), webhook=webhook)
        return EXIT_FAIL

    ja_importados = inbox_mod.load_imported(args.state_file)
    novos, repetidos, recusados = inbox_mod.triagem(arquivos, ja_importados)
    print(
        f"pasta: {len(arquivos)} arquivos — {len(novos)} novos, "
        f"{len(repetidos)} já importados, {len(recusados)} recusados pelo formato"
    )
    for arquivo in recusados:
        print(f"  recusado {arquivo.name}: {arquivo.motivo_recusa}")

    importados: list[tuple[drive.DriveFile, str]] = []
    falhas: list[tuple[str, str]] = []
    rascunhos: list[dict] = []
    destino_midia = os.path.join(args.media_dir, inbox_mod.MEDIA_SUBDIR)

    for arquivo in novos:
        nome = inbox_mod.media_filename(arquivo)
        try:
            drive.download(token, arquivo, os.path.join(destino_midia, nome))
        except drive.DriveError as exc:
            falhas.append((arquivo.name, str(exc)))
            continue
        url = inbox_mod.media_public_url(args.media_repo, args.branch, nome)
        importados.append((arquivo, url))
        rascunhos.append(inbox_mod.draft(arquivo, url))
        ja_importados[arquivo.id] = inbox_mod.Imported(
            drive_id=arquivo.id,
            name=arquivo.name,
            path=f"{inbox_mod.MEDIA_SUBDIR}/{nome}",
            url=url,
            imported_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        print(f"  importado {arquivo.name} → {nome}")

    if rascunhos:
        # Rascunhos anteriores ainda não aprovados continuam valendo.
        anteriores = inbox_mod.load_drafts(args.drafts)
        inbox_mod.write_drafts(anteriores + rascunhos, args.drafts)
        inbox_mod.save_imported(ja_importados, args.state_file)

    if args.report:
        with open(args.report, "w", encoding="utf-8") as handle:
            handle.write(
                inbox_mod.report_markdown(importados, recusados, repetidos, falhas)
            )

    write_summary(
        "### Caixa de entrada do Drive\n\n"
        f"- arquivos na pasta: {len(arquivos)}\n"
        f"- importados agora: {len(importados)}\n"
        f"- recusados pelo formato: {len(recusados)}\n"
        f"- falharam no download: {len(falhas)}\n"
    )
    if falhas:
        alert(
            f"{len(falhas)} mídia(s) da pasta do Drive não baixaram",
            webhook=webhook,
            context={"falhas": [nome for nome, _ in falhas]},
        )
        return EXIT_FAIL
    return EXIT_OK if importados else EXIT_NOTHING


def cmd_rehost(args: argparse.Namespace) -> int:
    """Traz a mídia de um post para um endereço que a Graph API aceite ingerir."""
    access_token = env_str("IG_ACCESS_TOKEN")
    if not access_token:
        print("IG_ACCESS_TOKEN é obrigatório", file=sys.stderr)
        return EXIT_FAIL

    client = GraphClient(access_token, version=env_str("IG_GRAPH_VERSION", GRAPH_VERSION))
    try:
        caminho, url, tamanho = rehost_mod.rehost(
            client,
            args.media_id,
            nome=args.name,
            diretorio=args.dir,
            repo=args.repo or env_str("GITHUB_REPOSITORY"),
            branch=args.branch,
        )
    except rehost_mod.RehostError as exc:
        alert(str(exc), webhook=env_str("IG_ALERT_WEBHOOK"))
        return EXIT_FAIL

    print(f"mídia salva em {caminho} ({tamanho // 1024} KB)")
    if url:
        print(f"url pública: {url}")
    write_summary(
        "### Mídia rehospedada\n\n"
        f"- arquivo: `{caminho}` ({tamanho // 1024} KB)\n"
        f"- url: {url or '—'}\n\n"
        "Use essa url no item da fila. Lembre: o arquivo fica no histórico do "
        "repositório mesmo depois de apagado.\n"
    )
    return EXIT_OK


def cmd_curate(args: argparse.Namespace) -> int:
    access_token, ig_user_id = env_str("IG_ACCESS_TOKEN"), env_str("IG_USER_ID")
    if not (access_token and ig_user_id):
        print("IG_ACCESS_TOKEN e IG_USER_ID são obrigatórios", file=sys.stderr)
        return EXIT_FAIL

    client = GraphClient(access_token, version=env_str("IG_GRAPH_VERSION", GRAPH_VERSION))
    acervo, cursor = curadoria.load_catalog(args.catalog)
    print(f"catálogo local: {len(acervo)} posts (cursor: {cursor or 'início'})")

    since = None
    if args.since_days > 0:
        since = datetime.now(timezone.utc) - timedelta(days=args.since_days)
        cursor = None  # recorte por data sempre recomeça do post mais recente
        print(f"coletando só o que é posterior a {since.date().isoformat()}")

    try:
        novos, proximo = curadoria.collect_media(
            client,
            ig_user_id,
            max_pages=args.max_pages,
            cursor=cursor,
            since=since,
        )
    except GraphError as exc:
        alert(f"coleta do acervo falhou: {exc}", webhook=env_str("IG_ALERT_WEBHOOK"))
        return EXIT_FAIL
    print(f"coletados {len(novos)} posts nesta execução")

    if args.insights:
        for post in novos:
            if post.has_insights_support:
                post.insights = curadoria.fetch_insights(client, post)

    acervo = curadoria.merge_catalog(acervo, novos)
    curadoria.save_catalog(acervo, proximo, args.catalog)

    ranking = curadoria.score_catalog(acervo, comment_weight=args.comment_weight)

    # Campanha de urgência sai dos candidatos, mas fica na mediana da época:
    # ela fez parte daquele mês, e removê-la da base inflaria o resto.
    if args.no_exclusions:
        reciclaveis, excluidos = ranking, []
    else:
        termos = curadoria.load_exclusions(args.exclusions)
        reciclaveis, excluidos = curadoria.split_recyclable(
            ranking, curadoria.compile_exclusions(termos)
        )

    documento = curadoria.candidates_document(reciclaveis, top_n=args.top)
    falhas: list[tuple[str, str]] = []
    if args.rehost:
        documento, falhas = rehost_mod.rehost_candidates(
            client,
            documento,
            repo=args.repo or env_str("GITHUB_REPOSITORY"),
            branch=args.branch,
        )
        for media_id, motivo in falhas:
            print(f"  mídia {media_id} não rehospedada: {motivo}")

    caminho = curadoria.write_candidates_document(documento, path=args.candidates)
    if args.report:
        with open(args.report, "w", encoding="utf-8") as handle:
            handle.write(
                curadoria.candidates_markdown(
                    documento, titulo=f"Top {len(documento)} do acervo"
                )
            )
        print(f"relatório escrito em {args.report}")
    print(f"{len(acervo)} posts no catálogo; top {args.top} escrito em {caminho}")
    if excluidos:
        print(f"{len(excluidos)} posts fora por serem campanha com data:")
        for item, termo in excluidos[:5]:
            print(f"  {item.post.timestamp.date()} score {item.score:.2f} — '{termo}'")

    restante = "backfill continua na próxima execução" if proximo else "backfill completo"
    write_summary(
        "### Curadoria\n\n"
        f"- posts no catálogo: {len(acervo)}\n"
        f"- coletados agora: {len(novos)}\n"
        f"- candidatos: `{caminho}` (top {args.top} de {len(reciclaveis)} recicláveis)\n"
        f"- fora por campanha com data: {len(excluidos)}\n"
        f"- {restante}\n"
    )
    return EXIT_OK


def log_token_validity(config: PublishConfig) -> None:
    """Dias restantes do token a cada publicação — expiração silenciosa mata tudo."""
    app_id, app_secret = env_str("META_APP_ID"), env_str("META_APP_SECRET")
    if not (app_id and app_secret):
        print("META_APP_ID/META_APP_SECRET ausentes — validade do token não checada")
        return
    try:
        info = token_info(config.access_token, app_id, app_secret)
    except (GraphError, OSError) as exc:
        print(f"validade do token não verificada: {exc}")
        return
    print(info.describe())
    dias = info.days_left()
    if not info.is_valid or (dias is not None and dias <= 7):
        alert(
            f"token do Instagram: {info.describe()}",
            webhook=config.alert_webhook,
            context={"days_left": dias},
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="poster", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def com_arquivos(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
        p.add_argument("--queue", default=queue_file.QUEUE_PATH, help="caminho da fila")
        p.add_argument("--state", default=state.STATE_PATH, help="caminho do estado")
        return p

    validate = com_arquivos(sub.add_parser("validate", help="valida a fila"))
    validate.add_argument("--media-type", default="", help="filtra por formato")
    validate.set_defaults(func=cmd_validate)

    publish = com_arquivos(sub.add_parser("publish", help="publica o próximo item"))
    publish.add_argument(
        "--dry-run", action="store_true", help="escolhe o item sem chamar a API"
    )
    publish.add_argument(
        "--media-type",
        default="",
        help="publica só este formato (REELS, STORIES, CAROUSEL, IMAGE)",
    )
    publish.set_defaults(func=cmd_publish)

    token = sub.add_parser("token", help="mostra a validade do token")
    token.add_argument("--warn-days", type=int, default=7)
    token.set_defaults(func=cmd_token)

    refresh = sub.add_parser("refresh-token", help="renova o long-lived token")
    refresh.add_argument("--secret-repo", default="", help="owner/repo do secret")
    refresh.add_argument("--secret-name", default="IG_ACCESS_TOKEN")
    refresh.set_defaults(func=cmd_refresh_token)

    audience = sub.add_parser("audience", help="horas com mais seguidores online")
    audience.add_argument("--utc-offset", type=int, default=audiencia.BRT_OFFSET)
    audience.set_defaults(func=cmd_audience)

    inbox = sub.add_parser("inbox", help="importa fotos novas da pasta do Drive")
    inbox.add_argument("--folder-id", default="", help="pasta do Drive (ou GDRIVE_FOLDER_ID)")
    inbox.add_argument("--media-dir", required=True, help="raiz do repositório de mídia")
    inbox.add_argument("--media-repo", required=True, help="owner/repo da mídia")
    inbox.add_argument("--branch", default="main")
    inbox.add_argument("--drafts", default=inbox_mod.DRAFTS_PATH)
    inbox.add_argument("--state-file", default=inbox_mod.IMPORTED_PATH)
    inbox.add_argument("--report", default="", help="relatório markdown neste caminho")
    inbox.set_defaults(func=cmd_inbox)

    rehost = sub.add_parser("rehost", help="baixa a mídia de um post para o repositório")
    rehost.add_argument("--media-id", required=True, help="id da mídia no Instagram")
    rehost.add_argument("--name", default="", help="nome do arquivo (sem extensão)")
    rehost.add_argument("--dir", default=rehost_mod.MEDIA_DIR)
    rehost.add_argument("--repo", default="", help="owner/repo para montar a url pública")
    rehost.add_argument("--branch", default="main")
    rehost.set_defaults(func=cmd_rehost)

    curate = sub.add_parser("curate", help="ranqueia o acervo e gera candidatos")
    curate.add_argument("--max-pages", type=int, default=10, help="lotes por execução")
    curate.add_argument("--top", type=int, default=20, help="candidatos no arquivo")
    curate.add_argument(
        "--since-days",
        type=int,
        default=0,
        help="coletar só os últimos N dias (0 = acervo inteiro, com cursor)",
    )
    curate.add_argument("--comment-weight", type=float, default=curadoria.COMMENT_WEIGHT)
    curate.add_argument("--insights", action="store_true", help="busca insights (pós-jul/2024)")
    curate.add_argument("--catalog", default=curadoria.CATALOG_PATH)
    curate.add_argument(
        "--exclusions",
        default=curadoria.EXCLUSIONS_PATH,
        help="lista de termos que tiram o post dos candidatos",
    )
    curate.add_argument(
        "--no-exclusions",
        action="store_true",
        help="ranqueia tudo, inclusive campanha com data",
    )
    curate.add_argument("--candidates", default=curadoria.CANDIDATES_PATH)
    curate.add_argument(
        "--rehost",
        action="store_true",
        help="baixa a mídia dos candidatos e preenche url com o endereço público",
    )
    curate.add_argument("--repo", default="", help="owner/repo para a url pública")
    curate.add_argument(
        "--report", default="", help="escreve um relatório markdown neste caminho"
    )
    curate.add_argument("--branch", default="main")
    curate.set_defaults(func=cmd_curate)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
