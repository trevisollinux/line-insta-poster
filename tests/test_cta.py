import io
import os
import tempfile
import unittest

from PIL import Image

from poster import cta, queue_file, relatorio, state
from datetime import datetime, timezone


def foto(largura=1080, altura=1920, cor=(200, 180, 160)) -> bytes:
    saida = io.BytesIO()
    Image.new("RGB", (largura, altura), cor).save(saida, "JPEG")
    return saida.getvalue()


ORIGEM = "https://cdn.jsdelivr.net/gh/dono/midia@main/inbox/foto.jpg"


def item(**extra) -> dict:
    base = {"id": "foto", "media_type": "STORIES", "url": ORIGEM}
    base.update(extra)
    return base


class ValidacaoTest(unittest.TestCase):
    def test_cta_valido(self):
        self.assertEqual(
            cta.problemas_do_cta({"titulo": "Caramelo ou marinho?", "acao": "Responda ↓"}), []
        )

    def test_acao_obrigatoria(self):
        self.assertTrue(cta.problemas_do_cta({"titulo": "Só título"}))

    def test_nao_e_mapa(self):
        self.assertTrue(cta.problemas_do_cta("Responda"))

    def test_campo_desconhecido(self):
        problemas = cta.problemas_do_cta({"acao": "Responda", "cor": "azul"})
        self.assertTrue(any("desconhecido" in p for p in problemas))

    def test_acao_longa_demais(self):
        self.assertTrue(cta.problemas_do_cta({"acao": "x" * (cta.ACAO_MAX + 1)}))

    def test_recusa_preco(self):
        problemas = cta.problemas_do_cta({"titulo": "Por R$ 390", "acao": "Responda"})
        self.assertTrue(any("preço" in p for p in problemas))

    def test_recusa_urgencia(self):
        problemas = cta.problemas_do_cta({"titulo": "Últimas peças!", "acao": "Responda"})
        self.assertTrue(any("urgência" in p for p in problemas))


class DesenhoTest(unittest.TestCase):
    def test_sai_sempre_em_9_16(self):
        for tamanho in [(1080, 1920), (1206, 2144), (1440, 1851), (1000, 1000), (2688, 4119)]:
            with self.subTest(tamanho=tamanho):
                saida = cta.renderizar(foto(*tamanho), cta.Cta("Responda ↓", "Título"))
                self.assertEqual(Image.open(io.BytesIO(saida)).size, (1080, 1920))

    def test_texto_fica_fora_da_zona_coberta(self):
        """Na base, o campo de mensagem cobre; o desenho não pode passar dali."""
        saida = Image.open(io.BytesIO(
            cta.renderizar(foto(cor=(0, 0, 0)), cta.Cta("Responda este story ↓"))
        ))
        abaixo = saida.crop((0, cta.BASE_SEGURA + 30, 1080, 1920))
        self.assertLess(abaixo.convert("L").getextrema()[1], 60)

    def test_faixa_nao_cobre_a_foto(self):
        """No layout faixa, o texto fica abaixo da foto, nunca por cima dela."""
        branca = foto(cor=(255, 255, 255))
        saida = Image.open(io.BytesIO(
            cta.renderizar(branca, cta.Cta("Responda ↓", "Título", layout="faixa"))
        )).convert("L")
        # a foto inteira (branca) aparece; o texto começa abaixo dela
        linhas_brancas = [y for y in range(0, 1920, 10) if saida.getpixel((540, y)) > 252]
        self.assertTrue(linhas_brancas)
        self.assertLess(max(linhas_brancas), cta.BASE_SEGURA - 200)

    def test_layout_invalido(self):
        self.assertTrue(cta.problemas_do_cta({"acao": "Responda", "layout": "lado"}))

    def test_layout_sobre_nao_muda_assinatura_antiga(self):
        self.assertEqual(
            cta.Cta("R", "T").assinatura("x"), cta.Cta("R", "T", layout="sobre").assinatura("x")
        )
        self.assertNotEqual(
            cta.Cta("R", "T").assinatura("x"), cta.Cta("R", "T", layout="faixa").assinatura("x")
        )

    def test_sem_titulo(self):
        saida = cta.renderizar(foto(), cta.Cta("Toque em @line_store"))
        self.assertTrue(saida.startswith(b"\xff\xd8"))

    def test_imagem_invalida(self):
        with self.assertRaises(cta.CtaError):
            cta.renderizar(b"nao e imagem", cta.Cta("Responda"))

    def test_quebra_equilibrada(self):
        from PIL import ImageFont

        fonte = ImageFont.truetype(cta.FONTE_TITULO, 84)
        linhas = cta._quebrar("A mochila que vai com tudo.", fonte, 920)
        self.assertEqual(len(linhas), 2)
        self.assertGreater(len(linhas[1].split()), 1, linhas)

    def test_assinatura_muda_com_texto_e_origem(self):
        a = cta.Cta("Responda", "Um")
        self.assertNotEqual(a.assinatura("x"), cta.Cta("Responda", "Dois").assinatura("x"))
        self.assertNotEqual(a.assinatura("x"), a.assinatura("y"))
        self.assertEqual(a.assinatura("x"), cta.Cta("Responda", "Um").assinatura("x"))


class AplicarTest(unittest.TestCase):
    def setUp(self):
        self.raiz = tempfile.mkdtemp()
        self.baixados: list[str] = []

    def ler(self, url: str) -> bytes:
        self.baixados.append(url)
        return foto()

    def aplicar(self, itens, **kw):
        return cta.aplicar(itens, ler_origem=self.ler, raiz=self.raiz, repo="dono/poster", **kw)

    def arquivos(self):
        pasta = os.path.join(self.raiz, cta.DESTINO_SUBDIR)
        return sorted(os.listdir(pasta)) if os.path.isdir(pasta) else []

    def test_gera_e_troca_url(self):
        itens = [item(cta={"titulo": "Oi", "acao": "Responda"})]
        resultado = self.aplicar(itens)

        self.assertEqual(resultado.gerados, ["foto"])
        self.assertEqual(itens[0]["url_original"], ORIGEM)
        self.assertTrue(itens[0]["url"].startswith(
            "https://cdn.jsdelivr.net/gh/dono/poster@main/media/stories-cta/foto-"
        ))
        self.assertEqual(len(self.arquivos()), 1)

    def test_segunda_rodada_nao_regera(self):
        itens = [item(cta={"acao": "Responda"})]
        self.aplicar(itens)
        resultado = self.aplicar(itens)
        self.assertEqual(resultado.mantidos, ["foto"])
        self.assertEqual(self.baixados, [ORIGEM])

    def test_mudar_texto_gera_arquivo_novo_e_apaga_o_velho(self):
        itens = [item(cta={"acao": "Responda"})]
        self.aplicar(itens)
        url_velha = itens[0]["url"]
        itens[0]["cta"] = {"acao": "Toque em @line_store"}
        self.aplicar(itens)

        self.assertNotEqual(itens[0]["url"], url_velha)
        self.assertEqual(self.baixados, [ORIGEM, ORIGEM], "regera da original, não da com CTA")
        self.assertEqual(len(self.arquivos()), 1)

    def test_tirar_cta_volta_a_foto_original(self):
        itens = [item(cta={"acao": "Responda"})]
        self.aplicar(itens)
        del itens[0]["cta"]
        resultado = self.aplicar(itens)

        self.assertEqual(resultado.removidos, ["foto"])
        self.assertEqual(itens[0]["url"], ORIGEM)
        self.assertNotIn("url_original", itens[0])
        self.assertNotIn("cta_render", itens[0])
        self.assertEqual(self.arquivos(), [])

    def test_video_falha_sem_parar_os_outros(self):
        itens = [
            item(id="video", url="https://x/video.mp4", cta={"acao": "Responda"}),
            item(cta={"acao": "Responda"}),
        ]
        resultado = self.aplicar(itens)
        self.assertEqual(resultado.gerados, ["foto"])
        self.assertEqual(len(resultado.falhas), 1)
        self.assertEqual(itens[0]["url"], "https://x/video.mp4")

    def test_item_sem_cta_nao_e_tocado(self):
        itens = [item()]
        self.aplicar(itens)
        self.assertEqual(itens, [item()])


class FilaTest(unittest.TestCase):
    def test_cta_so_conta_depois_de_gerado(self):
        pendente = queue_file.parse_queue([item(cta={"acao": "Responda"})])[0]
        self.assertEqual(pendente.cta, "")
        gerado = queue_file.parse_queue(
            [item(cta={"acao": "Responda"}, cta_render="abc", url_original=ORIGEM)]
        )[0]
        self.assertEqual(gerado.cta, "Responda")

    def test_cta_invalido_barra_a_fila(self):
        with self.assertRaises(queue_file.QueueError):
            queue_file.parse_queue([item(cta={"titulo": "R$ 390"})])

    def test_cta_fora_de_story(self):
        with self.assertRaises(queue_file.QueueError):
            queue_file.parse_queue([
                {"id": "x", "media_type": "IMAGE", "url": ORIGEM, "cta": {"acao": "Responda"}}
            ])

    def test_cta_em_video(self):
        with self.assertRaises(queue_file.QueueError):
            queue_file.parse_queue([item(url="https://x/v.mp4", cta={"acao": "Responda"})])

    def test_fila_versionada_tem_cta_valido(self):
        itens = queue_file.load_queue(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "queue", "stories.yaml"
        ))
        self.assertTrue(any(i.cta for i in itens))


class EstadoERelatorioTest(unittest.TestCase):
    def test_estado_guarda_o_cta(self):
        caminho = os.path.join(tempfile.mkdtemp(), "published.json")
        state.append_entry(
            state.PublishedEntry("a", "1", "c", "STORIES", "2026-11-01T15:00:00+00:00", cta="Responda"),
            caminho,
        )
        self.assertEqual(state.load_state(caminho)[0].cta, "Responda")

    def test_compara_com_e_sem_cta(self):
        agora = datetime(2026, 11, 1, tzinfo=timezone.utc)
        publicados = [
            relatorio.Publicado("a", "1", "", agora, views=200, respostas=1, visitas_perfil=2),
            relatorio.Publicado("b", "2", "", agora, views=210, respostas=4, visitas_perfil=6, cta="Responda"),
            relatorio.Publicado("c", "3", "", agora, views=None, cta="Responda"),
        ]
        grupos = relatorio.com_e_sem_cta(publicados)
        self.assertEqual(grupos["com CTA"]["n"], 1)
        self.assertEqual(grupos["com CTA"]["respostas"], 4)
        self.assertEqual(grupos["sem CTA"]["visitas_perfil"], 2)

        texto = relatorio.markdown(relatorio.Resumo(agora, agora, publicados))
        self.assertIn("Com e sem CTA", texto)


if __name__ == "__main__":
    unittest.main()
