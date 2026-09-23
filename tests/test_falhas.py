"""Memória de falhas: o que impede uma mídia ruim de segurar a fila.

Em 23/09 uma foto que a Meta recusava foi escolhida de novo em toda execução,
porque o item só sai da rotação depois de publicar. A fila parou atrás dela.
"""
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from poster import falhas

AGORA = datetime(2026, 9, 23, 18, 0, tzinfo=timezone.utc)


class EsperaTest(unittest.TestCase):
    def test_quem_acabou_de_falhar_fica_de_fora(self):
        registros = falhas.registrar({}, "a", "erro 2207006", agora=AGORA)

        self.assertIn("a", falhas.bloqueados(registros, agora=AGORA))

    def test_passada_a_espera_ele_volta(self):
        """Erro transitório da API não merece quarentena.

        Se ficasse fora para sempre na primeira falha, um soluço da Meta
        custaria uma foto boa.
        """
        registros = falhas.registrar({}, "a", "erro", agora=AGORA)

        self.assertEqual(
            falhas.bloqueados(registros, agora=AGORA + timedelta(hours=7)), {}
        )


class QuarentenaTest(unittest.TestCase):
    def test_falhar_demais_tira_de_circulacao(self):
        registros = {}
        for _ in range(3):
            registros = falhas.registrar(registros, "a", "recusada", agora=AGORA)

        motivo = falhas.bloqueados(registros, agora=AGORA + timedelta(days=30))["a"]

        self.assertIn("quarentena", motivo)
        self.assertIn("recusada", motivo, "o motivo real precisa chegar a quem lê")

    def test_quarentena_nao_expira_com_o_tempo(self):
        """Espera passa; quarentena não.

        Depois de três recusas o problema é a mídia, e o tempo não conserta
        mídia — só faria a fila travar de novo daqui a algumas horas.
        """
        registros = {}
        for _ in range(3):
            registros = falhas.registrar(registros, "a", "recusada", agora=AGORA)

        self.assertIn("a", falhas.bloqueados(registros, agora=AGORA + timedelta(days=365)))


class LimpezaTest(unittest.TestCase):
    def test_publicar_apaga_o_historico_do_item(self):
        registros = falhas.registrar({}, "a", "erro", agora=AGORA)

        self.assertEqual(falhas.limpar(registros, "a"), {})


class ArquivoTest(unittest.TestCase):
    def test_grava_e_rele(self):
        caminho = os.path.join(tempfile.mkdtemp(), "falhas.json")
        registros = falhas.registrar({}, "a", "erro", agora=AGORA)

        falhas.gravar(registros, caminho)

        relido = falhas.carregar(caminho)
        self.assertEqual(relido["a"]["tentativas"], 1)
        self.assertEqual(relido["a"]["ultimo_erro"], "erro")

    def test_arquivo_inexistente_nao_quebra(self):
        self.assertEqual(falhas.carregar(os.path.join(tempfile.mkdtemp(), "x.json")), {})


class SelecaoTest(unittest.TestCase):
    def test_selecao_pula_o_que_esta_bloqueado(self):
        from poster.queue_file import parse_queue
        from poster.selection import select_next

        itens = parse_queue([
            {"id": "ruim", "media_type": "STORIES", "url": "https://x/1.jpg"},
            {"id": "boa", "media_type": "STORIES", "url": "https://x/2.jpg"},
        ])

        escolha = select_next(itens, [], mode="order", bloqueados={"ruim": "falhou"})

        self.assertEqual(escolha.item.id, "boa")
        self.assertEqual([p.item_id for p in escolha.skipped], ["ruim"])


if __name__ == "__main__":
    unittest.main()
