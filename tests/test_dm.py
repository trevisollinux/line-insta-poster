"""Bot de DM: fluxos, eventos do webhook, decisão, envio e servidor — sem rede."""
import hashlib
import hmac
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from tests.support import FakeClient

from poster.dm import fluxos as fluxos_mod
from poster.dm.envio import JANELA_ALERTA, Enviador, processar
from poster.dm.estado import Estado
from poster.dm.eventos import Evento, extrair
from poster.dm.fluxos import FluxosInvalidos, interpretar, normalizar
from poster.dm.motor import decidir
from poster.dm.servidor import Aplicacao, DMConfig, assinatura_valida, criar_handler
from poster.graph import GraphError

CONTA = "17841-loja"

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


class EventosTest(unittest.TestCase):
    def corpo(self, messaging=None, changes=None):
        entrada = {"id": CONTA}
        if messaging is not None:
            entrada["messaging"] = messaging
        if changes is not None:
            entrada["changes"] = changes
        return {"object": "instagram", "entry": [entrada]}

    def test_comentario(self):
        corpo = self.corpo(
            changes=[
                {
                    "field": "comments",
                    "value": {
                        "id": "c9",
                        "text": "cupom",
                        "from": {"id": "u1", "username": "ana"},
                        "media": {"id": "m1"},
                    },
                }
            ]
        )
        [ev] = extrair(corpo, conta_id=CONTA)
        self.assertEqual((ev.tipo, ev.comentario_id, ev.media_id), ("comentario", "c9", "m1"))

    def test_ignora_comentario_da_propria_loja(self):
        corpo = self.corpo(
            changes=[{"field": "comments", "value": {"id": "c1", "from": {"id": CONTA}}}]
        )
        self.assertEqual(extrair(corpo, conta_id=CONTA), [])

    def test_ignora_eco_das_nossas_mensagens(self):
        corpo = self.corpo(
            messaging=[
                {"sender": {"id": "u1"}, "message": {"mid": "m", "text": "x", "is_echo": True}}
            ]
        )
        self.assertEqual(extrair(corpo, conta_id=CONTA), [])

    def test_ignora_mensagem_enviada_pela_conta(self):
        corpo = self.corpo(messaging=[{"sender": {"id": CONTA}, "message": {"mid": "m"}}])
        self.assertEqual(extrair(corpo, conta_id=CONTA), [])

    def test_postback_e_resposta_rapida_viram_botao(self):
        corpo = self.corpo(
            messaging=[
                {"sender": {"id": "u1"}, "postback": {"mid": "p1", "payload": "passo:cupom"}},
                {
                    "sender": {"id": "u1"},
                    "message": {
                        "mid": "q1",
                        "text": "Claro",
                        "quick_reply": {"payload": "passo:cupom"},
                    },
                },
            ]
        )
        eventos = extrair(corpo, conta_id=CONTA)
        self.assertEqual([(e.tipo, e.passo) for e in eventos], [("botao", "cupom")] * 2)

    def test_postback_alheio_e_ignorado(self):
        corpo = self.corpo(
            messaging=[{"sender": {"id": "u1"}, "postback": {"mid": "p", "payload": "OUTRO"}}]
        )
        self.assertEqual(extrair(corpo, conta_id=CONTA), [])

    def test_resposta_a_story_e_dm(self):
        corpo = self.corpo(
            messaging=[
                {
                    "sender": {"id": "u1"},
                    "message": {"mid": "s1", "text": "cupom", "reply_to": {"story": {"id": "9"}}},
                },
                {"sender": {"id": "u2"}, "message": {"mid": "d1", "text": "oi"}},
                {"sender": {"id": "u3"}, "message": {"mid": "a1", "attachments": [{}]}},
            ]
        )
        eventos = extrair(corpo, conta_id=CONTA)
        self.assertEqual([e.tipo for e in eventos], ["story", "dm"])

    def test_objeto_que_nao_e_instagram(self):
        self.assertEqual(extrair({"object": "page", "entry": []}), [])


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


def enviador(respostas, **kw):
    client = FakeClient(respostas)
    logs = []
    return Enviador(client, log=logs.append, **kw), client, logs


class EnvioTest(unittest.TestCase):
    def setUp(self):
        self.alertas = []
        import poster.dm.envio as envio_mod

        self._alert = envio_mod.alert
        envio_mod.alert = lambda msg, **kw: self.alertas.append(msg)

    def tearDown(self):
        import poster.dm.envio as envio_mod

        envio_mod.alert = self._alert

    def test_fluxo_de_comentario_completo(self):
        env, client, _ = enviador(
            {("POST", "me/messages"): {"message_id": "x"}, ("POST", "c1/replies"): {"id": "r"}}
        )
        acoes = processar(evento(), fluxos(), Estado(), env)
        self.assertEqual(len(acoes), 2)
        metodo, path, params = client.chamadas[0]
        self.assertEqual(json.loads(params["recipient"]), {"comment_id": "c1"})
        self.assertEqual(params["messaging_type"], "RESPONSE")
        self.assertEqual(client.chamadas[1][2], {"message": "Te chamei no direct!"})

    def test_evento_repetido_nao_responde_de_novo(self):
        env, client, _ = enviador(
            {("POST", "me/messages"): {"message_id": "x"}, ("POST", "c1/replies"): {"id": "r"}}
        )
        estado = Estado()
        processar(evento(), fluxos(), estado, env)
        self.assertEqual(processar(evento(), fluxos(), estado, env), [])
        self.assertEqual(len(client.chamadas), 2)

    def test_registra_cupom_so_depois_de_enviar(self):
        estado = Estado()
        env, _, _ = enviador({("POST", "me/messages"): GraphError("x", status=400)})
        processar(evento("dm", "cupom"), fluxos(), estado, env)
        self.assertFalse(estado.ja_entregue("u1", "cupom"))

        env, _, _ = enviador({("POST", "me/messages"): {"message_id": "x"}})
        processar(evento("dm", "cupom", id="e2"), fluxos(), estado, env)
        self.assertTrue(estado.ja_entregue("u1", "cupom"))

    def test_template_recusado_cai_para_texto(self):
        env, client, logs = enviador(
            {
                ("POST", "me/messages"): [
                    GraphError("template", status=400, payload={"error": {"code": 100}}),
                    {"message_id": "x"},
                ]
            }
        )
        processar(evento("dm", "cupom"), fluxos(), Estado(), env)
        segunda = json.loads(client.chamadas[1][2]["message"])
        self.assertIn("https://loja.example/", segunda["text"])
        self.assertEqual(self.alertas, [])

    def test_sem_dm_nao_responde_em_publico(self):
        # "Te chamei no direct" sem a DM ter saído seria mentira.
        env, client, _ = enviador(
            {("POST", "me/messages"): GraphError("sem permissão", status=403)}
        )
        processar(evento(), fluxos(), Estado(), env)
        self.assertEqual(client.paths(), ["me/messages", "me/messages"])
        self.assertEqual(len(self.alertas), 1)
        self.assertIn("permissão", self.alertas[0])

    def test_alerta_repetido_e_segurado(self):
        agora = [1000.0]
        env, _, _ = enviador(
            {("POST", "me/messages"): GraphError("x", status=403)}, relogio=lambda: agora[0]
        )
        estado = Estado()
        for i in range(3):
            processar(evento("dm", "cupom", id=f"e{i}"), fluxos(), estado, env)
        self.assertEqual(len(self.alertas), 1)
        agora[0] += JANELA_ALERTA + 1
        processar(evento("dm", "cupom", id="e9"), fluxos(), estado, env)
        self.assertEqual(len(self.alertas), 2)

    def test_dry_run_nao_chama_api(self):
        env, client, logs = enviador({}, dry_run=True)
        processar(evento(), fluxos(), Estado(), env)
        self.assertEqual(client.chamadas, [])
        self.assertTrue(all(linha.startswith("[dry-run]") for linha in logs))


class EstadoTest(unittest.TestCase):
    def test_visto_e_entregue(self):
        estado = Estado()
        self.assertTrue(estado.marcar_visto("a"))
        self.assertFalse(estado.marcar_visto("a"))
        self.assertFalse(estado.ja_entregue("u", "p"))
        estado.registrar_entrega("u", "p")
        estado.registrar_entrega("u", "p")
        self.assertTrue(estado.ja_entregue("u", "p"))

    def test_limpa_vistos_antigos(self):
        estado = Estado()
        estado.marcar_visto("a")
        self.assertEqual(estado.limpar_vistos(0), 1)


def cfg(**kw):
    base = dict(
        ig_user_id=CONTA, page_token="", app_secret="segredo", verify_token="frase",
        db=":memory:", fluxos="", dry_run=True, alert_webhook="", port=0,
    )
    base.update(kw)
    return DMConfig(**base)


def assinar(corpo: bytes, segredo="segredo") -> str:
    return "sha256=" + hmac.new(segredo.encode(), corpo, hashlib.sha256).hexdigest()


class ServidorTest(unittest.TestCase):
    def setUp(self):
        self.env, self.client, self.logs = enviador({}, dry_run=True)
        self.app = Aplicacao(cfg(), fluxos(), Estado(), self.env)

    def test_assinatura(self):
        corpo = b'{"a":1}'
        self.assertTrue(assinatura_valida(corpo, assinar(corpo), "segredo"))
        self.assertFalse(assinatura_valida(corpo, assinar(corpo, "outro"), "segredo"))
        self.assertFalse(assinatura_valida(corpo, "", "segredo"))
        self.assertFalse(assinatura_valida(corpo, assinar(corpo), ""))

    def test_verificacao_da_meta(self):
        ok = self.app.verificar(
            {"hub.mode": ["subscribe"], "hub.verify_token": ["frase"], "hub.challenge": ["42"]}
        )
        self.assertEqual(ok, (200, "42"))
        ruim = self.app.verificar({"hub.mode": ["subscribe"], "hub.verify_token": ["x"]})
        self.assertEqual(ruim[0], 403)

    def test_http_de_ponta_a_ponta(self):
        servidor = ThreadingHTTPServer(("127.0.0.1", 0), criar_handler(self.app))
        threading.Thread(target=servidor.serve_forever, daemon=True).start()
        self.addCleanup(servidor.server_close)
        self.addCleanup(servidor.shutdown)
        base = f"http://127.0.0.1:{servidor.server_address[1]}"

        corpo = json.dumps(
            {
                "object": "instagram",
                "entry": [
                    {"messaging": [{"sender": {"id": "u1"}, "message": {"mid": "m1", "text": "cupom"}}]}
                ],
            }
        ).encode()

        def post(assinatura):
            pedido = urllib.request.Request(
                f"{base}/webhook", data=corpo, method="POST",
                headers={"X-Hub-Signature-256": assinatura, "Content-Type": "application/json"},
            )
            try:
                with urllib.request.urlopen(pedido, timeout=5) as resposta:
                    return resposta.status
            except urllib.error.HTTPError as exc:
                return exc.code

        self.assertEqual(post("sha256=errada"), 401)
        self.assertTrue(self.app.fila.empty())
        self.assertEqual(post(assinar(corpo)), 200)

        self.app.tratar(self.app.fila.get_nowait())
        self.assertEqual(len(self.logs), 1)
        self.assertIn("Use LINE10.", self.logs[0])

        with urllib.request.urlopen(f"{base}/saude", timeout=5) as resposta:
            self.assertEqual(resposta.read(), b"ok")

    def test_config_exige_token_fora_do_dry_run(self):
        import os
        from unittest import mock

        env = {"IG_USER_ID": CONTA, "META_APP_SECRET": "s", "DM_VERIFY_TOKEN": "v"}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(RuntimeError) as ctx:
                DMConfig.from_env()
            self.assertIn("IG_PAGE_ACCESS_TOKEN", str(ctx.exception))
        with mock.patch.dict(os.environ, {**env, "DM_DRY_RUN": "true"}, clear=True):
            self.assertTrue(DMConfig.from_env().dry_run)

    def test_servidor_recusa_subir_com_trocar(self):
        from poster.dm.servidor import montar

        with self.assertRaises(RuntimeError) as ctx:
            montar(cfg(dry_run=False, page_token="t", fluxos=fluxos_mod.FLUXOS_PATH))
        self.assertIn("TROCAR", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
