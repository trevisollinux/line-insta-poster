"""Vigia do silêncio: a conta de quantos stories o dia deveria ter."""
import os
import tempfile
import unittest
from datetime import date, datetime, time, timezone

from tests.support import FakeClient  # noqa: F401  (garante o sys.path do pacote)

from poster import vigia
from poster.state import PublishedEntry

BRT = timezone(vigia.timedelta(hours=-3))


def entrada(publicado_local: str, media_type: str = "STORIES") -> PublishedEntry:
    momento = datetime.fromisoformat(publicado_local).replace(tzinfo=BRT)
    return PublishedEntry(
        item_id="x",
        media_id="1",
        container_id="c",
        media_type=media_type,
        published_at=momento.astimezone(timezone.utc).isoformat(),
    )


def workflow(*crons: str) -> str:
    linhas = "\n".join(f"    - cron: '{c}'" for c in crons)
    corpo = f"name: t\non:\n  schedule:\n{linhas}\njobs:\n  j:\n    runs-on: ubuntu-latest\n"
    caminho = os.path.join(tempfile.mkdtemp(), "wf.yml")
    with open(caminho, "w", encoding="utf-8") as handle:
        handle.write(corpo)
    return caminho


AGENDA = workflow("34 16 * * *", "34 20 * * *")  # fixture: disparos 13h34 e 17h34


class HorariosTest(unittest.TestCase):
    def test_converte_os_crons_para_o_fuso_local(self):
        self.assertEqual(
            vigia.horarios_do_workflow(AGENDA), [time(13, 34), time(17, 34)]
        )

    def test_le_a_agenda_real_do_repositorio(self):
        # Se o vigia copiasse os horários, ele poderia vigiar um horário que
        # ninguém mais usa — calado, como o problema que ele existe para pegar.
        #
        # O esperado vem de test_workflows, que é onde a agenda combinada está
        # fixada. Repetir os horários aqui criaria um segundo lugar para
        # esquecer de atualizar — e este teste existe justamente contra isso.
        from tests.test_workflows import HorarioDosStoriesTest

        esperados = sorted(
            time(hora, minuto) for hora, minuto in HorarioDosStoriesTest.DISPAROS_BRT
        )
        self.assertEqual(vigia.horarios_do_workflow(), esperados)

    def test_ignora_cron_com_curinga(self):
        self.assertEqual(vigia.horarios_do_workflow(workflow("0 */4 * * *")), [])

    def test_workflow_sem_agenda_devolve_vazio(self):
        caminho = os.path.join(tempfile.mkdtemp(), "wf.yml")
        with open(caminho, "w", encoding="utf-8") as handle:
            handle.write("name: t\non:\n  workflow_dispatch:\njobs: {}\n")

        self.assertEqual(vigia.horarios_do_workflow(caminho), [])


class ToleranciaTest(unittest.TestCase):
    """A folga antes de cobrar um horário.

    Os casos são escritos em relação a `TOLERANCIA_MIN`, não a minutos fixos:
    o valor já mudou uma vez (de 45 min para 5h30, quando medimos que o cron do
    GitHub atrasa até 4h34) e vai mudar de novo se o atraso mudar. Teste preso
    ao número quebraria a cada medição, sem nenhum defeito real por trás.
    """

    SLOT = time(13, 34)

    def momento(self, minutos_apos_o_slot: int) -> datetime:
        base = datetime.combine(date(2026, 9, 19), self.SLOT).replace(tzinfo=BRT)
        return base + vigia.timedelta(minutes=minutos_apos_o_slot)

    def test_dentro_da_tolerancia_ainda_nao_conta(self):
        agora = self.momento(vigia.TOLERANCIA_MIN - 10)

        self.assertEqual(vigia.horarios_vencidos([self.SLOT], agora), [])

    def test_passada_a_tolerancia_o_horario_conta(self):
        agora = self.momento(vigia.TOLERANCIA_MIN + 10)

        self.assertEqual(vigia.horarios_vencidos([self.SLOT], agora), [self.SLOT])

    def test_a_folga_cobre_o_pior_atraso_ja_medido(self):
        # 4h34 foi o pior atraso real observado neste repositório. Se a folga
        # ficar menor que isso, o vigia passa a acusar todo dia sem motivo.
        self.assertGreater(vigia.TOLERANCIA_MIN, 274)

    def test_antes_do_primeiro_horario_nada_e_cobrado(self):
        madrugada = datetime.fromisoformat("2026-09-19T02:00").replace(tzinfo=BRT)

        self.assertEqual(
            vigia.horarios_vencidos([time(13, 34), time(17, 34)], madrugada), []
        )

    def test_de_madrugada_nao_cobra_o_dia_que_mal_comecou(self):
        """Regressão: a folga de horas fazia `agora - folga` cair em ontem.

        Comparando só a hora do dia, às 2h da manhã o limite virava 20h30 e
        todos os horários do dia novo apareciam como perdidos de uma vez.
        """
        for hora in ("00:05", "02:00", "05:30", "13:33"):
            with self.subTest(agora=hora):
                agora = datetime.fromisoformat(f"2026-09-19T{hora}").replace(tzinfo=BRT)

                self.assertEqual(
                    vigia.horarios_vencidos([time(13, 34), time(17, 34)], agora), []
                )


class AvaliarTest(unittest.TestCase):
    """A conta do dia: quantos horários venceram × quantos stories saíram.

    Os relógios dos casos são calculados a partir dos horários da agenda mais
    a tolerância, nunca escritos à mão. Já quebrei esta classe duas vezes ao
    mexer na agenda e na folga — e nas duas o código estava certo, só o teste
    é que estava preso a um minuto que deixou de fazer sentido.
    """

    DIA = date(2026, 9, 19)

    def apos_vencer(self, quantos_slots: int) -> datetime:
        """Um instante logo depois de o n-ésimo horário do dia vencer."""
        horarios = vigia.horarios_do_workflow(AGENDA)
        slot = horarios[quantos_slots - 1]
        prazo = datetime.combine(self.DIA, slot, tzinfo=BRT)
        return prazo + vigia.timedelta(minutes=vigia.TOLERANCIA_MIN + 1)

    def diagnostico(self, agora, entradas):
        return vigia.avaliar(entradas, agora=agora, caminho_workflow=AGENDA)

    def publicado(self, slots_atras: int = 1, **kwargs):
        """Um story publicado logo depois do n-ésimo horário da agenda."""
        horarios = vigia.horarios_do_workflow(AGENDA)
        momento = datetime.combine(self.DIA, horarios[slots_atras - 1], tzinfo=BRT)
        momento += vigia.timedelta(minutes=20)
        return entrada(momento.replace(tzinfo=None).isoformat(), **kwargs)

    def test_dia_em_dia_nao_acusa_nada(self):
        d = self.diagnostico(
            self.apos_vencer(2), [self.publicado(1), self.publicado(2)]
        )

        self.assertTrue(d.ok)
        self.assertEqual((d.esperados, d.publicados), (2, 2))

    def test_acusa_o_story_que_nao_saiu(self):
        d = self.diagnostico(self.apos_vencer(2), [self.publicado(1)])

        self.assertFalse(d.ok)
        self.assertEqual(d.faltando, 1)

    def test_dia_totalmente_silencioso(self):
        d = self.diagnostico(self.apos_vencer(2), [])

        self.assertEqual(d.faltando, 2)

    def test_story_atrasado_ainda_conta_para_o_dia(self):
        # Story sai horas depois do disparo, por causa do atraso do cron.
        # Cobrar por atraso dentro do mesmo dia seria ruído: o que importa é o
        # dia ter recebido o story.
        d = self.diagnostico(self.apos_vencer(1), [self.publicado(1)])

        self.assertTrue(d.ok)

    def test_story_de_ontem_nao_cobre_hoje(self):
        d = self.diagnostico(self.apos_vencer(1), [entrada("2026-09-18T18:03")])

        self.assertFalse(d.ok)

    def test_ignora_outros_formatos(self):
        d = self.diagnostico(
            self.apos_vencer(1), [self.publicado(1, media_type="REELS")]
        )

        self.assertFalse(d.ok)

    def test_madrugada_nao_cobra_o_dia_que_mal_comecou(self):
        madrugada = datetime.combine(self.DIA, time(2, 0), tzinfo=BRT)

        d = self.diagnostico(madrugada, [])

        self.assertTrue(d.ok)
        self.assertEqual(d.esperados, 0)

    def test_publicacao_extra_nao_vira_numero_negativo(self):
        d = self.diagnostico(
            self.apos_vencer(1),
            [self.publicado(1), self.publicado(1)],
        )

        self.assertEqual(d.faltando, 0)


class RelatorioTest(unittest.TestCase):
    def diagnostico(self):
        # Depois do último horário vencer, calculado da agenda — não um
        # relógio fixo, que deixa de valer quando a agenda ou a folga muda.
        ultimo = vigia.horarios_do_workflow(AGENDA)[-1]
        prazo = datetime.combine(date(2026, 9, 19), ultimo, tzinfo=BRT)
        agora = prazo + vigia.timedelta(minutes=vigia.TOLERANCIA_MIN + 1)
        return vigia.avaliar([], agora=agora, caminho_workflow=AGENDA)

    def test_titulo_carrega_a_data(self):
        # É a data no título que dá uma issue por dia em vez de uma por hora.
        self.assertEqual(vigia.titulo(self.diagnostico()), "Story não publicado — 19/09/2026")

    def test_relatorio_diz_os_numeros_e_o_que_checar(self):
        texto = vigia.relatorio_markdown(self.diagnostico())

        self.assertIn("**2**", texto)
        self.assertIn("13:34, 17:34", texto)
        self.assertIn("startup failure", texto)
        self.assertIn("queue/stories.yaml", texto)


if __name__ == "__main__":
    unittest.main()


class EnsaioTest(unittest.TestCase):
    """O ensaio existe para que o alarme não estreie no dia do incidente."""

    def base(self, publicados: int = 1):
        entradas = [entrada(f"2026-09-19T1{i}:00") for i in range(publicados)]
        return vigia.avaliar(
            entradas,
            agora=datetime.fromisoformat("2026-09-19T17:45").replace(tzinfo=BRT),
            caminho_workflow=AGENDA,
        )

    def test_dia_saudavel_vira_buraco_no_ensaio(self):
        real = self.base()
        self.assertTrue(real.ok)

        self.assertFalse(vigia.simulado(real).ok)

    def test_o_ensaio_se_identifica_no_titulo(self):
        # Sem isso, um ensaio no meio de um dia ruim viraria dúvida sobre qual
        # das duas issues é o incidente de verdade.
        self.assertTrue(vigia.titulo(vigia.simulado(self.base())).startswith("[teste] "))

    def test_o_incidente_de_verdade_nao_leva_o_prefixo(self):
        self.assertFalse(vigia.titulo(self.base()).startswith("[teste]"))

    def test_o_corpo_diz_que_nada_esta_faltando(self):
        texto = vigia.relatorio_markdown(vigia.simulado(self.base()))

        self.assertIn("ensaio", texto.lower())
        self.assertIn("Nenhum story está faltando", texto)
        self.assertIn("pode fechar", texto)

    def test_o_ensaio_nao_inventa_o_numero_de_publicados(self):
        # O ensaio força o alarme, não os dados: se mentisse aqui, o teste
        # deixaria de provar que a leitura do estado funciona.
        self.assertEqual(vigia.simulado(self.base(publicados=2)).publicados, 2)

    def test_o_ensaio_nao_altera_o_diagnostico_original(self):
        real = self.base()

        vigia.simulado(real)

        self.assertTrue(real.ok)
        self.assertFalse(real.teste)
