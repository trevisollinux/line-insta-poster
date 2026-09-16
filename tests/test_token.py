"""Token: validade lida corretamente e renovação que não engole falha."""
import json
import unittest
from datetime import datetime, timedelta, timezone

from tests.support import FakeTransport

from poster.graph import GraphError
from poster.token import parse_token_info, refresh_long_lived_token, token_info, update_repo_secret

AGORA = datetime(2026, 9, 16, tzinfo=timezone.utc)


def expira_em(dias: int) -> int:
    return int((AGORA + timedelta(days=dias)).timestamp())


class TokenInfoTest(unittest.TestCase):
    def test_dias_restantes(self):
        info = parse_token_info({"data": {"is_valid": True, "expires_at": expira_em(45)}})

        self.assertEqual(info.days_left(AGORA), 45)
        self.assertIn("45 dias", info.describe(AGORA))

    def test_token_sem_expiracao(self):
        info = parse_token_info({"data": {"is_valid": True, "expires_at": 0}})

        self.assertTrue(info.never_expires)
        self.assertIsNone(info.days_left(AGORA))
        self.assertIn("sem data de expiração", info.describe(AGORA))

    def test_token_invalido_aparece_na_descricao(self):
        info = parse_token_info({"data": {"is_valid": False, "expires_at": expira_em(10)}})

        self.assertIn("INVÁLIDO", info.describe(AGORA))

    def test_token_expirado_nao_devolve_dias_negativos(self):
        info = parse_token_info({"data": {"is_valid": True, "expires_at": expira_em(-5)}})

        self.assertEqual(info.days_left(AGORA), 0)

    def test_escopos_sao_preservados(self):
        info = parse_token_info(
            {"data": {"is_valid": True, "expires_at": 0, "scopes": ["instagram_basic"]}}
        )

        self.assertEqual(info.scopes, ("instagram_basic",))

    def test_debug_token_usa_app_token(self):
        transporte = FakeTransport([(200, {"data": {"is_valid": True, "expires_at": 0}})])

        token_info("TOKEN", "APP", "SECRET", transport=transporte)

        url = transporte.requisicoes[0][1]
        self.assertIn("input_token=TOKEN", url)
        self.assertIn("access_token=APP%7CSECRET", url)


class RefreshTest(unittest.TestCase):
    def test_renovacao_devolve_token_e_validade(self):
        transporte = FakeTransport(
            [(200, {"access_token": "NOVO", "expires_in": 5184000})]
        )

        novo, expira = refresh_long_lived_token("VELHO", "APP", "SECRET", transport=transporte)

        self.assertEqual(novo, "NOVO")
        self.assertGreater((expira - datetime.now(timezone.utc)).days, 55)
        self.assertIn("grant_type=fb_exchange_token", transporte.requisicoes[0][1])

    def test_resposta_sem_token_e_erro(self):
        transporte = FakeTransport([(200, {"expires_in": 100})])

        with self.assertRaises(GraphError):
            refresh_long_lived_token("VELHO", "APP", "SECRET", transport=transporte)

    def test_erro_http_vira_graph_error(self):
        transporte = FakeTransport([(400, {"error": {"message": "token expirado"}})])

        with self.assertRaises(GraphError) as ctx:
            refresh_long_lived_token("VELHO", "APP", "SECRET", transport=transporte)

        self.assertIn("token expirado", str(ctx.exception))


class UpdateSecretTest(unittest.TestCase):
    def test_sem_pat_falha_antes_de_chamar_a_api(self):
        transporte = FakeTransport([])

        with self.assertRaises(RuntimeError) as ctx:
            update_repo_secret("dono/repo", "IG_ACCESS_TOKEN", "NOVO", "", transport=transporte)

        self.assertIn("GH_SECRETS_TOKEN", str(ctx.exception))
        self.assertEqual(transporte.requisicoes, [])

    def test_chave_publica_indisponivel_interrompe(self):
        transporte = FakeTransport([(404, {"message": "Not Found"})])

        with self.assertRaises(RuntimeError) as ctx:
            update_repo_secret("dono/repo", "IG_ACCESS_TOKEN", "NOVO", "PAT", transport=transporte)

        self.assertIn("chave pública", str(ctx.exception))

    def test_grava_secret_criptografado(self):
        try:
            from nacl import encoding, public
        except ImportError:
            self.skipTest("pynacl não instalado")
        import base64

        chave_privada = public.PrivateKey.generate()
        chave_publica = chave_privada.public_key.encode(encoding.Base64Encoder()).decode()
        transporte = FakeTransport(
            [(200, {"key": chave_publica, "key_id": "42"}), (204, "")]
        )

        update_repo_secret("dono/repo", "IG_ACCESS_TOKEN", "NOVO", "PAT", transport=transporte)

        metodo, url, body, headers = transporte.requisicoes[1]
        enviado = json.loads(body)
        self.assertEqual(metodo, "PUT")
        self.assertTrue(url.endswith("/actions/secrets/IG_ACCESS_TOKEN"))
        self.assertEqual(enviado["key_id"], "42")
        aberto = public.SealedBox(chave_privada).decrypt(
            base64.b64decode(enviado["encrypted_value"])
        )
        self.assertEqual(aberto.decode(), "NOVO")


if __name__ == "__main__":
    unittest.main()
