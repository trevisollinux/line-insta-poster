"""Captura de métricas de story: negociação de métricas, merge e posição no dia."""
import os
import tempfile
import unittest
from datetime import datetime, timezone

from tests.support import FakeClient

from poster import metricas_stories as ms
from poster.graph import GraphError

IG = "17841000000000000"


def story(media_id, timestamp, media_type="IMAGE"):
    return {
        "id": media_id,
        "media_type": media_type,
        "timestamp": timestamp,
        "permalink": f"https://instagram.com/stories/{media_id}",
    }


def insights_payload(**metricas):
    return {
        "data": [
            {"name": nome, "values": [{"value": valor}]}
            for nome, valor in metricas.items()
        ]
    }


class StoriesAtivosTest(unittest.TestCase):
    def test_le_os_stories_no_ar(self):
        client = FakeClient(
            {("GET", f"{IG}/stories"): {"data": [story("1", "2026-09-19T14:00:00+0000")]}}
        )

        ativos = ms.stories_ativos(client, IG)

        self.assertEqual(len(ativos), 1)
        self.assertIn("timestamp", client.chamadas[0][2]["fields"])

    def test_nenhum_no_ar_devolve_vazio(self):
        client = FakeClient({("GET", f"{IG}/stories"): {"data": []}})

        self.assertEqual(ms.stories_ativos(client, IG), [])

    def test_ignora_entrada_sem_id(self):
        client = FakeClient({("GET", f"{IG}/stories"): {"data": [{"timestamp": "x"}]}})

        self.assertEqual(ms.stories_ativos(client, IG), [])


class InsightsTest(unittest.TestCase):
    def test_le_os_valores(self):
        client = FakeClient({("GET", "9/insights"): insights_payload(views=200, reach=180)})

        self.assertEqual(ms.insights(client, "9"), {"views": 200, "reach": 180})

    def test_descarta_a_metrica_recusada_e_tenta_de_novo(self):
        # A Graph API rejeita o pedido inteiro por causa de uma métrica só e diz
        # qual é na mensagem. Perder a captura por isso seria perder o dado para
        # sempre, já que o story expira em 24h.
        client = FakeClient(
            {
                ("GET", "9/insights"): [
                    GraphError("metric (follows) is not supported"),
                    insights_payload(views=200),
                ]
            }
        )

        medidas = ms.insights(client, "9")

        self.assertEqual(medidas, {"views": 200})
        self.assertNotIn("follows", client.chamadas[1][2]["metric"])
        self.assertIn("views", client.chamadas[1][2]["metric"])

    def test_erro_sem_metrica_citada_cai_para_o_minimo(self):
        client = FakeClient(
            {
                ("GET", "9/insights"): [
                    GraphError("something went wrong"),
                    insights_payload(reach=180),
                ]
            }
        )

        self.assertEqual(ms.insights(client, "9"), {"reach": 180})
        self.assertEqual(client.chamadas[1][2]["metric"], "reach,replies")

    def test_erro_persistente_propaga(self):
        client = FakeClient(
            {
                ("GET", "9/insights"): [
                    GraphError("boom"),
                    GraphError("boom de novo"),
                ]
            }
        )

        with self.assertRaises(GraphError):
            ms.insights(client, "9")

    def test_ignora_valor_nao_numerico(self):
        client = FakeClient(
            {("GET", "9/insights"): {"data": [{"name": "views", "values": [{"value": {}}]}]}}
        )

        self.assertEqual(ms.insights(client, "9"), {})


class MontarLinhaTest(unittest.TestCase):
    def test_converte_para_o_fuso_local(self):
        agora = datetime(2026, 9, 19, 23, 0, tzinfo=timezone.utc)

        linha = ms.montar_linha(
            story("9", "2026-09-19T23:40:00+0000"), {"views": 200}, agora=agora
        )

        # 23h40 UTC é 20h40 em Brasília, no dia anterior.
        self.assertEqual(linha["data_local"], "2026-09-19")
        self.assertEqual(linha["hora_local"], "20:40")
        self.assertEqual(linha["views"], "200")

    def test_vira_o_dia_para_tras(self):
        linha = ms.montar_linha(story("9", "2026-09-20T01:30:00+0000"), {})

        self.assertEqual(linha["data_local"], "2026-09-19")
        self.assertEqual(linha["hora_local"], "22:30")

    def test_metrica_ausente_fica_vazia_e_nao_zero(self):
        # Zero e "não medido" são coisas diferentes: zero entra na mediana.
        linha = ms.montar_linha(story("9", "2026-09-19T14:00:00+0000"), {})

        self.assertEqual(linha["views"], "")

    def test_timestamp_invalido_nao_derruba(self):
        linha = ms.montar_linha(story("9", "sem data"), {"views": 5})

        self.assertEqual(linha["publicado_utc"], "")
        self.assertEqual(linha["views"], "5")


class MesclarTest(unittest.TestCase):
    def test_uma_linha_por_story(self):
        antiga = ms.montar_linha(story("9", "2026-09-19T14:00:00+0000"), {"views": 100})
        nova = ms.montar_linha(story("9", "2026-09-19T14:00:00+0000"), {"views": 180})

        linhas = ms.mesclar([antiga], [nova])

        self.assertEqual(len(linhas), 1)
        self.assertEqual(linhas[0]["views"], "180")

    def test_queda_de_contador_nao_apaga_o_maior(self):
        # Métrica de story só sobe; número menor é oscilação da API.
        antiga = ms.montar_linha(story("9", "2026-09-19T14:00:00+0000"), {"views": 300})
        nova = ms.montar_linha(story("9", "2026-09-19T14:00:00+0000"), {"views": 12})

        linhas = ms.mesclar([antiga], [nova])

        self.assertEqual(linhas[0]["views"], "300")

    def test_captura_sem_insights_preserva_a_anterior(self):
        antiga = ms.montar_linha(story("9", "2026-09-19T14:00:00+0000"), {"views": 300})
        nova = ms.montar_linha(story("9", "2026-09-19T14:00:00+0000"), {})

        linhas = ms.mesclar([antiga], [nova])

        self.assertEqual(linhas[0]["views"], "300")

    def test_story_novo_e_acrescentado(self):
        antiga = ms.montar_linha(story("9", "2026-09-19T14:00:00+0000"), {"views": 300})
        nova = ms.montar_linha(story("10", "2026-09-19T20:00:00+0000"), {"views": 90})

        self.assertEqual(len(ms.mesclar([antiga], [nova])), 2)


class GravarTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "sub", "stories.csv")

    def test_numera_a_posicao_por_dia_local(self):
        linhas = [
            ms.montar_linha(story("b", "2026-09-19T23:00:00+0000"), {"views": 100}),
            ms.montar_linha(story("a", "2026-09-19T19:40:00+0000"), {"views": 200}),
            ms.montar_linha(story("c", "2026-09-20T19:40:00+0000"), {"views": 150}),
        ]

        gravadas = ms.gravar(linhas, self.path)

        self.assertEqual([l["media_id"] for l in gravadas], ["a", "b", "c"])
        self.assertEqual([l["posicao_dia"] for l in gravadas], ["1", "2", "1"])

    def test_ida_e_volta_pelo_arquivo(self):
        linhas = [ms.montar_linha(story("a", "2026-09-19T19:40:00+0000"), {"views": 200})]

        ms.gravar(linhas, self.path)
        lidas = ms.carregar(self.path)

        self.assertEqual(lidas[0]["media_id"], "a")
        self.assertEqual(lidas[0]["views"], "200")
        self.assertEqual(lidas[0]["posicao_dia"], "1")

    def test_arquivo_inexistente_carrega_vazio(self):
        self.assertEqual(ms.carregar(self.path), [])

    def test_recalcula_a_posicao_quando_chega_story_fora_de_ordem(self):
        # Uma captura atrasada não pode deixar o arquivo com dois "1º do dia".
        ms.gravar([ms.montar_linha(story("b", "2026-09-19T23:00:00+0000"), {})], self.path)
        atrasado = ms.montar_linha(story("a", "2026-09-19T19:40:00+0000"), {})

        gravadas = ms.gravar(ms.mesclar(ms.carregar(self.path), [atrasado]), self.path)

        self.assertEqual([l["media_id"] for l in gravadas], ["a", "b"])
        self.assertEqual([l["posicao_dia"] for l in gravadas], ["1", "2"])


class ResumoTest(unittest.TestCase):
    def test_sem_dados_diz_que_nao_ha(self):
        self.assertIn("Sem leituras", ms.resumo([]))

    def test_agrupa_por_posicao_e_por_hora(self):
        linhas = ms.gravar(
            [
                ms.montar_linha(story("a", "2026-09-19T19:40:00+0000"), {"views": 200}),
                ms.montar_linha(story("b", "2026-09-19T23:00:00+0000"), {"views": 100}),
                ms.montar_linha(story("c", "2026-09-20T19:40:00+0000"), {"views": 300}),
            ],
            os.path.join(tempfile.mkdtemp(), "s.csv"),
        )

        texto = ms.resumo(linhas)

        self.assertIn("| 1º | 2 | 250 |", texto)
        self.assertIn("| 2º | 1 | 100 |", texto)
        self.assertIn("16h", texto)  # 19h40 UTC = 16h40 BRT

    def test_a_tabela_por_hora_so_usa_os_primeiros_do_dia(self):
        # Se o 2º do dia entrasse aqui, a penalidade de posição viraria
        # "hora ruim" — exatamente o erro que a tabela existe para evitar.
        linhas = ms.gravar(
            [
                ms.montar_linha(story("a", "2026-09-19T19:40:00+0000"), {"views": 200}),
                ms.montar_linha(story("b", "2026-09-20T00:00:00+0000"), {"views": 10}),
            ],
            os.path.join(tempfile.mkdtemp(), "s.csv"),
        )

        texto = ms.resumo(linhas)
        por_hora = texto.split("Por hora")[1]

        self.assertIn("16h", por_hora)
        self.assertNotIn("21h", por_hora)

    def test_avisa_que_a_amostra_e_pequena(self):
        linhas = ms.gravar(
            [ms.montar_linha(story("a", "2026-09-19T19:40:00+0000"), {"views": 200})],
            os.path.join(tempfile.mkdtemp(), "s.csv"),
        )

        self.assertIn("Amostra ainda pequena", ms.resumo(linhas))


if __name__ == "__main__":
    unittest.main()


class CurvaTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "curva.csv")

    def ponto(self, media_id, publicado, horas_depois, **medidas):
        publicado_dt = datetime.strptime(publicado, "%Y-%m-%dT%H:%M:%S%z")
        agora = publicado_dt.replace(tzinfo=timezone.utc)
        agora = agora.fromtimestamp(
            agora.timestamp() + horas_depois * 3600, tz=timezone.utc
        )
        return ms.montar_ponto(story(media_id, publicado), medidas, agora=agora)

    def test_calcula_a_idade_do_story(self):
        ponto = self.ponto("a", "2026-09-19T19:40:00+0000", 3, views=80)

        self.assertEqual(ponto["idade_horas"], "3")
        self.assertEqual(ponto["views"], "80")

    def test_arredonda_a_idade(self):
        # O runner do Actions atrasa alguns minutos; sem arredondar, cada story
        # cairia numa idade diferente e a curva não seria comparável.
        ponto = self.ponto("a", "2026-09-19T19:40:00+0000", 3.1, views=80)

        self.assertEqual(ponto["idade_horas"], "3")

    def test_acumula_pontos_ao_longo_das_horas(self):
        curva = []
        for hora, views in ((1, 60), (2, 95), (6, 120)):
            curva = ms.anexar_curva(
                curva, [self.ponto("a", "2026-09-19T19:40:00+0000", hora, views=views)]
            )

        self.assertEqual([p["idade_horas"] for p in ms.gravar_curva(curva, self.path)],
                         ["1", "2", "6"])
        self.assertEqual([p["views"] for p in ms.gravar_curva(curva, self.path)],
                         ["60", "95", "120"])

    def test_nao_duplica_a_mesma_idade(self):
        primeiro = self.ponto("a", "2026-09-19T19:40:00+0000", 2, views=95)
        repetido = self.ponto("a", "2026-09-19T19:40:00+0000", 2.2, views=97)

        curva = ms.anexar_curva([primeiro], [repetido])

        self.assertEqual(len(curva), 1)
        self.assertEqual(curva[0]["views"], "97")

    def test_colisao_de_idade_fica_com_o_maior(self):
        primeiro = self.ponto("a", "2026-09-19T19:40:00+0000", 2, views=95)
        repetido = self.ponto("a", "2026-09-19T19:40:00+0000", 2.2, views=4)

        curva = ms.anexar_curva([primeiro], [repetido])

        self.assertEqual(curva[0]["views"], "95")

    def test_stories_diferentes_na_mesma_idade_convivem(self):
        a = self.ponto("a", "2026-09-19T19:40:00+0000", 2, views=95)
        b = self.ponto("b", "2026-09-19T23:00:00+0000", 2, views=40)

        self.assertEqual(len(ms.anexar_curva([a], [b])), 2)

    def test_ida_e_volta_pelo_arquivo(self):
        ms.gravar_curva([self.ponto("a", "2026-09-19T19:40:00+0000", 2, views=95)], self.path)

        lidos = ms.carregar_curva(self.path)

        self.assertEqual(lidos[0]["media_id"], "a")
        self.assertEqual(lidos[0]["idade_horas"], "2")

    def test_posicao_do_historico_chega_na_curva(self):
        # A posição só se sabe depois de ordenar o dia inteiro, e um story pode
        # virar "2º" horas depois de ter sido capturado como 1º.
        linhas = ms.gravar(
            [
                ms.montar_linha(story("a", "2026-09-19T19:40:00+0000"), {}),
                ms.montar_linha(story("b", "2026-09-19T23:00:00+0000"), {}),
            ],
            os.path.join(self.dir.name, "hist.csv"),
        )
        pontos = [
            self.ponto("a", "2026-09-19T19:40:00+0000", 1, views=50),
            self.ponto("b", "2026-09-19T23:00:00+0000", 1, views=30),
        ]

        aplicados = ms.aplicar_posicao(pontos, linhas)

        self.assertEqual([p["posicao_dia"] for p in aplicados], ["1", "2"])

    def test_timestamp_invalido_deixa_a_idade_vazia(self):
        ponto = ms.montar_ponto(story("a", "sem data"), {"views": 5})

        self.assertEqual(ponto["idade_horas"], "")
