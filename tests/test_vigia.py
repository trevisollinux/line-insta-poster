"""Vigia do silêncio: a conta de quantos stories o dia deveria ter."""
import os
import tempfile
import unittest
from datetime import datetime, time, timezone

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


AGENDA = workflow("0 21 * * *", "0 0 * * *")  # 18h e 21h em Brasília


class HorariosTest(unittest.TestCase):
    def test_converte_os_crons_para_o_fuso_local(self):
        self.assertEqual(
            vigia.horarios_do_workflow(AGENDA), [time(18, 0), time(21, 0)]
        )

    def test_le_a_agenda_real_do_repositorio(self):
        # Se o vigia copiasse os horários, ele poderia vigiar um horário que
        # ninguém mais usa — calado, como o problema que ele existe para pegar.
        self.assertEqual(vigia.horarios_do_workflow(), [time(18, 0), time(21, 0)])

    def test_ignora_cron_com_curinga(self):
        self.assertEqual(vigia.horarios_do_workflow(workflow("0 */4 * * *")), [])

    def test_workflow_sem_agenda_devolve_vazio(self):
        caminho = os.path.join(tempfile.mkdtemp(), "wf.yml")
        with open(caminho, "w", encoding="utf-8") as handle:
            handle.write("name: t\non:\n  workflow_dispatch:\njobs: {}\n")

        self.assertEqual(vigia.horarios_do_workflow(caminho), [])


class ToleranciaTest(unittest.TestCase):
    def agora(self, hhmm: str) -> datetime:
        return datetime.fromisoformat(f"2026-09-19T{hhmm}").replace(tzinfo=BRT)

    def test_horario_recem_vencido_ainda_nao_conta(self):
        # Cron do GitHub atrasa alguns minutos por rotina; cobrar às 18h01
        # geraria alarme falso quase todo dia.
        vencidos = vigia.horarios_vencidos([time(18, 0)], self.agora("18:20"))

        self.assertEqual(vencidos, [])

    def test_passada_a_tolerancia_o_horario_conta(self):
        vencidos = vigia.horarios_vencidos([time(18, 0)], self.agora("18:46"))

        self.assertEqual(vencidos, [time(18, 0)])

    def test_antes_do_primeiro_horario_nada_e_cobrado(self):
        vencidos = vigia.horarios_vencidos(
            [time(18, 0), time(21, 0)], self.agora("09:00")
        )

        self.assertEqual(vencidos, [])


class AvaliarTest(unittest.TestCase):
    def agora(self, hhmm: str) -> datetime:
        return datetime.fromisoformat(f"2026-09-19T{hhmm}").replace(tzinfo=BRT)

    def diagnostico(self, hhmm, entradas):
        return vigia.avaliar(
            entradas, agora=self.agora(hhmm), caminho_workflow=AGENDA
        )

    def test_dia_em_dia_nao_acusa_nada(self):
        d = self.diagnostico("21:50", [entrada("2026-09-19T18:03"), entrada("2026-09-19T21:04")])

        self.assertTrue(d.ok)
        self.assertEqual((d.esperados, d.publicados), (2, 2))

    def test_acusa_o_story_que_nao_saiu(self):
        d = self.diagnostico("21:50", [entrada("2026-09-19T18:03")])

        self.assertFalse(d.ok)
        self.assertEqual(d.faltando, 1)

    def test_dia_totalmente_silencioso(self):
        d = self.diagnostico("21:50", [])

        self.assertEqual(d.faltando, 2)

    def test_story_atrasado_ainda_conta_para_o_dia(self):
        # O de hoje saiu 53 min depois do horário. Cobrar por atraso dentro do
        # mesmo dia seria ruído: o que importa é o dia ter recebido o story.
        d = self.diagnostico("18:50", [entrada("2026-09-19T18:40")])

        self.assertTrue(d.ok)

    def test_story_de_ontem_nao_cobre_hoje(self):
        d = self.diagnostico("18:50", [entrada("2026-09-18T18:03")])

        self.assertFalse(d.ok)

    def test_ignora_outros_formatos(self):
        d = self.diagnostico("18:50", [entrada("2026-09-19T18:03", media_type="REELS")])

        self.assertFalse(d.ok)

    def test_madrugada_nao_cobra_o_dia_que_mal_comecou(self):
        d = self.diagnostico("02:00", [])

        self.assertTrue(d.ok)
        self.assertEqual(d.esperados, 0)

    def test_publicacao_extra_nao_vira_numero_negativo(self):
        d = self.diagnostico(
            "18:50",
            [entrada("2026-09-19T17:33"), entrada("2026-09-19T18:03")],
        )

        self.assertEqual(d.faltando, 0)


class RelatorioTest(unittest.TestCase):
    def diagnostico(self):
        return vigia.avaliar(
            [],
            agora=datetime.fromisoformat("2026-09-19T21:50").replace(tzinfo=BRT),
            caminho_workflow=AGENDA,
        )

    def test_titulo_carrega_a_data(self):
        # É a data no título que dá uma issue por dia em vez de uma por hora.
        self.assertEqual(vigia.titulo(self.diagnostico()), "Story não publicado — 19/09/2026")

    def test_relatorio_diz_os_numeros_e_o_que_checar(self):
        texto = vigia.relatorio_markdown(self.diagnostico())

        self.assertIn("**2**", texto)
        self.assertIn("18:00, 21:00", texto)
        self.assertIn("startup failure", texto)
        self.assertIn("queue/stories.yaml", texto)


if __name__ == "__main__":
    unittest.main()
