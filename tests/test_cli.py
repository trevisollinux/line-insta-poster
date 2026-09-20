"""A CLI é o que o workflow chama — os códigos de saída são contrato."""
import contextlib
import io
import json
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
            # legenda com preço e sem reviewed_price: a trava tem de pegar
            handle.write(
                "- id: a\n  url: https://x/a.jpg\n  caption: 'Bolsa R$ 890'\n"
            )

        self.assertEqual(
            main(["validate", "--queue", caminho, "--state", self.state]), EXIT_FAIL
        )

    def test_publish_dry_run_usa_a_fila_do_repositorio(self):
        """Só exige que a fila versionada seja publicável — vazia ou não."""
        codigo = main(["publish", "--dry-run", "--queue", FILA, "--state", self.state])

        self.assertIn(codigo, (EXIT_OK, EXIT_NOTHING))

    def test_publish_dry_run_nao_precisa_de_credencial(self):
        codigo = main(["publish", "--dry-run", "--queue", EXEMPLO, "--state", self.state])

        self.assertEqual(codigo, EXIT_OK)
        self.assertFalse(os.path.exists(self.state), "dry run não grava estado")

    def test_publish_sem_item_elegivel_sai_com_codigo_proprio(self):
        """Fila própria, não a do repositório: ela tem conteúdo real e muda."""
        vazia = os.path.join(self.dir.name, "vazia.yaml")
        with open(vazia, "w", encoding="utf-8") as handle:
            handle.write("# sem itens\n")

        codigo = main(["publish", "--dry-run", "--queue", vazia, "--state", self.state])

        self.assertEqual(codigo, EXIT_NOTHING)

    def test_publish_sem_credencial_falha_com_alerta(self):
        codigo = main(["publish", "--queue", EXEMPLO, "--state", self.state])

        self.assertEqual(codigo, EXIT_FAIL)


class MaxPorDiaTest(unittest.TestCase):
    """O limite diário separa "recuperar o que faltou" de "publicar mais um".

    Sem ele, a execução de recuperação vira um terceiro story diário, no pior
    horário do dia, sem ninguém ter pedido.
    """

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.state = os.path.join(self.dir.name, "published.json")
        # Fila própria, com item elegível de verdade. Apontar para a fila do
        # repositório faria o teste passar por ela estar vazia, e não pelo
        # limite — um verde que não prova nada.
        self.fila = os.path.join(self.dir.name, "stories.yaml")
        with open(self.fila, "w", encoding="utf-8") as handle:
            handle.write(
                "- id: teste-1\n"
                "  media_type: STORIES\n"
                "  url: https://media.example/foto.jpg\n"
            )

    def _estado(self, quantos):
        from datetime import datetime, timedelta, timezone

        agora = datetime.now(timezone(timedelta(hours=-3)))
        entradas = [
            {
                "item_id": f"ja-{n}",
                "media_id": f"m{n}",
                "container_id": "c",
                "media_type": "STORIES",
                "published_at": agora.astimezone(timezone.utc).isoformat(),
            }
            for n in range(quantos)
        ]
        with open(self.state, "w", encoding="utf-8") as handle:
            json.dump({"version": 1, "published": entradas}, handle)

    def _rodar(self, limite):
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            codigo = main([
                "publish", "--dry-run", "--queue", self.fila, "--state", self.state,
                "--media-type", "STORIES", "--max-por-dia", str(limite),
            ])
        return codigo, saida.getvalue()

    def test_dia_completo_nao_publica(self):
        self._estado(2)

        codigo, texto = self._rodar(2)

        self.assertEqual(codigo, EXIT_NOTHING)
        self.assertIn("nada a recuperar", texto)
        self.assertNotIn("escolhido:", texto)

    def test_dia_devendo_segue_em_frente(self):
        self._estado(1)

        codigo, texto = self._rodar(2)

        self.assertEqual(codigo, EXIT_OK)
        self.assertIn("recuperação: o dia tem 1 de 2", texto)
        self.assertIn("escolhido: teste-1", texto)

    def test_sem_limite_publica_como_sempre(self):
        self._estado(5)

        codigo, texto = self._rodar(0)

        self.assertEqual(codigo, EXIT_OK)
        self.assertNotIn("nada a recuperar", texto)


if __name__ == "__main__":
    unittest.main()
