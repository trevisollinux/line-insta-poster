"""Cliente HTTP: retry só no que é transitório, token fora de URL e de log."""
import unittest

from tests.support import FakeTransport

from poster.graph import GraphClient, GraphError, redact


def cliente(respostas, **kwargs):
    transporte = FakeTransport(respostas)
    client = GraphClient(
        "TOKEN-SECRETO",
        transport=transporte,
        sleep=kwargs.pop("sleep", lambda _: None),
        **kwargs,
    )
    return client, transporte


class RequestTest(unittest.TestCase):
    def test_get_manda_params_na_query_e_token_no_header(self):
        client, transporte = cliente([(200, {"id": "1"})])

        client.get("17841/media", {"fields": "id,caption"})

        metodo, url, body, headers = transporte.requisicoes[0]
        self.assertEqual(metodo, "GET")
        self.assertIn("fields=id%2Ccaption", url)
        self.assertNotIn("TOKEN-SECRETO", url)
        self.assertEqual(headers["Authorization"], "Bearer TOKEN-SECRETO")
        self.assertIsNone(body)

    def test_post_manda_params_no_corpo(self):
        client, transporte = cliente([(200, {"id": "c1"})])

        client.post("17841/media", {"image_url": "https://x/a.jpg"})

        metodo, url, body, headers = transporte.requisicoes[0]
        self.assertEqual(metodo, "POST")
        self.assertIn(b"image_url=https", body)
        self.assertEqual(headers["Content-Type"], "application/x-www-form-urlencoded")

    def test_parametro_none_e_descartado(self):
        client, transporte = cliente([(200, {})])

        client.get("17841/media", {"fields": "id", "after": None})

        self.assertNotIn("after", transporte.requisicoes[0][1])


class RetryTest(unittest.TestCase):
    def test_erro_500_e_repetido_com_backoff(self):
        dormidas = []
        client, _ = cliente(
            [(500, {"error": {"message": "temporário"}}), (200, {"id": "ok"})],
            sleep=dormidas.append,
        )

        self.assertEqual(client.get("me"), {"id": "ok"})
        self.assertEqual(dormidas, [2])

    def test_rate_limit_e_repetido(self):
        client, transporte = cliente(
            [(400, {"error": {"code": 4, "message": "limite"}}), (200, {"id": "ok"})]
        )

        self.assertEqual(client.get("me"), {"id": "ok"})
        self.assertEqual(len(transporte.requisicoes), 2)

    def test_erro_definitivo_nao_e_repetido(self):
        client, transporte = cliente(
            [(400, {"error": {"code": 100, "message": "param inválido"}})]
        )

        with self.assertRaises(GraphError) as ctx:
            client.post("17841/media", {"image_url": "https://x/a.jpg"})

        self.assertEqual(len(transporte.requisicoes), 1)
        self.assertEqual(ctx.exception.code, 100)
        self.assertIn("param inválido", str(ctx.exception))

    def test_desiste_depois_do_maximo_de_tentativas(self):
        client, transporte = cliente(
            [(503, {"error": {"message": "indisponível"}})] * 3, max_attempts=3
        )

        with self.assertRaises(GraphError) as ctx:
            client.get("me")

        self.assertEqual(len(transporte.requisicoes), 3)
        self.assertTrue(ctx.exception.transient)

    def test_resposta_nao_json_vira_erro_legivel(self):
        client, _ = cliente([(502, "<html>bad gateway</html>")] * 3)

        with self.assertRaises(GraphError) as ctx:
            client.get("me")

        self.assertIn("bad gateway", str(ctx.exception))


class RedactTest(unittest.TestCase):
    def test_esconde_token_e_segredo(self):
        texto = "GET /me?access_token=EAAB123&client_secret=abc&fields=id"

        limpo = redact(texto)

        self.assertNotIn("EAAB123", limpo)
        self.assertNotIn("abc", limpo)
        self.assertIn("fields=id", limpo)

    def test_erro_ja_nasce_sem_token(self):
        erro = GraphError("falha em /me?access_token=EAAB123")

        self.assertNotIn("EAAB123", str(erro))


class ClientConfigTest(unittest.TestCase):
    def test_token_vazio_e_recusado(self):
        with self.assertRaises(ValueError):
            GraphClient("   ")

    def test_url_usa_host_e_versao(self):
        client, _ = cliente([])

        self.assertEqual(
            client.url("/17841/media"), "https://graph.facebook.com/v21.0/17841/media"
        )


if __name__ == "__main__":
    unittest.main()
