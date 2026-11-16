"""Bot de DM, lado Python: fluxos, decisão de referência e exportação para o Worker."""
import contextlib
import io
import json
import os
import tempfile
import unittest

from poster.dm import cli as dm_cli
from poster.dm import fluxos as fluxos_mod
from poster.dm.estado import Estado
from poster.dm.fluxos import FluxosInvalidos, interpretar, normalizar
from poster.dm.motor import Evento, decidir

CASOS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dm_casos.json")

BASE = {
    "gatilhos": [
        {
            "nome": "comentario-cupom",
            "onde": "comentario",
            "palavras": ["cupom", "eu quero"],
            "resposta_publica": ["Te chamei no direct!"],
            "passo": "boas-vindas",
        },
        {"nome": "dm-cupom", "onde": "dm", "palavras": ["cupom"], "passo": "cupom"},
        {"nome": "story-cupom", "onde": "story", "palavras": ["cupom"], "passo": "cupom"},
    ],
    "passos": {
        "boas-vindas": {
            "texto": "Temos um presente.",
            "botoes": [{"titulo": "Claro, quero sim!", "vai_para": "cupom"}],
        },
        "cupom": {
            "texto": "Use LINE10.",
            "botoes": [{"titulo": "Quero meu cupom!", "url": "https://loja.example/"}],
            "uma_vez": True,
            "se_repetido": "Você já pegou: LINE10.",
        },
    },
}


def fluxos(**mudancas):
    dados = json.loads(json.dumps(BASE))
    dados.update(mudancas)
    return interpretar(dados)


def evento(tipo="comentario", texto="quero o cupom", **kw):
    padrao = dict(id="e1", usuario="u1", comentario_id="c1" if tipo == "comentario" else "")
    padrao.update(kw)
    return Evento(tipo=tipo, texto=texto, **padrao)


class FluxosTest(unittest.TestCase):
    def test_arquivo_versionado_e_valido(self):
        resultado = fluxos_mod.carregar()
        self.assertTrue(resultado.gatilhos)

    def test_normaliza_acento_e_caixa(self):
        self.assertEqual(normalizar("  CÚPOM  Já "), "cupom ja")

    def test_palavra_respeita_fronteira(self):
        f = fluxos()
        self.assertIsNotNone(f.gatilho_para("comentario", "EU QUERO!!"))
        self.assertIsNone(f.gatilho_para("comentario", "eu queroseno"))
        self.assertIsNotNone(f.gatilho_para("dm", "tem cúpom?"))

    def test_gatilho_filtra_por_post(self):
        dados = json.loads(json.dumps(BASE))
        dados["gatilhos"][0]["posts"] = ["m1"]
        f = interpretar(dados)
        self.assertIsNotNone(f.gatilho_para("comentario", "cupom", "m1"))
        self.assertIsNone(f.gatilho_para("comentario", "cupom", "m2"))

    def test_recusa_problemas_e_lista_todos(self):
        dados = json.loads(json.dumps(BASE))
        dados["gatilhos"].append({"nome": "x", "onde": "dm", "passo": "nao-existe"})
        dados["passos"]["cupom"]["botoes"][0]["titulo"] = "um título comprido demais"
        dados["passos"]["boas-vindas"]["botoes"].append({"titulo": "Sem destino"})
        with self.assertRaises(FluxosInvalidos) as ctx:
            interpretar(dados)
        mensagem = str(ctx.exception)
        self.assertIn("'nao-existe' não existe", mensagem)
        self.assertIn("`palavras` é obrigatório", mensagem)
        self.assertIn("máximo 20", mensagem)
        self.assertIn("`vai_para` OU `url`", mensagem)

    def test_story_sem_palavras_e_recusado(self):
        # Resposta ao CTA do story é venda — não pode cair no bot por padrão.
        dados = json.loads(json.dumps(BASE))
        dados["gatilhos"][2]["palavras"] = []
        with self.assertRaises(FluxosInvalidos):
            interpretar(dados)

    def test_trocar_valida_mas_fica_pendente(self):
        dados = json.loads(json.dumps(BASE))
        dados["passos"]["cupom"]["texto"] = "Use TROCAR."
        resultado = interpretar(dados)
        self.assertEqual(len(resultado.pendentes), 1)

    def test_url_precisa_ser_https(self):
        dados = json.loads(json.dumps(BASE))
        dados["passos"]["cupom"]["botoes"][0]["url"] = "http://loja.example/"
        with self.assertRaises(FluxosInvalidos):
            interpretar(dados)

    def test_mensagem_com_botoes_vira_template(self):
        passo = fluxos().passos["boas-vindas"]
        mensagem = fluxos_mod.montar_mensagem(passo)
        payload = mensagem["attachment"]["payload"]
        self.assertEqual(payload["template_type"], "button")
        self.assertEqual(payload["buttons"][0]["payload"], "passo:cupom")

    def test_alternativa_tem_links_e_respostas_rapidas(self):
        f = fluxos()
        cupom = fluxos_mod.montar_alternativa(f.passos["cupom"])
        self.assertIn("https://loja.example/", cupom["text"])
        boas = fluxos_mod.montar_alternativa(f.passos["boas-vindas"])
        self.assertEqual(boas["quick_replies"][0]["payload"], "passo:cupom")


class MotorTest(unittest.TestCase):
    def test_comentario_manda_resposta_privada_e_publica(self):
        acoes = decidir(evento(), fluxos(), Estado())
        self.assertEqual([a.tipo for a in acoes], ["enviar", "responder_comentario"])
        self.assertEqual(acoes[0].destinatario, {"comment_id": "c1"})
        self.assertEqual(acoes[1].texto, "Te chamei no direct!")

    def test_mensagem_sem_palavra_fica_para_gente(self):
        self.assertEqual(decidir(evento("dm", "quanto custa?"), fluxos(), Estado()), [])
        self.assertEqual(decidir(evento("story", "amei a caramelo"), fluxos(), Estado()), [])

    def test_botao_leva_ao_passo(self):
        [acao] = decidir(evento("botao", "", passo="cupom"), fluxos(), Estado())
        self.assertEqual(acao.destinatario, {"id": "u1"})
        self.assertEqual(acao.registrar, ("u1", "cupom"))

    def test_botao_de_passo_que_sumiu(self):
        self.assertEqual(decidir(evento("botao", "", passo="velho"), fluxos(), Estado()), [])

    def test_uma_vez_manda_se_repetido(self):
        estado = Estado()
        estado.registrar_entrega("u1", "cupom")
        [acao] = decidir(evento("dm", "cupom"), fluxos(), estado)
        self.assertEqual(acao.mensagem, {"text": "Você já pegou: LINE10."})
        self.assertIsNone(acao.registrar)

    def test_uma_vez_sem_se_repetido_fica_quieto(self):
        dados = json.loads(json.dumps(BASE))
        del dados["passos"]["cupom"]["se_repetido"]
        estado = Estado()
        estado.registrar_entrega("u1", "cupom")
        self.assertEqual(decidir(evento("dm", "cupom"), interpretar(dados), estado), [])


class CasosCompartilhadosTest(unittest.TestCase):
    """Os mesmos casos rodam em worker/test/motor.test.js — Python e Worker
    não podem discordar sobre o que responder."""

    def test_decisoes(self):
        with open(CASOS, encoding="utf-8") as handle:
            casos = json.load(handle)
        f = interpretar(casos["fluxos"])
        for caso in casos["decisoes"]:
            with self.subTest(caso=caso["nome"]):
                estado = Estado()
                for usuario, passo in caso["entregues"]:
                    estado.registrar_entrega(usuario, passo)
                acoes = decidir(Evento(**caso["evento"]), f, estado, sortear=lambda o: o[0])
                self.assertEqual([a.como_dict() for a in acoes], caso["esperado"])


class ExportarTest(unittest.TestCase):
    def test_exporta_mensagens_montadas_e_palavras_normalizadas(self):
        dados = json.loads(json.dumps(BASE))
        dados["gatilhos"][0]["palavras"] = ["Eu  QUERO"]
        exportado = fluxos_mod.exportar(interpretar(dados))
        self.assertEqual(exportado["gatilhos"][0]["palavras"], ["eu quero"])
        cupom = exportado["passos"]["cupom"]
        self.assertEqual(cupom["repetido"], {"text": "Você já pegou: LINE10."})
        self.assertTrue(cupom["uma_vez"])
        self.assertIn("attachment", cupom["mensagem"])
        self.assertIn("https://loja.example/", cupom["alternativa"]["text"])

    def rodar(self, *extra, trocar=True):
        dados = json.loads(json.dumps(BASE))
        if trocar:
            dados["passos"]["cupom"]["texto"] = "Use o cupom TROCAR."
        with tempfile.TemporaryDirectory() as pasta:
            fonte = os.path.join(pasta, "fluxos.yaml")
            with open(fonte, "w", encoding="utf-8") as handle:
                json.dump(dados, handle)  # JSON é YAML válido
            saida = os.path.join(pasta, "fluxos.json")
            parser = __import__("poster.cli", fromlist=["build_parser"]).build_parser()
            args = parser.parse_args(["dm-exportar", "--fluxos", fonte, "--saida", saida, *extra])
            with contextlib.redirect_stdout(io.StringIO()) as out:
                codigo = args.func(args)
            existe = os.path.exists(saida)
        return codigo, existe, out.getvalue()

    def test_recusa_exportar_com_trocar(self):
        # Com TROCAR o deploy para aqui, sem falhar o CI.
        codigo, existe, saida = self.rodar()
        self.assertEqual(codigo, dm_cli.EXIT_NOTHING)
        self.assertFalse(existe)
        self.assertIn("TROCAR", saida)

    def test_permitir_pendente_exporta(self):
        codigo, existe, _ = self.rodar("--permitir-pendente")
        self.assertEqual((codigo, existe), (0, True))

    def test_sem_pendente_exporta(self):
        codigo, existe, _ = self.rodar(trocar=False)
        self.assertEqual((codigo, existe), (0, True))


class TokenDaPaginaTest(unittest.TestCase):
    def test_escolhe_a_pagina_ligada_ao_instagram(self):
        from tests.support import FakeClient

        client = FakeClient(
            {
                ("GET", "me/accounts"): {
                    "data": [
                        {"name": "Outra", "access_token": "X",
                         "instagram_business_account": {"id": "9"}},
                        {"name": "LINE STORE", "access_token": "PAGINA"},
                        {"name": "LINE STORE", "access_token": "CERTO",
                         "instagram_business_account": {"id": "1"}},
                    ]
                }
            }
        )
        self.assertEqual(dm_cli.token_da_pagina("u", "1", client=client), ("LINE STORE", "CERTO"))

    def test_sem_pagina_ligada(self):
        from tests.support import FakeClient

        client = FakeClient({("GET", "me/accounts"): {"data": []}})
        with self.assertRaises(dm_cli.SemPagina):
            dm_cli.token_da_pagina("u", "1", client=client)

    def test_inscrever_pagina(self):
        from tests.support import FakeClient

        from poster.graph import GraphError

        ok = FakeClient(
            {("GET", "me"): {"id": "p1"}, ("POST", "p1/subscribed_apps"): {"success": True}}
        )
        self.assertEqual(dm_cli.inscrever_pagina("t", client=ok), "")
        self.assertEqual(ok.chamadas[1][2], {"subscribed_fields": "feed"})

        sem = FakeClient(
            {("GET", "me"): {"id": "p1"},
             ("POST", "p1/subscribed_apps"): GraphError("(#200) permissão", status=403)}
        )
        self.assertIn("permissão", dm_cli.inscrever_pagina("t", client=sem))

    def test_escopos_faltando(self):
        from unittest import mock

        class Info:
            scopes = ("instagram_basic", "instagram_manage_messages")

        with mock.patch.dict(os.environ, {"META_APP_ID": "a", "META_APP_SECRET": "b"}):
            self.assertEqual(
                dm_cli.escopos_faltando("u", info_fn=lambda *a: Info()),
                ["instagram_manage_comments"],
            )
        with mock.patch.dict(os.environ, {"META_APP_ID": "", "META_APP_SECRET": ""}):
            self.assertIsNone(dm_cli.escopos_faltando("u", info_fn=lambda *a: Info()))


if __name__ == "__main__":
    unittest.main()
