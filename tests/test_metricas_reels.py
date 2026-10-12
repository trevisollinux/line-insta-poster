"""Coletor de Reels: só Reel da janela, origem robô/manual, curva por dia de vida."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

from tests.support import FakeClient

from poster import metricas_reels as mr
from poster.cli import main
from poster.curadoria import parse_media
from poster.graph import GraphError
from poster.state import PublishedEntry

IG = "17841000000000000"
AGORA = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)


def midia(media_id, timestamp, produto="REELS", **extra):
    return {
        "id": media_id,
        "timestamp": timestamp,
        "media_type": "VIDEO",
        "media_product_type": produto,
        "permalink": f"https://www.instagram.com/reel/{media_id}/",
        "caption": "Uma bolsa.\nTrês jeitos de usar.",
        "like_count": 15,
        "comments_count": 0,
        **extra,
    }


def insights_payload(**metricas):
    return {
        "data": [
            {"name": nome, "values": [{"value": valor}]}
            for nome, valor in metricas.items()
        ]
    }


def reel(media_id="r1", timestamp="2026-10-10T17:38:07+0000", **extra):
    return parse_media(midia(media_id, timestamp, **extra))


class ListarTest(unittest.TestCase):
    def test_so_reels_da_janela(self):
        client = FakeClient({("GET", f"{IG}/media"): {"data": [
            midia("novo", "2026-10-10T17:38:07+0000"),
            midia("carrossel", "2026-09-30T20:21:57+0000", produto="FEED"),
            midia("velho", "2026-07-01T10:00:00+0000"),
        ]}})

        reels = mr.listar_reels(client, IG, janela_dias=60, agora=AGORA)

        self.assertEqual([r.id for r in reels], ["novo"])


class InsightsTest(unittest.TestCase):
    def test_metrica_recusada_sai_e_o_resto_e_lido(self):
        recusa = GraphError("(#100) metric[7] must be one of ...: profile_visits")
        client = FakeClient({("GET", "r1/insights"): [
            recusa, insights_payload(views=900, reach=700),
        ]})

        medidas = mr.insights(client, "r1")

        self.assertEqual(medidas, {"views": 900, "reach": 700})
        self.assertNotIn("profile_visits", client.chamadas[1][2]["metric"])

    def test_recusa_sem_nome_cai_para_o_minimo_de_reel(self):
        # O mínimo de story inclui `replies`, que Reel não tem.
        client = FakeClient({("GET", "r1/insights"): [
            GraphError("erro genérico"), insights_payload(reach=700, likes=15),
        ]})

        mr.insights(client, "r1")

        self.assertEqual(client.chamadas[1][2]["metric"], "reach,likes")


class LinhaTest(unittest.TestCase):
    def test_robo_e_manual(self):
        robo = mr.origens([PublishedEntry("juniper", "r1", "c", "REELS", "2026-10-10")])

        do_robo = mr.montar_linha(reel("r1"), {}, robo=robo, agora=AGORA)
        a_mao = mr.montar_linha(reel("r2"), {}, robo=robo, agora=AGORA)

        self.assertEqual((do_robo["origem"], do_robo["item_id"]), ("robo", "juniper"))
        self.assertEqual((a_mao["origem"], a_mao["item_id"]), ("manual", ""))

    def test_data_local_idade_e_legenda(self):
        linha = mr.montar_linha(reel(), {"views": 900}, robo={}, agora=AGORA)

        self.assertEqual((linha["data_local"], linha["hora_local"]), ("2026-10-10", "14:38"))
        # 1 dia e 18h → arredonda para 2: o atraso do cron não pode pular um dia.
        self.assertEqual(linha["idade_dias"], "2")
        self.assertEqual(linha["legenda"], "Uma bolsa. Três jeitos de usar.")
        self.assertEqual(linha["views"], "900")

    def test_insight_falhou_guarda_curtida_da_listagem(self):
        linha = mr.montar_linha(reel(), {}, robo={}, agora=AGORA)

        self.assertEqual((linha["likes"], linha["comments"], linha["views"]), ("15", "0", ""))


class MesclarTest(unittest.TestCase):
    def test_contador_fica_com_o_maior_e_tempo_medio_com_o_recente(self):
        antiga = {"media_id": "r1", "views": "900", "ig_reels_avg_watch_time": "8000",
                  "idade_dias": "1"}
        nova = {"media_id": "r1", "views": "850", "ig_reels_avg_watch_time": "6000",
                "idade_dias": "2"}

        [linha] = mr.mesclar([antiga], [nova])

        self.assertEqual(linha["views"], "900")
        self.assertEqual(linha["ig_reels_avg_watch_time"], "6000")
        self.assertEqual(linha["idade_dias"], "2")


class CurvaTest(unittest.TestCase):
    def test_um_ponto_por_dia_de_vida(self):
        dia1 = {"media_id": "r1", "idade_dias": "1", "views": "500"}
        dia1_de_novo = {"media_id": "r1", "idade_dias": "1", "views": "480"}
        dia2 = {"media_id": "r1", "idade_dias": "2", "views": "700"}

        curva = mr.anexar_curva([dia1], [dia1_de_novo, dia2])

        self.assertEqual(sorted((p["idade_dias"], p["views"]) for p in curva),
                         [("1", "500"), ("2", "700")])

    def test_resumo_compara_pela_mesma_idade(self):
        linhas = [{"media_id": "r1", "data_local": "2026-10-10", "origem": "robo",
                   "views": "1200", "permalink": "https://x/r1"}]
        curva = [{"media_id": "r1", "idade_dias": "1", "views": "500"}]

        texto = mr.resumo(linhas, curva)

        self.assertIn("| 2026-10-10 | robo | 1200 | 500 | — |", texto)


class ComandoTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        base = self.dir.name
        self.csv = os.path.join(base, "reels.csv")
        self.curva = os.path.join(base, "curva.csv")
        self.state = os.path.join(base, "published.json")
        with open(self.state, "w", encoding="utf-8") as handle:
            json.dump({"version": 1, "published": [{
                "item_id": "juniper", "media_id": "r1", "container_id": "c",
                "media_type": "REELS", "published_at": "2026-10-10T17:38:07+00:00",
            }]}, handle)
        env = mock.patch.dict(os.environ, {"IG_ACCESS_TOKEN": "t", "IG_USER_ID": IG})
        env.start()
        self.addCleanup(env.stop)

    def rodar(self, client):
        with mock.patch("poster.cli.GraphClient", return_value=client), \
                mock.patch("poster.cli.write_summary"), \
                contextlib.redirect_stdout(io.StringIO()):
            return main(["reel-metrics", "--csv", self.csv, "--curva", self.curva,
                         "--state", self.state])

    def test_grava_total_e_curva_sem_perder_o_reel_que_falhou(self):
        agora = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+0000")
        client = FakeClient({
            ("GET", f"{IG}/media"): {"data": [midia("r1", agora), midia("r2", agora)]},
            ("GET", "r1/insights"): insights_payload(views=900, reach=700),
            ("GET", "r2/insights"): [GraphError("x"), GraphError("y")],
        })

        codigo = self.rodar(client)

        self.assertEqual(codigo, 0)
        linhas = {l["media_id"]: l for l in mr.carregar(self.csv)}
        self.assertEqual((linhas["r1"]["origem"], linhas["r1"]["views"]), ("robo", "900"))
        self.assertEqual((linhas["r2"]["origem"], linhas["r2"]["likes"]), ("manual", "15"))
        self.assertEqual(len(mr.carregar_curva(self.curva)), 2)

    def test_nenhum_reel_na_janela_e_nada_a_fazer(self):
        client = FakeClient({("GET", f"{IG}/media"): {"data": []}})

        self.assertEqual(self.rodar(client), 2)


if __name__ == "__main__":
    unittest.main()
