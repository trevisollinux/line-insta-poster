"""Trava de 9:16: a API estica foto de story fora de proporção sem avisar."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest import mock

import yaml
from PIL import Image

from poster import proporcao
from poster.cli import EXIT_NOTHING, EXIT_OK, main
from poster.drive import DriveFile
from poster.inbox import problema_de_story, report_markdown


def jpeg(largura: int, altura: int) -> bytes:
    saida = io.BytesIO()
    Image.new("RGB", (largura, altura), (120, 90, 60)).save(saida, "JPEG")
    return saida.getvalue()


class ProblemaTest(unittest.TestCase):
    """Os casos são as fotos reais da fila, medidas em 30/09."""

    def test_foto_de_celular_em_9_16_passa(self):
        for largura, altura in ((1080, 1920), (1206, 2144), (941, 1672), (1036, 1848)):
            with self.subTest(f"{largura}x{altura}"):
                self.assertEqual(proporcao.problema(largura, altura), "")

    def test_photoroom_quase_9_16_passa(self):
        # 1,6 % acima de 9:16 — a diferença não aparece na tela.
        self.assertEqual(proporcao.problema(768, 1344), "")
        self.assertEqual(proporcao.problema(714, 1248), "")

    def test_as_duas_que_sairam_esticadas_sao_barradas(self):
        for largura, altura in ((1440, 1851), (2688, 4119)):
            with self.subTest(f"{largura}x{altura}"):
                motivo = proporcao.problema(largura, altura)
                self.assertIn(f"{largura}x{altura}", motivo)
                self.assertIn("larga demais", motivo)
                self.assertIn("1080x1920", motivo)

    def test_2_por_3_da_fila_atual_e_barrada(self):
        self.assertNotEqual(proporcao.problema(832, 1248), "")

    def test_horizontal_e_barrada(self):
        self.assertIn("larga demais", proporcao.problema(1920, 1080))

    def test_mais_estreita_que_9_16_tambem(self):
        self.assertIn("estreita demais", proporcao.problema(800, 2000))

    def test_dimensao_zerada_nao_passa(self):
        self.assertIn("inválidas", proporcao.problema(0, 1920))


class MedirTest(unittest.TestCase):
    def test_mede_os_bytes(self):
        self.assertEqual(proporcao.medir_bytes(jpeg(90, 160)), (90, 160))

    def test_foto_de_celular_gravada_deitada_mede_em_pe(self):
        """Pixels 1920x1080 com EXIF "gire 90°" aparecem como 1080x1920."""
        imagem = Image.new("RGB", (192, 108))
        exif = imagem.getexif()
        exif[proporcao.ORIENTACAO_EXIF] = 6
        saida = io.BytesIO()
        imagem.save(saida, "JPEG", exif=exif)

        largura, altura = proporcao.medir_bytes(saida.getvalue())

        self.assertEqual((largura, altura), (108, 192))
        self.assertEqual(proporcao.problema(largura, altura), "")

    def test_bytes_que_nao_sao_imagem(self):
        with self.assertRaises(proporcao.ProporcaoError):
            proporcao.medir_bytes(b"nao sou imagem")

    def test_mede_pela_url(self):
        dados = jpeg(72, 128)

        def abrir(url, timeout):
            return contextlib.closing(io.BytesIO(dados))

        self.assertEqual(proporcao.medir_url("https://x/a.jpg", opener=abrir), (72, 128))

    def test_falha_de_rede_vira_erro_de_medicao(self):
        def abrir(url, timeout):
            raise OSError("sem rede")

        with self.assertRaises(proporcao.ProporcaoError):
            proporcao.medir_url("https://x/a.jpg", opener=abrir)


class ImportacaoTest(unittest.TestCase):
    def test_video_nao_e_medido(self):
        video = DriveFile("v1", "tour.mp4", "video/mp4", 10)
        # Caminho inexistente: se medisse, estouraria.
        self.assertEqual(problema_de_story(video, "/nao/existe.mp4"), "")

    def test_foto_torta_tem_motivo(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = os.path.join(pasta, "a.jpg")
            with open(caminho, "wb") as handle:
                handle.write(jpeg(144, 185))
            foto = DriveFile("f1", "a.jpg", "image/jpeg", 10)
            self.assertIn("144x185", problema_de_story(foto, caminho))

    def test_relatorio_explica_como_consertar(self):
        foto = DriveFile("f1", "CYMERA_2025.jpg", "image/jpeg", 10)
        texto = report_markdown([], [], [], [], tortas=[(foto, "foto fora do formato")])
        self.assertIn("Fora do formato de story (9:16)", texto)
        self.assertIn("CYMERA_2025.jpg", texto)
        self.assertIn("reenquadre", texto)


class InboxNaoEnfileiraFotoTortaTest(unittest.TestCase):
    """Ponta a ponta: a foto 2:3 fica fora da fila e fora do registro."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        base = self.dir.name
        self.fila = os.path.join(base, "stories.yaml")
        self.estado = os.path.join(base, "inbox.json")
        self.relatorio = os.path.join(base, "relatorio.md")
        self.midia = os.path.join(base, "midia")
        for chave, valor in (("GDRIVE_SERVICE_ACCOUNT", "{}"), ("GDRIVE_FOLDER_ID", "p")):
            os.environ[chave] = valor
            self.addCleanup(os.environ.pop, chave, None)

    def _importar(self, arquivos, tamanhos):
        def baixar(token, arquivo, destino):
            os.makedirs(os.path.dirname(destino), exist_ok=True)
            with open(destino, "wb") as handle:
                handle.write(jpeg(*tamanhos[arquivo.id]))

        with mock.patch("poster.cli.drive.access_token", return_value="t"), \
                mock.patch("poster.cli.drive.folder_name", return_value="Stories"), \
                mock.patch("poster.cli.drive.list_tree", return_value=arquivos), \
                mock.patch("poster.cli.drive.download", side_effect=baixar), \
                contextlib.redirect_stdout(io.StringIO()):
            return main([
                "inbox", "--media-dir", self.midia, "--media-repo", "o/r",
                "--drafts", self.fila, "--state-file", self.estado,
                "--report", self.relatorio,
            ])

    def test_so_a_torta_ainda_avisa(self):
        """O workflow só abre a issue com código 0: a recusa sozinha não pode
        sair como "pasta sem novidade"."""
        torta = [DriveFile("torta", "cymera.jpg", "image/jpeg", 10)]

        codigo = self._importar(torta, {"torta": (2688, 4119)})

        self.assertEqual(codigo, EXIT_OK)
        with open(self.relatorio, encoding="utf-8") as handle:
            self.assertIn("2688x4119", handle.read())

    def test_torta_ja_avisada_nao_volta_a_cada_importacao(self):
        torta = [DriveFile("torta", "cymera.jpg", "image/jpeg", 10)]
        self._importar(torta, {"torta": (2688, 4119)})

        codigo = self._importar(torta, {"torta": (2688, 4119)})

        self.assertEqual(codigo, EXIT_NOTHING)

    def test_so_a_vertical_entra(self):
        arquivos = [
            DriveFile("reta1", "vertical.jpg", "image/jpeg", 10),
            DriveFile("torta", "cymera.jpg", "image/jpeg", 10),
        ]
        tamanhos = {"reta1": (108, 192), "torta": (832, 1248)}

        codigo = self._importar(arquivos, tamanhos)

        self.assertEqual(codigo, EXIT_OK)
        with open(self.fila, encoding="utf-8") as handle:
            fila = yaml.safe_load(handle)
        self.assertEqual([i["origem"] for i in fila], ["Drive: vertical.jpg"])
        with open(self.estado, encoding="utf-8") as handle:
            registro = {r["drive_id"]: r for r in json.load(handle)["imported"]}
        # A torta fica registrada como recusada: é avisada uma vez só.
        self.assertEqual(registro["reta1"]["recusado"], "")
        self.assertIn("832x1248", registro["torta"]["recusado"])
        self.assertEqual(registro["torta"]["url"], "")
        # O arquivo torto não fica no repositório de mídia para ser commitado.
        hospedados = os.listdir(os.path.join(self.midia, "inbox"))
        self.assertEqual(len(hospedados), 1)
        self.assertIn("vertical", hospedados[0])
        with open(self.relatorio, encoding="utf-8") as handle:
            self.assertIn("cymera.jpg", handle.read())


if __name__ == "__main__":
    unittest.main()
