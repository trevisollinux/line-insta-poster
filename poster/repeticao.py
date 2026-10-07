"""Repetição de stories quando a fila de fotos novas acaba.

Story some em 24h, e a fila do Drive acaba antes de alguém subir foto nova —
em 02/10 ela esvaziou e o perfil ficou sem story automático. Repetir o que já
saiu é melhor que silêncio, desde que:

1. **Foto nova sempre ganha.** A repetição só é consultada quando a seleção
   normal não achou nada. Ela não compete com o Drive; tapa o buraco.
2. **Há um intervalo mínimo** desde a última vez que o item saiu (14 dias no
   workflow), para o seguidor não reconhecer a foto da semana passada.
3. **Repete primeiro o que levou gente ao perfil.** Visualização engana — um
   story com 174 views levou 9 pessoas ao perfil, outro com 260 levou 5 (ver
   docs/CONTEXTO.md, seção 6). Visita ao perfil é o que vira venda, então ela
   ordena; views só desempata.

A nota de um item é a MÉDIA das suas publicações medidas, não a melhor. Assim
um story que rendeu bem na estreia e mal na repetição desce na fila sozinho, em
vez de ficar preso no topo pelo resultado antigo.

O que isto NÃO corrige: a nota carrega o contexto do dia em que o story saiu
(posição no dia, horário, anúncio rodando junto). É um critério melhor que
sorteio, não uma medida limpa do conteúdo. Item sem nenhuma medição vai para o
fim — o coletor perde leituras (docs/CONTEXTO.md, seção 3), e ausência de dado
não é nota baixa, mas também não é motivo para passar na frente de quem provou
alguma coisa.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .queue_file import QueueItem
from .selection import Selection, Skipped
from .state import PublishedEntry, last_published_at


@dataclass(frozen=True)
class Nota:
    """Desempenho médio das publicações medidas de um item."""

    visitas: float
    views: float
    medicoes: int


def _inteiro(bruto: str | None) -> int | None:
    texto = (bruto or "").strip()
    return int(texto) if texto.isdigit() else None


def notas_por_item(
    published: list[PublishedEntry], metricas: list[dict[str, str]]
) -> dict[str, Nota]:
    """Liga o que a API mediu (media_id) ao item da fila (item_id).

    Linha sem views é captura que não chegou a ler nada (o story expirou antes
    do coletor passar) — conta como não medida, não como zero.
    """
    por_media = {linha.get("media_id", ""): linha for linha in metricas}
    acumulado: dict[str, list[tuple[int, int]]] = {}
    for entrada in published:
        linha = por_media.get(entrada.media_id)
        if linha is None:
            continue
        views = _inteiro(linha.get("views"))
        if views is None:
            continue
        visitas = _inteiro(linha.get("profile_visits")) or 0
        acumulado.setdefault(entrada.item_id, []).append((visitas, views))

    notas: dict[str, Nota] = {}
    for item_id, leituras in acumulado.items():
        n = len(leituras)
        notas[item_id] = Nota(
            visitas=sum(v for v, _ in leituras) / n,
            views=sum(w for _, w in leituras) / n,
            medicoes=n,
        )
    return notas


def selecionar(
    items: list[QueueItem],
    published: list[PublishedEntry],
    metricas: list[dict[str, str]],
    *,
    apos_dias: int,
    now: datetime | None = None,
    media_types: tuple[str, ...] | None = None,
    bloqueados: dict[str, str] | None = None,
) -> Selection:
    """Escolhe o próximo story a repetir, ou nenhum.

    Só considera item que já saiu ao menos uma vez — o que nunca saiu é
    trabalho da seleção normal, e se ela não o escolheu foi por um motivo
    (formato, falha, quarentena) que vale aqui também.
    """
    if apos_dias <= 0:
        raise ValueError("apos_dias precisa ser positivo")
    now = now or datetime.now(timezone.utc)
    permitidos = {t.upper() for t in media_types} if media_types else None
    travados = bloqueados or {}
    notas = notas_por_item(published, metricas)

    candidatos: list[tuple[QueueItem, datetime]] = []
    pulados: list[Skipped] = []
    for item in items:
        if item.id in travados:
            pulados.append(Skipped(item.id, travados[item.id]))
            continue
        if permitidos and item.media_type not in permitidos:
            continue
        ultima = last_published_at(published, item.id) or item.last_published
        if ultima is None:
            continue
        liberado = ultima + timedelta(days=apos_dias)
        if liberado > now:
            pulados.append(
                Skipped(item.id, f"repete só a partir de {liberado.date().isoformat()}")
            )
            continue
        candidatos.append((item, ultima))

    def chave(par: tuple[QueueItem, datetime]):
        item, ultima = par
        nota = notas.get(item.id)
        if nota is None:
            # Sem medição: depois de todos os medidos, o mais antigo primeiro.
            return (1, 0.0, 0.0, ultima)
        return (0, -nota.visitas, -nota.views, ultima)

    ordenados = [item for item, _ in sorted(candidatos, key=chave)]
    if not ordenados:
        return Selection(None, [], pulados)
    return Selection(ordenados[0], ordenados, pulados)
