"""Audiência por hora: conversão de fuso e mediana."""
import unittest

from tests.support import FakeClient

from poster.audiencia import melhores_horas, online_followers, por_hora_local
from poster.graph import GraphError

IG = "17841000000000000"


def resposta(dias):
    return {"data": [{"name": "online_followers", "values": [{"value": d} for d in dias]}]}


class OnlineFollowersTest(unittest.TestCase):
    def test_le_a_serie(self):
        client = FakeClient({("GET", f"{IG}/insights"): resposta([{"0": 10, "1": 20}])})

        serie = online_followers(client, IG)

        self.assertEqual(serie, [{"0": 10, "1": 20}])
        self.assertEqual(client.chamadas[0][2]["metric"], "online_followers")

    def test_metrica_indisponivel_explica_a_alternativa(self):
        client = FakeClient({("GET", f"{IG}/insights"): GraphError("metric deprecated")})

        with self.assertRaises(GraphError) as ctx:
            online_followers(client, IG)

        self.assertIn("histórico dos próprios posts", str(ctx.exception))

    def test_sem_dados_devolve_vazio(self):
        client = FakeClient({("GET", f"{IG}/insights"): {"data": []}})

        self.assertEqual(online_followers(client, IG), [])


class FusoTest(unittest.TestCase):
    def test_converte_utc_para_local(self):
        """A API responde em UTC; 23h UTC é 20h em Brasília."""
        por_hora = por_hora_local([{"23": 500}], offset=-3)

        self.assertEqual(por_hora, {20: 500})

    def test_vira_o_dia_sem_hora_negativa(self):
        por_hora = por_hora_local([{"0": 100, "1": 200}], offset=-3)

        self.assertEqual(sorted(por_hora), [21, 22])

    def test_usa_mediana_entre_os_dias(self):
        """Um dia atípico não pode decidir o horário do mês."""
        serie = [{"20": 100}, {"20": 110}, {"20": 5000}]

        self.assertEqual(por_hora_local(serie, offset=0)[20], 110)


class MelhoresHorasTest(unittest.TestCase):
    def test_ordena_por_audiencia(self):
        self.assertEqual(
            melhores_horas({9: 50.0, 21: 300.0, 16: 120.0}, quantas=2),
            [(21, 300.0), (16, 120.0)],
        )
