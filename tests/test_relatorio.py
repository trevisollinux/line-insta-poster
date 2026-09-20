"""O resumo semanal: o risco aqui não é quebrar, é mentir com cara de dado."""
import unittest
from datetime import datetime, timedelta, timezone

from poster import relatorio
from poster.state import PublishedEntry

BRT = timezone(timedelta(hours=-3))


def entrada(item_id, media_id, quando, tipo=""):
    return PublishedEntry(
        item_id=item_id,
        media_id=media_id,
        container_id="c",
        media_type="STORIES",
        published_at=quando.astimezone(timezone.utc).isoformat(),
        tipo=tipo,
    )


AGORA = datetime(2026, 9, 20, 12, 0, tzinfo=BRT)


class JanelaTest(unittest.TestCase):
    def test_pega_so_os_ultimos_dias(self):
        dentro = entrada("a", "1", AGORA - timedelta(days=2))
        fora = entrada("b", "2", AGORA - timedelta(days=9))

        resultado = relatorio.semana([dentro, fora], agora=AGORA, dias=7)

        self.assertEqual([e.item_id for e in resultado], ["a"])


class JuntarTest(unittest.TestCase):
    def test_cola_publicacao_com_medicao_pelo_media_id(self):
        """O estado sabe QUE tipo de foto era; o CSV sabe QUANTO rendeu."""
        entradas = [entrada("a", "m1", AGORA - timedelta(days=1), tipo="bastidor")]
        metricas = [{"media_id": "m1", "views": "340", "reach": "300", "profile_visits": "7"}]

        [item] = relatorio.juntar(entradas, metricas)

        self.assertEqual(item.tipo, "bastidor")
        self.assertEqual(item.views, 340)
        self.assertEqual(item.visitas_perfil, 7)

    def test_publicacao_sem_medicao_nao_some(self):
        """Story que o coletor não pegou continua contando como publicado.

        O coletor entrega 25%; sumir com o que ele perdeu faria a semana
        parecer mais vazia do que foi.
        """
        entradas = [entrada("a", "m1", AGORA - timedelta(days=1))]

        [item] = relatorio.juntar(entradas, [])

        self.assertIsNone(item.views)


class PorTipoTest(unittest.TestCase):
    def test_leva_o_tamanho_da_amostra_junto(self):
        """Mediana sem `n` do lado é como se faz alguém reorganizar a produção
        inteira em cima de duas fotos."""
        publicados = relatorio.juntar(
            [
                entrada("a", "m1", AGORA, tipo="bastidor"),
                entrada("b", "m2", AGORA, tipo="produto"),
                entrada("c", "m3", AGORA, tipo="produto"),
            ],
            [
                {"media_id": "m1", "views": "340"},
                {"media_id": "m2", "views": "150"},
                {"media_id": "m3", "views": "170"},
            ],
        )

        resultado = relatorio.por_tipo(publicados)

        self.assertEqual(resultado["bastidor"], {"n": 1, "mediana": 340})
        self.assertEqual(resultado["produto"], {"n": 2, "mediana": 160})


class ContaTest(unittest.TestCase):
    def test_compara_com_a_linha_de_uma_semana_atras(self):
        linhas = [
            {"data": "2026-09-06", "seguidores": "34000"},
            {"data": "2026-09-13", "seguidores": "34200"},
            {"data": "2026-09-19", "seguidores": "34326"},
        ]

        hoje, antes = relatorio.conta_na_semana(linhas, agora=AGORA, dias=7)

        self.assertEqual(hoje["data"], "2026-09-19")
        self.assertEqual(antes["data"], "2026-09-13")

    def test_sem_historico_nao_inventa_comparacao(self):
        hoje, antes = relatorio.conta_na_semana(
            [{"data": "2026-09-19", "seguidores": "34326"}], agora=AGORA, dias=7
        )

        self.assertEqual(hoje["data"], "2026-09-19")
        self.assertEqual(antes, {})


class MarkdownTest(unittest.TestCase):
    def test_avisa_que_a_amostra_e_pequena(self):
        publicados = relatorio.juntar(
            [
                entrada("a", "m1", AGORA, tipo="bastidor"),
                entrada("b", "m2", AGORA, tipo="produto"),
            ],
            [{"media_id": "m1", "views": "340"}, {"media_id": "m2", "views": "150"}],
        )
        resumo = relatorio.Resumo(
            inicio=AGORA - timedelta(days=7), fim=AGORA, publicados=publicados,
            fila_restante=8,
        )

        texto = relatorio.markdown(resumo)

        self.assertIn("Amostra pequena", texto)
        # A contagem tem de estar NA LINHA do tipo. O "n=" da linha de views
        # não serve: ele existiria mesmo com a tabela mentindo.
        self.assertIn("| bastidor | 1 | 340 |", texto)
        self.assertIn("| produto | 1 | 150 |", texto)

    def test_sem_tipo_diz_por_que_nao_da_para_comparar(self):
        publicados = relatorio.juntar(
            [entrada("a", "m1", AGORA)], [{"media_id": "m1", "views": "150"}]
        )
        resumo = relatorio.Resumo(
            inicio=AGORA - timedelta(days=7), fim=AGORA, publicados=publicados,
            fila_restante=8,
        )

        self.assertIn("Nenhum story tinha tipo", relatorio.markdown(resumo))


if __name__ == "__main__":
    unittest.main()
