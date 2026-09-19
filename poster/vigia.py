"""Vigia do silêncio: avisa quando o dia passou sem story.

O sistema já manda e-mail quando um job falha. O que ele não detectava é o
contrário — o job que *não aconteceu*. Foi assim que o bug do `queue` passou
despercebido: o run nascia morto, sem job, sem log e sem notificação, e de fora
parecia igualzinho a um dia em que nada estava agendado.

Ausência não dispara evento. Por isso este módulo não observa execuções: ele
compara quantos stories o dia deveria ter até agora com quantos realmente
foram publicados, e essa conta funciona mesmo quando o workflow não chegou a
existir.

Os horários esperados são lidos do próprio workflow de publicação, não
copiados aqui. Duplicar a agenda criaria a possibilidade de o vigia vigiar um
horário que ninguém mais usa — calado, como o problema que ele existe para
pegar.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from datetime import datetime, time, timedelta, timezone

import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW_PATH = os.path.join(
    REPO_ROOT, ".github", "workflows", "publicar-stories-auto.yml"
)

BRT_OFFSET = -3  # America/Sao_Paulo, fixo desde 2019

# Quanto esperar antes de considerar um horário perdido.
#
# Comecei com 45 minutos, supondo que o cron do GitHub atrasasse alguns
# minutos. Medi: neste repositório o atraso real foi de 3h20 a 4h34 em quatro
# execuções. Com 45 minutos o vigia abriria uma issue falsa todos os dias, e
# alarme que grita à toa é alarme que ninguém lê.
#
# 5h30 cobre o pior atraso observado com folga e ainda avisa no mesmo dia: o
# disparo das 13h10 é cobrado às 18h40, o das 17h10 às 22h40.
TOLERANCIA_MIN = 330


@dataclass(frozen=True)
class Diagnostico:
    agora: datetime
    esperados: int
    publicados: int
    horarios_vencidos: list[time] = field(default_factory=list)
    teste: bool = False

    @property
    def faltando(self) -> int:
        return max(0, self.esperados - self.publicados)

    @property
    def ok(self) -> bool:
        return self.faltando == 0


def horarios_do_workflow(
    caminho: str = WORKFLOW_PATH, *, offset: int = BRT_OFFSET
) -> list[time]:
    """Horários locais de publicação, lidos dos crons do workflow."""
    with open(caminho, "r", encoding="utf-8") as handle:
        documento = yaml.safe_load(handle) or {}
    # `on:` vira True em YAML 1.1; o GitHub lê a chave, não o booleano.
    gatilhos = documento.get("on", documento.get(True))
    agenda = (gatilhos or {}).get("schedule") or [] if isinstance(gatilhos, dict) else []

    horarios: list[time] = []
    for entrada in agenda:
        campos = str(entrada.get("cron", "")).split()
        if len(campos) < 2 or not (campos[0].isdigit() and campos[1].isdigit()):
            continue  # cron com curinga não descreve um horário do dia
        minuto, hora_utc = int(campos[0]), int(campos[1])
        horarios.append(time((hora_utc + offset) % 24, minuto))
    return sorted(horarios)


def horarios_vencidos(
    horarios: list[time], agora: datetime, *, tolerancia_min: int = TOLERANCIA_MIN
) -> list[time]:
    """Horários de hoje cujo prazo (horário + tolerância) já passou.

    A comparação é entre datas completas, não entre horas do dia. Parece
    detalhe e não é: com tolerância medida em horas, `agora - tolerância` cai
    no dia anterior durante a madrugada. Comparando só a hora, às 2h da manhã
    o limite viraria 20h30 "de hoje" e o vigia acusaria como perdidos todos os
    horários de um dia que mal começou — alarme falso na pior hora possível.
    """
    folga = timedelta(minutes=tolerancia_min)
    vencidos = []
    for horario in horarios:
        prazo = datetime.combine(agora.date(), horario, tzinfo=agora.tzinfo) + folga
        if prazo <= agora:
            vencidos.append(horario)
    return vencidos


def publicados_hoje(
    entradas, agora: datetime, *, offset: int = BRT_OFFSET, media_type: str = "STORIES"
) -> int:
    """Quantos itens do formato foram publicados na data local de `agora`."""
    fuso = timezone(timedelta(hours=offset))
    total = 0
    for entrada in entradas:
        if entrada.media_type.upper() != media_type:
            continue
        if not entrada.published_at:
            continue
        local = entrada.published_datetime.astimezone(fuso)
        if local.date() == agora.date():
            total += 1
    return total


def avaliar(
    entradas,
    *,
    agora: datetime | None = None,
    caminho_workflow: str = WORKFLOW_PATH,
    offset: int = BRT_OFFSET,
    tolerancia_min: int = TOLERANCIA_MIN,
) -> Diagnostico:
    fuso = timezone(timedelta(hours=offset))
    momento = (agora or datetime.now(timezone.utc)).astimezone(fuso)
    horarios = horarios_do_workflow(caminho_workflow, offset=offset)
    vencidos = horarios_vencidos(horarios, momento, tolerancia_min=tolerancia_min)
    return Diagnostico(
        agora=momento,
        esperados=len(vencidos),
        publicados=publicados_hoje(entradas, momento, offset=offset),
        horarios_vencidos=vencidos,
    )


def simulado(diagnostico: Diagnostico) -> Diagnostico:
    """Força um buraco de propósito, para exercitar o alarme inteiro.

    Alarme que nunca tocou é alarme em que não dá para confiar: a parte que
    mais quebra calada não é a conta, é o caminho que cria a issue. Testar isso
    esperando um dia ruim acontecer seria descobrir o defeito na hora errada.

    O `teste: True` viaja até o título e o corpo, para que ninguém confunda o
    ensaio com um incidente de verdade.
    """
    return replace(diagnostico, esperados=diagnostico.publicados + 1, teste=True)


def titulo(diagnostico: Diagnostico) -> str:
    # A data no título é o que permite uma issue por dia: o workflow procura
    # por este texto antes de abrir outra, e assim 24 execuções por dia não
    # viram 24 e-mails do mesmo problema.
    prefixo = "[teste] " if diagnostico.teste else ""
    return f"{prefixo}Story não publicado — {diagnostico.agora:%d/%m/%Y}"


def relatorio_markdown(diagnostico: Diagnostico) -> str:
    if diagnostico.teste:
        return (
            "### Isto é um ensaio do alarme\n\n"
            "Disparado de propósito para verificar que a issue é criada e que o "
            "e-mail chega. **Nenhum story está faltando** — pode fechar esta "
            "issue.\n\n"
            "Se você recebeu este e-mail, o aviso de silêncio funciona: no dia "
            "em que um story realmente não sair, a mensagem chega pelo mesmo "
            "caminho, sem o `[teste]` no título.\n\n"
            f"- Ensaio disparado em {diagnostico.agora:%d/%m/%Y às %H:%M}\n"
            f"- Stories publicados hoje até agora: {diagnostico.publicados}\n"
        )

    horarios = ", ".join(f"{h:%H:%M}" for h in diagnostico.horarios_vencidos) or "—"
    plural = "s" if diagnostico.faltando > 1 else ""
    return (
        f"Até **{diagnostico.agora:%H:%M}** de hoje, o esperado eram "
        f"**{diagnostico.esperados}** story(s) publicado(s) e saíram "
        f"**{diagnostico.publicados}**. Falta{'m' if diagnostico.faltando > 1 else ''} "
        f"{diagnostico.faltando} story{plural}.\n\n"
        f"- Horários já vencidos hoje: {horarios} "
        f"(com {TOLERANCIA_MIN} min de tolerância para atraso do cron)\n"
        f"- Fonte: `state/published.json`\n\n"
        "### O que checar, nesta ordem\n\n"
        "1. **A aba Actions tem um run de _Publicar Stories (automático)_ hoje?**\n"
        "   - Não tem nenhum → o cron não disparou. O GitHub atrasa e às vezes\n"
        "     pula a primeira ocorrência de um agendamento recém-alterado.\n"
        "   - Tem um com `startup failure` → o workflow está inválido. Esse caso\n"
        "     não manda e-mail sozinho, que é a razão desta issue existir.\n"
        "2. **A fila tem item elegível?** `queue/stories.yaml` acaba: cada story\n"
        "   publicado sai da rotação e não volta.\n"
        "3. **O token expirou?** Rode _Renovar token do Instagram_.\n\n"
        "Para publicar agora: Actions → _Publicar Stories (automático)_ → "
        "_Run workflow_.\n"
    )
