"""Caixa de entrada do Drive — sem rede e sem SDK nos testes."""
import io
import json
import os
import tempfile
import unittest
import urllib.error

from poster.drive import DriveError, DriveFile, download, folder_name, list_files

PASTA = "1V5F60XSyFesdYiwSo_7JCgIV1Jiv22r_"


class FakeResposta(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def opener_json(paginas):
    """Devolve cada página em sequência e registra as URLs pedidas."""
    chamadas = []

    def abrir(requisicao, timeout=None):
        chamadas.append(requisicao.full_url)
        return FakeResposta(json.dumps(paginas[len(chamadas) - 1]).encode())

    abrir.chamadas = chamadas
    return abrir


def opener_erro(codigo):
    def abrir(requisicao, timeout=None):
        raise urllib.error.HTTPError(
            requisicao.full_url, codigo, "erro", {}, io.BytesIO(b'{"error":"nao"}')
        )

    return abrir


def arquivo(nome="foto.jpg", mime="image/jpeg", id_="f1"):
    return {"id": id_, "name": nome, "mimeType": mime, "size": "2048", "modifiedTime": "2026-09-19T10:00:00Z"}


class ListFilesTest(unittest.TestCase):
    def test_lista_a_pasta(self):
        abrir = opener_json([{"files": [arquivo(), arquivo("video.mp4", "video/mp4", "f2")]}])

        arquivos = list_files("TOKEN", PASTA, opener=abrir)

        self.assertEqual([a.name for a in arquivos], ["foto.jpg", "video.mp4"])
        self.assertEqual(arquivos[0].size, 2048)

    def test_filtra_lixeira_e_pede_a_pasta_certa(self):
        abrir = opener_json([{"files": []}])

        list_files("TOKEN", PASTA, opener=abrir)

        url = abrir.chamadas[0]
        self.assertIn(PASTA, url)
        self.assertIn("trashed", url)

    def test_pagina_ate_o_fim(self):
        abrir = opener_json(
            [
                {"files": [arquivo(id_="f1")], "nextPageToken": "P2"},
                {"files": [arquivo(id_="f2")]},
            ]
        )

        arquivos = list_files("TOKEN", PASTA, opener=abrir)

        self.assertEqual(len(arquivos), 2)
        self.assertIn("pageToken=P2", abrir.chamadas[1])

    def test_403_explica_o_compartilhamento(self):
        """É o erro mais provável e o mais confuso: pasta não compartilhada."""
        with self.assertRaises(DriveError) as ctx:
            list_files("TOKEN", PASTA, opener=opener_erro(403))

        self.assertIn("conta de serviço", str(ctx.exception))

    def test_404_tambem_aponta_o_compartilhamento(self):
        with self.assertRaises(DriveError) as ctx:
            list_files("TOKEN", PASTA, opener=opener_erro(404))

        self.assertIn("Leitor", str(ctx.exception))


class TipoDeArquivoTest(unittest.TestCase):
    def test_jpeg_e_mp4_sao_publicaveis(self):
        self.assertTrue(DriveFile("1", "a.jpg", "image/jpeg").publicavel)
        self.assertTrue(DriveFile("2", "b.mp4", "video/mp4").publicavel)

    def test_png_e_recusado_com_instrucao(self):
        png = DriveFile("3", "c.png", "image/png")

        self.assertFalse(png.publicavel)
        self.assertIn("JPEG", png.motivo_recusa)

    def test_pdf_e_recusado(self):
        pdf = DriveFile("4", "tabela.pdf", "application/pdf")

        self.assertFalse(pdf.publicavel)
        self.assertIn("não publicável", pdf.motivo_recusa)

    def test_extensao_vem_do_tipo_e_nao_do_nome(self):
        """Nome no celular às vezes vem sem extensão ou com a errada."""
        self.assertEqual(DriveFile("5", "sem_extensao", "image/jpeg").extension, ".jpg")


class DownloadTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.destino = os.path.join(self.dir.name, "sub", "foto.jpg")
        self.arquivo = DriveFile("f1", "foto.jpg", "image/jpeg")

    def opener_bytes(self, conteudo):
        def abrir(requisicao, timeout=None):
            self.url = requisicao.full_url
            return FakeResposta(conteudo)

        return abrir

    def test_baixa_e_grava(self):
        tamanho = download("TOKEN", self.arquivo, self.destino, opener=self.opener_bytes(b"x" * 500))

        self.assertEqual(tamanho, 500)
        self.assertTrue(os.path.exists(self.destino))
        self.assertIn("alt=media", self.url)

    def test_arquivo_vazio_nao_e_promovido(self):
        with self.assertRaises(DriveError):
            download("TOKEN", self.arquivo, self.destino, opener=self.opener_bytes(b""))

        self.assertFalse(os.path.exists(self.destino))

    def test_grande_demais_nao_e_promovido(self):
        with self.assertRaises(DriveError) as ctx:
            download(
                "TOKEN",
                self.arquivo,
                self.destino,
                opener=self.opener_bytes(b"x" * 5000),
                max_bytes=1000,
            )

        self.assertIn("grande demais", str(ctx.exception))
        self.assertFalse(os.path.exists(self.destino))

    def test_nao_deixa_parcial(self):
        with self.assertRaises(DriveError):
            download("TOKEN", self.arquivo, self.destino, opener=self.opener_bytes(b""))

        self.assertFalse(os.path.exists(f"{self.destino}.parcial"))


if __name__ == "__main__":
    unittest.main()


class FolderNameTest(unittest.TestCase):
    """Sem esta checagem, pasta não compartilhada parece pasta vazia."""

    def test_devolve_o_nome_da_pasta(self):
        abrir = opener_json([{"id": PASTA, "name": "Instagram — a postar"}])

        self.assertEqual(folder_name("TOKEN", PASTA, opener=abrir), "Instagram — a postar")

    def test_sem_acesso_falha_em_vez_de_fingir_pasta_vazia(self):
        with self.assertRaises(DriveError) as ctx:
            folder_name("TOKEN", PASTA, opener=opener_erro(404))

        self.assertIn("compartilhada", str(ctx.exception))
