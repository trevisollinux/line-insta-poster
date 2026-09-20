"""Resumo semanal — o contrário do vigia.

O vigia avisa quando algo quebrou. Este resume o que aconteceu quando nada
quebrou, que é a informação que some: os números ficam no CSV, e CSV ninguém
abre de segunda de manhã.

Regra que atravessa o arquivo inteiro: **nenhum número aparece sem o tamanho
da amostra ao lado**. Uma semana tem 10 a 14 stories; mediana de 3 não é
tendência, e escrever como se fosse é a forma mais barata de fazer alguém
tomar decisão errada com cara de dado.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

BRT_OFFSET = -3


@dataclass(frozen=True)
class Publicado:
    item_id: str
    media_id: str
    tipo: str
    quando: datetime
    views: int | None = None
    reach: int | None = None
    visitas_perfil: int | None = None


@dataclass(frozen=True)
class Resumo:
    inicio: datetime
    fim: datetime
    publicados: list[Publicado] = field(default_factory=list)
    fila_restante: int = 0
    conta_hoje: dict[str, str] = field(default_factory=dict)
    conta_antes: dict[str, str] = field(default_factory=dict)


def _numero(bruto) -> int | None:
    texto = str(bruto or "").strip()
    return int(texto) if texto.lstrip("-").isdigit() else None


def semana(entradas, *, agora: datetime | None = None, dias: int = 7) -> list:
    """Publicações dos últimos `dias`, por data local."""
    fuso = timezone(timedelta(hours=BRT_OFFSET))
    momento = (agora or datetime.now(timezone.utc)).astimezone(fuso)
    corte = momento - timedelta(days=dias)
    return [
        e for e in entradas
        if e.published_at and e.published_datetime.astimezone(fuso) >= corte
    ]


def juntar(entradas, metricas: list[dict[str, str]]) -> list[Publicado]:
    """Cola o que foi publicado com o que foi medido.

    A ponte é o `media_id`: o estado sabe QUE tipo de foto era, o CSV sabe
    QUANTO ela rendeu, e nenhum dos dois sabe as duas coisas sozinho.
    """
    por_media = {linha.get("media_id", ""): linha for linha in metricas}
    fuso = timezone(timedelta(hours=BRT_OFFSET))
    saida = []
    for entrada in entradas:
        medida = por_media.get(entrada.media_id, {})
        saida.append(
            Publicado(
                item_id=entrada.item_id,
                media_id=entrada.media_id,
                tipo=(getattr(entrada, "tipo", "") or ""),
                quando=entrada.published_datetime.astimezone(fuso),
                views=_numero(medida.get("views")),
                reach=_numero(medida.get("reach")),
                visitas_perfil=_numero(medida.get("profile_visits")),
            )
        )
    return sorted(saida, key=lambda p: p.quando)


def por_tipo(publicados: list[Publicado]) -> dict[str, dict[str, float]]:
    """Mediana de views por tipo de conteúdo, com o tamanho da amostra.

    Sem o `n` ao lado, a primeira semana mostraria "bastidor: 340" contra
    "produto: 150" e alguém reorganizaria a produção inteira em cima de duas
    fotos.
    """
    grupos: dict[str, list[int]] = {}
    for item in publicados:
        if item.views is None:
            continue
        grupos.setdefault(item.tipo or "(sem tipo)", []).append(item.views)
    return {
        tipo: {"n": len(valores), "mediana": statistics.median(valores)}
        for tipo, valores in sorted(grupos.items())
    }


def linha_da_conta(linhas: list[dict[str, str]], data: str) -> dict[str, str]:
    for linha in linhas:
        if linha.get("data") == data:
            return linha
    return {}


def conta_na_semana(
    linhas: list[dict[str, str]], *, agora: datetime | None = None, dias: int = 7
) -> tuple[dict[str, str], dict[str, str]]:
    """A linha mais recente e a de `dias` atrás, para dar a variação."""
    if not linhas:
        return {}, {}
    ordenadas = sorted(linhas, key=lambda linha: linha.get("data", ""))
    fuso = timezone(timedelta(hours=BRT_OFFSET))
    momento = (agora or datetime.now(timezone.utc)).astimezone(fuso)
    alvo = (momento - timedelta(days=dias)).date().isoformat()
    antes = [linha for linha in ordenadas if linha.get("data", "") <= alvo]
    return ordenadas[-1], (antes[-1] if antes else {})


def titulo(agora: datetime) -> str:
    return f"Resumo da semana — {agora:%d/%m/%Y}"


def _variacao(hoje: str, antes: str) -> str:
    a, b = _numero(hoje), _numero(antes)
    if a is None:
        return "—"
    if b is None:
        return f"{a}"
    delta = a - b
    sinal = "+" if delta > 0 else ""
    return f"{a} ({sinal}{delta} na semana)"


def markdown(resumo: Resumo) -> str:
    linhas = [
        f"## Semana de {resumo.inicio:%d/%m} a {resumo.fim:%d/%m}",
        "",
    ]

    publicados = resumo.publicados
    medidos = [p for p in publicados if p.views is not None]
    linhas.append(f"**{len(publicados)} story(s) publicado(s)**, {len(medidos)} com métrica lida.")
    linhas.append("")

    if medidos:
        views = [p.views for p in medidos]
        linhas += [
            f"- Views por story: mediana **{statistics.median(views):.0f}** "
            f"(de {min(views)} a {max(views)}, n={len(views)})",
        ]
        melhor = max(medidos, key=lambda p: p.views)
        pior = min(medidos, key=lambda p: p.views)
        linhas += [
            f"- Melhor: {melhor.views} views em {melhor.quando:%d/%m %H:%M}"
            + (f" · _{melhor.tipo}_" if melhor.tipo else ""),
            f"- Pior: {pior.views} views em {pior.quando:%d/%m %H:%M}"
            + (f" · _{pior.tipo}_" if pior.tipo else ""),
        ]
        perfil = [p.visitas_perfil for p in medidos if p.visitas_perfil is not None]
        if perfil:
            linhas.append(f"- Visitas ao perfil somadas: **{sum(perfil)}**")
        linhas.append("")

    tipos = por_tipo(publicados)
    if len(tipos) > 1:
        linhas += ["### Por tipo de conteúdo", "", "| Tipo | Stories | Views (mediana) |", "|---|---|---|"]
        for tipo, dados in sorted(tipos.items(), key=lambda x: -x[1]["mediana"]):
            linhas.append(f"| {tipo} | {dados['n']:.0f} | {dados['mediana']:.0f} |")
        linhas += [
            "",
            "Amostra pequena: com menos de 5 stories por tipo, a diferença ainda "
            "cabe no acaso. O número serve para acompanhar, não para decidir.",
            "",
        ]
    elif publicados and not any(p.tipo for p in publicados):
        linhas += [
            "_Nenhum story tinha tipo._ Enquanto as fotos não vierem das "
            "subpastas do Drive, não dá para comparar conteúdo — que é o fator "
            "que mais mexeu no alcance.",
            "",
        ]

    if resumo.conta_hoje:
        hoje, antes = resumo.conta_hoje, resumo.conta_antes
        linhas += ["### A conta", ""]
        rotulos = (
            ("seguidores", "Seguidores"),
            ("profile_views", "Visitas ao perfil"),
            ("website_clicks", "Cliques no link da bio"),
            ("reach", "Alcance no dia"),
        )
        for campo, rotulo in rotulos:
            if hoje.get(campo):
                linhas.append(f"- {rotulo}: **{_variacao(hoje.get(campo, ''), antes.get(campo, ''))}**")
        linhas += ["", f"_Último dia medido: {hoje.get('data', '—')}._", ""]

    linhas += [
        "### A fila",
        "",
        f"Restam **{resumo.fila_restante}** foto(s) — cerca de "
        f"**{resumo.fila_restante / 2:.1f} dia(s)** no ritmo de dois por dia.",
    ]
    return "\n".join(linhas) + "\n"
