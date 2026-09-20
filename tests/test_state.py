"""Estado: só entra quem já foi publicado de verdade, e nada se perde no caminho."""
import json
import os
import tempfile
import unittest

from poster.state import PublishedEntry, append_entry, last_published_at, load_state, save_state


def entrada(item_id="a", quando="2026-09-16T12:00:00+00:00", media_id="m1"):
    return PublishedEntry(
        item_id=item_id,
        media_id=media_id,
        container_id="c1",
        media_type="IMAGE",
        published_at=quando,
        permalink="https://instagram.com/p/x",
    )


class StateTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "published.json")

    def test_arquivo_inexistente_vira_lista_vazia(self):
        self.assertEqual(load_state(self.path), [])

    def test_ida_e_volta(self):
        save_state([entrada()], self.path)

        [lida] = load_state(self.path)

        self.assertEqual(lida.item_id, "a")
        self.assertEqual(lida.media_id, "m1")
        self.assertEqual(lida.permalink, "https://instagram.com/p/x")

    def test_append_preserva_o_que_ja_estava(self):
        save_state([entrada("a")], self.path)

        append_entry(entrada("b", media_id="m2"), self.path)

        self.assertEqual([e.item_id for e in load_state(self.path)], ["a", "b"])

    def test_arquivo_tem_versao_e_carimbo(self):
        save_state([entrada()], self.path)

        with open(self.path, encoding="utf-8") as handle:
            dados = json.load(handle)

        self.assertEqual(dados["version"], 1)
        self.assertIn("updated_at", dados)

    def test_last_published_at_pega_a_publicacao_mais_recente(self):
        entradas = [
            entrada("a", "2026-01-01T10:00:00+00:00"),
            entrada("a", "2026-06-01T10:00:00+00:00"),
            entrada("b", "2026-09-01T10:00:00+00:00"),
        ]

        self.assertEqual(last_published_at(entradas, "a").month, 6)
        self.assertIsNone(last_published_at(entradas, "inexistente"))

    def test_lista_crua_tambem_e_aceita(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump([{"item_id": "a", "media_id": "m", "published_at": ""}], handle)

        self.assertEqual(load_state(self.path)[0].item_id, "a")


class TipoNoEstadoTest(unittest.TestCase):
    """O tipo precisa sobreviver no estado, não na fila.

    A fila é mexida e esvaziada; o estado é o que resta. Se o tipo morasse só
    na fila, daqui a um mês ninguém conseguiria dizer que tipo de foto era o
    story que rendeu — que é exatamente a pergunta que o campo existe para
    responder.
    """

    def test_grava_e_rele_o_tipo(self):
        caminho = os.path.join(tempfile.mkdtemp(), "published.json")
        entrada = PublishedEntry(
            item_id="a",
            media_id="m",
            container_id="c",
            media_type="STORIES",
            published_at="2026-09-20T18:00:00+00:00",
            tipo="bastidor",
        )

        save_state([entrada], caminho)

        self.assertEqual(load_state(caminho)[0].tipo, "bastidor")

    def test_estado_antigo_sem_tipo_continua_lendo(self):
        # published.json já tem quatro publicações gravadas sem o campo.
        caminho = os.path.join(tempfile.mkdtemp(), "published.json")
        with open(caminho, "w", encoding="utf-8") as handle:
            json.dump(
                {
                    "version": 1,
                    "published": [
                        {
                            "item_id": "a",
                            "media_id": "m",
                            "container_id": "c",
                            "media_type": "STORIES",
                            "published_at": "2026-09-20T18:00:00+00:00",
                        }
                    ],
                },
                handle,
            )

        self.assertEqual(load_state(caminho)[0].tipo, "")


if __name__ == "__main__":
    unittest.main()
