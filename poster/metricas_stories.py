"""Histórico de desempenho dos stories — o que a API não guarda.

Story sai do ar em 24h e leva a métrica junto: `/stories` só devolve o que está
publicado agora, e depois não existe endpoint que traga de volta. Sem captura
periódica, qualquer pergunta sobre horário só pode ser respondida por print de
tela, que é trabalho manual e não vira série histórica.

Aqui os stories ativos são lidos, as insights de cada um são buscadas e o
resultado vira uma linha por story em `state/stories_metrics.csv`. Rodando a
cada poucas horas, a última leitura de cada story cai perto do fim da vida dele
— que é quando o número para de subir.

A posição do story no dia não é buscada da API: é calculada na hora de gravar,
ordenando por data local. Ela é o dado que mais explicou o alcance até agora
(o 2º story do dia rende menos que o 1º, sempre), e calcular na gravação faz o
arquivo inteiro se corrigir sozinho quando uma captura chega fora de ordem.
"""
from __future__ import annotations

import csv
import os
from datetime import datetime, timedelta, timezone

from .graph import GraphClient, GraphError

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(REPO_ROOT, "state", "stories_metrics.csv")
CURVA_PATH = os.path.join(REPO_ROOT, "state", "stories_curva.csv")

BRT_OFFSET = -3  # America/Sao_Paulo

STORY_FIELDS = "id,media_type,media_product_type,timestamp,permalink"

# Métricas de story na v21+. `impressions`, `taps_forward`, `taps_back` e `exits`
# foram descontinuadas em 2025 e não entram aqui. A lista é uma preferência, não
# um contrato: conta sem alcance mínimo ou versão diferente da API recusa parte
# dela, e aí o código negocia para baixo em vez de perder a captura inteira.
METRICAS = (
    "views",
    "reach",
    "replies",
    "shares",
    "total_interactions",
    "profile_visits",
    "follows",
    "navigation",
)
METRICAS_MINIMAS = ("reach", "replies")

CAMPOS = (
    "media_id",
    "publicado_utc",
    "data_local",
    "hora_local",
    "posicao_dia",
    "media_type",
    *METRICAS,
    "permalink",
    "capturado_em",
)

# A curva é o motivo de coletar de hora em hora em vez de guardar só o total: o
# total diz quantos viram, a curva diz *quando* viram. Se as visualizações de um
# story das 21h chegam quase todas nas duas primeiras horas, o horário importa;
# se pingam ao longo do dia seguinte, não importa quase nada. Essa diferença não
# é recuperável depois — ou se mede enquanto acontece, ou não se mede.
CAMPOS_CURVA = (
    "media_id",
    "data_local",
    "hora_local",
    "posicao_dia",
    "idade_horas",
    "capturado_em",
    "views",
    "reach",
    "profile_visits",
    "navigation",
)


def stories_ativos(client: GraphClient, ig_user_id: str) -> list[dict[str, str]]:
    """Os stories no ar neste momento. Lista vazia é resposta normal."""
    payload = client.get(f"{ig_user_id}/stories", {"fields": STORY_FIELDS})
    return [linha for linha in (payload.get("data") or []) if linha.get("id")]


def insights(
    client: GraphClient, media_id: str, *, metricas: tuple[str, ...] = METRICAS
) -> dict[str, int]:
    """Insights de um story, negociando a lista de métricas quando a API recusa.

    A Graph API rejeita o pedido inteiro por causa de uma métrica só, e o nome
    dela vem na mensagem de erro. Em vez de desistir, tira-se a métrica citada e
    tenta de novo — pior caso, sobra o mínimo que toda conta responde.
    """
    tentativa = list(metricas)
    ultimo_erro: GraphError | None = None
    for _ in range(3):
        if not tentativa:
            break
        try:
            payload = client.get(
                f"{media_id}/insights", {"metric": ",".join(tentativa)}
            )
        except GraphError as exc:
            ultimo_erro = exc
            recusadas = [m for m in tentativa if m in str(exc)]
            if recusadas:
                tentativa = [m for m in tentativa if m not in recusadas]
                continue
            if tentativa != list(METRICAS_MINIMAS):
                tentativa = list(METRICAS_MINIMAS)
                continue
            break
        return _valores(payload)

    if ultimo_erro is not None:
        raise ultimo_erro
    return {}


def _valores(payload: dict) -> dict[str, int]:
    saida: dict[str, int] = {}
    for linha in payload.get("data") or []:
        nome = str(linha.get("name") or "")
        valores = linha.get("values") or []
        if not nome or not valores:
            continue
        bruto = valores[0].get("value")
        if isinstance(bruto, (int, float)):
            saida[nome] = int(bruto)
    return saida


def montar_linha(
    story: dict, medidas: dict[str, int], *, offset: int = BRT_OFFSET, agora: datetime | None = None
) -> dict[str, str]:
    publicado = _parse_timestamp(str(story.get("timestamp") or ""))
    local = publicado + timedelta(hours=offset) if publicado else None
    captura = (agora or datetime.now(timezone.utc)).astimezone(timezone.utc)
    linha = {
        "media_id": str(story.get("id") or ""),
        "publicado_utc": publicado.isoformat(timespec="seconds") if publicado else "",
        "data_local": local.strftime("%Y-%m-%d") if local else "",
        "hora_local": local.strftime("%H:%M") if local else "",
        "posicao_dia": "",  # preenchido em gravar()
        "media_type": str(story.get("media_type") or ""),
        "permalink": str(story.get("permalink") or ""),
        "capturado_em": captura.isoformat(timespec="seconds"),
    }
    for metrica in METRICAS:
        valor = medidas.get(metrica)
        linha[metrica] = "" if valor is None else str(valor)
    return linha


def _parse_timestamp(bruto: str) -> datetime | None:
    if not bruto:
        return None
    texto = bruto.replace("Z", "+0000")
    for formato in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            return datetime.strptime(texto, formato).astimezone(timezone.utc)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(bruto).astimezone(timezone.utc)
    except ValueError:
        return None


def carregar(path: str = CSV_PATH) -> list[dict[str, str]]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return [dict(linha) for linha in csv.DictReader(handle)]


def mesclar(
    existentes: list[dict[str, str]], novas: list[dict[str, str]]
) -> list[dict[str, str]]:
    """Uma linha por story, sempre com a leitura mais completa.

    As métricas de story são contadores que só sobem. Quando uma captura nova
    traz número menor que a anterior, isso é oscilação da API e não o story
    perdendo visualização — por isso fica o maior dos dois, e não o mais recente.
    """
    por_id = {linha.get("media_id", ""): dict(linha) for linha in existentes}
    for nova in novas:
        media_id = nova.get("media_id", "")
        if not media_id:
            continue
        antiga = por_id.get(media_id)
        if antiga is None:
            por_id[media_id] = dict(nova)
            continue
        combinada = dict(antiga)
        combinada.update({k: v for k, v in nova.items() if v not in ("", None)})
        for metrica in METRICAS:
            combinada[metrica] = _maior(antiga.get(metrica), nova.get(metrica))
        por_id[media_id] = combinada
    return list(por_id.values())


def _maior(a: str | None, b: str | None) -> str:
    valores = [int(v) for v in (a, b) if v not in ("", None) and str(v).lstrip("-").isdigit()]
    return str(max(valores)) if valores else ""


def gravar(linhas: list[dict[str, str]], path: str = CSV_PATH) -> list[dict[str, str]]:
    ordenadas = sorted(linhas, key=lambda linha: linha.get("publicado_utc", ""))
    contagem: dict[str, int] = {}
    for linha in ordenadas:
        dia = linha.get("data_local", "")
        contagem[dia] = contagem.get(dia, 0) + 1
        linha["posicao_dia"] = str(contagem[dia])

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(CAMPOS))
        writer.writeheader()
        for linha in ordenadas:
            writer.writerow({campo: linha.get(campo, "") for campo in CAMPOS})
    return ordenadas


def _numero(linha: dict[str, str], campo: str) -> int | None:
    bruto = (linha.get(campo) or "").strip()
    return int(bruto) if bruto.lstrip("-").isdigit() else None


def _mediana(valores: list[int]) -> float:
    ordenados = sorted(valores)
    meio = len(ordenados) // 2
    if len(ordenados) % 2:
        return float(ordenados[meio])
    return (ordenados[meio - 1] + ordenados[meio]) / 2


def resumo(linhas: list[dict[str, str]], *, metrica: str = "views") -> str:
    """Markdown com o corte que interessa: posição no dia e hora de publicação.

    As duas leituras vêm juntas de propósito. Comparar horas sem separar a
    posição confunde as duas coisas — um story das 21h que é o segundo do dia
    parece "hora ruim" quando o que pesou foi ser o segundo.
    """
    uteis = [linha for linha in linhas if _numero(linha, metrica) is not None]
    if not uteis:
        return f"### Stories\n\nSem leituras de `{metrica}` ainda.\n"

    por_posicao: dict[str, list[int]] = {}
    por_hora: dict[int, list[int]] = {}
    primeiros_por_hora: dict[int, list[int]] = {}
    for linha in uteis:
        valor = _numero(linha, metrica)
        posicao = (linha.get("posicao_dia") or "?").strip()
        por_posicao.setdefault(posicao, []).append(valor)
        hora_texto = (linha.get("hora_local") or "")[:2]
        if hora_texto.isdigit():
            hora = int(hora_texto)
            por_hora.setdefault(hora, []).append(valor)
            if posicao == "1":
                primeiros_por_hora.setdefault(hora, []).append(valor)

    partes = [
        f"### Stories — {len(uteis)} medições (`{metrica}`)",
        "",
        "**Por posição no dia**",
        "",
        "| posição | stories | mediana |",
        "|---|---|---|",
    ]
    for posicao in sorted(por_posicao, key=lambda p: (not p.isdigit(), p)):
        valores = por_posicao[posicao]
        partes.append(f"| {posicao}º | {len(valores)} | {_mediana(valores):.0f} |")

    partes += [
        "",
        "**Por hora — só os primeiros do dia**",
        "",
        "Comparar só primeiros é o que separa hora de posição; por isso a coluna",
        "de segundos em diante fica de fora desta tabela.",
        "",
        "| hora | stories | mediana |",
        "|---|---|---|",
    ]
    if primeiros_por_hora:
        for hora in sorted(primeiros_por_hora):
            valores = primeiros_por_hora[hora]
            partes.append(f"| {hora:02d}h | {len(valores)} | {_mediana(valores):.0f} |")
    else:
        partes.append("| — | 0 | sem primeiros do dia registrados |")

    minimo = min(len(v) for v in primeiros_por_hora.values()) if primeiros_por_hora else 0
    if minimo < 5:
        partes += [
            "",
            "> Amostra ainda pequena por hora. Com menos de ~5 medições em cada "
            "horário, diferença aqui não distingue efeito de acaso.",
        ]
    return "\n".join(partes) + "\n"


def montar_ponto(
    story: dict,
    medidas: dict[str, int],
    *,
    offset: int = BRT_OFFSET,
    agora: datetime | None = None,
) -> dict[str, str]:
    """Um ponto da curva: o estado das métricas na idade X do story.

    `idade_horas` é arredondada para inteiro de propósito. O coletor roda no
    minuto 0, mas o runner atrasa alguns minutos e isso deslocaria cada ponto
    para uma idade ligeiramente diferente, impedindo comparar story com story.
    """
    linha = montar_linha(story, medidas, offset=offset, agora=agora)
    publicado = _parse_timestamp(str(story.get("timestamp") or ""))
    captura = (agora or datetime.now(timezone.utc)).astimezone(timezone.utc)
    idade = ""
    if publicado:
        idade = str(round((captura - publicado).total_seconds() / 3600))
    ponto = {campo: linha.get(campo, "") for campo in CAMPOS_CURVA}
    ponto["idade_horas"] = idade
    return ponto


def carregar_curva(path: str = CURVA_PATH) -> list[dict[str, str]]:
    return carregar(path)


def anexar_curva(
    existentes: list[dict[str, str]], pontos: list[dict[str, str]]
) -> list[dict[str, str]]:
    """Acrescenta pontos novos sem duplicar (story, idade).

    Duas capturas podem cair na mesma idade arredondada — um run atrasado
    seguido de um no horário. Guardar as duas inflaria o número de medições sem
    acrescentar informação, então a colisão vira uma linha só com o maior valor.
    """
    por_chave: dict[tuple[str, str], dict[str, str]] = {
        (linha.get("media_id", ""), linha.get("idade_horas", "")): dict(linha)
        for linha in existentes
    }
    for ponto in pontos:
        chave = (ponto.get("media_id", ""), ponto.get("idade_horas", ""))
        if not chave[0]:
            continue
        anterior = por_chave.get(chave)
        if anterior is None:
            por_chave[chave] = dict(ponto)
            continue
        combinado = dict(anterior)
        combinado.update({k: v for k, v in ponto.items() if v not in ("", None)})
        for metrica in ("views", "reach", "profile_visits", "navigation"):
            combinado[metrica] = _maior(anterior.get(metrica), ponto.get(metrica))
        por_chave[chave] = combinado
    return list(por_chave.values())


def gravar_curva(
    pontos: list[dict[str, str]], path: str = CURVA_PATH
) -> list[dict[str, str]]:
    def chave(linha: dict[str, str]) -> tuple:
        idade = linha.get("idade_horas", "")
        return (
            linha.get("data_local", ""),
            linha.get("hora_local", ""),
            linha.get("media_id", ""),
            int(idade) if idade.lstrip("-").isdigit() else 0,
        )

    ordenados = sorted(pontos, key=chave)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(CAMPOS_CURVA))
        writer.writeheader()
        for ponto in ordenados:
            writer.writerow({campo: ponto.get(campo, "") for campo in CAMPOS_CURVA})
    return ordenados


def aplicar_posicao(
    pontos: list[dict[str, str]], linhas: list[dict[str, str]]
) -> list[dict[str, str]]:
    """Copia `posicao_dia` do histórico para a curva.

    A posição só é conhecida depois de ordenar o dia inteiro, e um story pode
    virar "2º do dia" horas depois de ter sido capturado como 1º. Recopiar a
    cada gravação mantém os dois arquivos contando a mesma história.
    """
    posicoes = {
        linha.get("media_id", ""): linha.get("posicao_dia", "") for linha in linhas
    }
    for ponto in pontos:
        posicao = posicoes.get(ponto.get("media_id", ""))
        if posicao:
            ponto["posicao_dia"] = posicao
    return pontos
