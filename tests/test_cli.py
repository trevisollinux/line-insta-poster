"""A CLI é o que o workflow chama — os códigos de saída são contrato."""
import os
import tempfile
import unittest

from poster.cli import EXIT_FAIL, EXIT_NOTHING, EXIT_OK, main

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXEMPLO = os.path.join(RAIZ, "queue", "posts.example.yaml")
FILA = os.path.join(RAIZ, "queue", "posts.yaml")


class CliTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.state = os.path.join(self.dir.name, "published.json")
        for chave in ("IG_USER_ID", "IG_ACCESS_TOKEN", "IG_DRY_RUN", "IG_SELECTION"):
            os.environ.pop(chave, None)

    def test_validate_aceita_o_exemplo_versionado(self):
        self.assertEqual(
            main(["validate", "--queue", EXEMPLO, "--state", self.state]), EXIT_OK
        )

    def test_validate_aceita_a_fila_do_repositorio(self):
        self.assertEqual(
            main(["validate", "--queue", FILA, "--state", self.state]), EXIT_OK
        )

    def test_validate_reprova_fila_quebrada(self):
        caminho = os.path.join(self.dir.name, "quebrada.yaml")
        with open(caminho, "w", encoding="utf-8") as handle:
            handle.write("- id: a\n  url: https://x/a.jpg\n")  # sem reviewed_price

        self.assertEqual(
            main(["validate", "--queue", caminho, "--state", self.state]), EXIT_FAIL
        )

    def test_publish_dry_run_nao_precisa_de_credencial(self):
        codigo = main(["publish", "--dry-run", "--queue", EXEMPLO, "--state", self.state])

        self.assertEqual(codigo, EXIT_OK)
        self.assertFalse(os.path.exists(self.state), "dry run não grava estado")

    def test_publish_sem_item_elegivel_sai_com_codigo_proprio(self):
        codigo = main(["publish", "--dry-run", "--queue", FILA, "--state", self.state])

        self.assertEqual(codigo, EXIT_NOTHING)

    def test_publish_sem_credencial_falha_com_alerta(self):
        codigo = main(["publish", "--queue", EXEMPLO, "--state", self.state])

        self.assertEqual(codigo, EXIT_FAIL)


if __name__ == "__main__":
    unittest.main()
