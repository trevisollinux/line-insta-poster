"""Métricas da conta: a ponte entre alcance e negócio.

O que se testa aqui é o que costuma sair errado calado: a data deslocada por
causa do `end_time`, a mesclagem que apaga o que já estava medido, e o retrato
de seguidores carimbado em dia que ninguém mediu.
"""
import os
import tempfile
import unittest
from datetime import datetime, timezone

from poster import conta
from poster.graph import GraphError


class ClienteFalso:
    def __init__(self, respostas, erros=None):
        self.respostas = respostas
        self.erros = erros or {}
        self.chamadas = []

    def get(self, path, params=None):
        self.chamadas.append((path, params or {}))
        if path in self.erros:
            # Erra uma vez e sai do caminho: o que se testa é a negociação
            # conseguir seguir, não o cliente falhar para sempre.
            raise self.erros.pop(path)
        return self.respostas.get(path, {})


def serie(nome, pares):
    return {
        "data": [
            {
                "name": nome,
                "values": [
                    {"value": valor, "end_time": fim} for fim, valor in pares
                ],
            }
        ]
    }


class DataTest(unittest.TestCase):
    def test_end_time_e_o_fim_da_janela_nao_o_dia(self):
        """`end_time` 20/09 07:00 fecha o dia 19.

        Sem o desconto, a série inteira fica um dia à frente — e a comparação
        com o dia em que um post saiu passa a apontar para o dia seguinte.
        """
        payload = serie("reach", [("2026-09-20T07:00:00+0000", 120)])

        self.assertEqual(conta._por_data(payload), {"2026-09-19": {"reach": 120}})

    def test_varias_metricas_caem_na_mesma_data(self):
        payload = {
            "data": [
                serie("reach", [("2026-09-20T07:00:00+0000", 120)])["data"][0],
                serie("profile_views", [("2026-09-20T07:00:00+0000", 9)])["data"][0],
            ]
        }

        self.assertEqual(
            conta._por_data(payload),
            {"2026-09-19": {"reach": 120, "profile_views": 9}},
        )


class NegociacaoTest(unittest.TestCase):
    """A API recusa o pedido inteiro por causa de uma métrica que a conta não
    tem. Desistir da captura seria perder as outras junto."""

    def test_tira_a_metrica_recusada_e_tenta_de_novo(self):
        cliente = ClienteFalso(
            {"123/insights": serie("reach", [("2026-09-20T07:00:00+0000", 10)])},
            {"123/insights": GraphError("metric website_clicks não suportada")},
        )

        resultado = conta.insights(cliente, "123", dias=2)

        self.assertEqual(resultado, {"2026-09-19": {"reach": 10}})
        pedidas = cliente.chamadas[-1][1]["metric"]
        self.assertNotIn("website_clicks", pedidas)


class MesclagemTest(unittest.TestCase):
    def test_leitura_nova_vence_a_antiga_no_mesmo_dia(self):
        """Aqui não vale o maior, ao contrário do story.

        Seguidor pode cair, e leitura do meio do dia é parcial de propósito —
        a mais recente é a mais próxima do fechado.
        """
        antigas = [{"data": "2026-09-19", "reach": "100", "seguidores": "1200"}]
        novas = [{"data": "2026-09-19", "reach": "140"}]

        [linha] = conta.mesclar(antigas, novas)

        self.assertEqual(linha["reach"], "140")
        self.assertEqual(linha["seguidores"], "1200", "o que não veio não se apaga")

    def test_dias_ficam_em_ordem(self):
        linhas = conta.mesclar(
            [{"data": "2026-09-19"}], [{"data": "2026-09-17"}, {"data": "2026-09-18"}]
        )

        self.assertEqual([l["data"] for l in linhas], ["2026-09-17", "2026-09-18", "2026-09-19"])


class RetratoTest(unittest.TestCase):
    def test_seguidores_entram_so_no_dia_mais_recente(self):
        """Carimbar o número de hoje na janela inteira inventa histórico.

        Quem olhasse o CSV depois veria uma contagem estável por sete dias que
        nunca foi medida — e concluiria que a conta não cresceu.
        """
        series = {
            "2026-09-18": {"reach": 90},
            "2026-09-19": {"reach": 120},
        }

        linhas = conta.montar_linhas(
            series, {"seguidores": 1200, "publicacoes": 135},
            agora=datetime(2026, 9, 20, tzinfo=timezone.utc),
        )

        self.assertNotIn("seguidores", linhas[0])
        self.assertEqual(linhas[1]["seguidores"], "1200")


class ArquivoTest(unittest.TestCase):
    def test_grava_e_rele(self):
        caminho = os.path.join(tempfile.mkdtemp(), "conta.csv")

        conta.gravar([{"data": "2026-09-19", "reach": "120", "seguidores": "1200"}], caminho)

        [linha] = conta.carregar(caminho)
        self.assertEqual(linha["data"], "2026-09-19")
        self.assertEqual(linha["reach"], "120")


if __name__ == "__main__":
    unittest.main()
