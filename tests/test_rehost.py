"""Rehospedagem: buscar a URL na hora, e nunca promover download ruim."""
import io
import os
import tempfile
import unittest

from tests.support import FakeClient

from poster.rehost import (
    rehost_candidates,
    RehostError,
    download,
    media_source,
    public_url,
    rehost,
)

MEDIA_ID = "18152138197469599"


class FakeResposta(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def opener_com(conteudo: bytes):
    def abrir(url, timeout=None):
        return FakeResposta(conteudo)

    return abrir


class MediaSourceTest(unittest.TestCase):
    def test_busca_a_url_na_hora(self):
        client = FakeClient(
            {
                ("GET", MEDIA_ID): {
                    "media_url": "https://cdn.example/v.mp4",
                    "media_type": "VIDEO",
                    "media_product_type": "REELS",
                }
            }
        )

        origem = media_source(client, MEDIA_ID)

        self.assertEqual(origem.url, "https://cdn.example/v.mp4")
        self.assertTrue(origem.is_video)
        self.assertEqual(origem.extension, ".mp4")
        self.assertEqual(client.chamadas[0][2]["fields"], "media_url,media_type,media_product_type")

    def test_imagem_vira_jpg(self):
        client = FakeClient(
            {("GET", MEDIA_ID): {"media_url": "https://cdn.example/f.webp", "media_type": "IMAGE"}}
        )

        self.assertEqual(media_source(client, MEDIA_ID).extension, ".jpg")

    def test_post_sem_media_url_explica_o_motivo(self):
        client = FakeClient({("GET", MEDIA_ID): {"media_type": "IMAGE"}})

        with self.assertRaises(RehostError) as ctx:
            media_source(client, MEDIA_ID)

        self.assertIn("Shopping", str(ctx.exception))


class DownloadTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.destino = os.path.join(self.dir.name, "sub", "midia.mp4")

    def test_grava_e_devolve_tamanho(self):
        tamanho = download("https://x/y.mp4", self.destino, opener=opener_com(b"x" * 2048))

        self.assertEqual(tamanho, 2048)
        self.assertTrue(os.path.exists(self.destino))

    def test_download_vazio_nao_vira_arquivo(self):
        with self.assertRaises(RehostError):
            download("https://x/y.mp4", self.destino, opener=opener_com(b""))

        self.assertFalse(os.path.exists(self.destino))

    def test_arquivo_grande_demais_nao_vira_arquivo(self):
        with self.assertRaises(RehostError) as ctx:
            download(
                "https://x/y.mp4",
                self.destino,
                opener=opener_com(b"x" * 5000),
                max_bytes=1000,
            )

        self.assertIn("bucket", str(ctx.exception))
        self.assertFalse(os.path.exists(self.destino), "mídia grande não pode ser promovida")

    def test_nao_deixa_arquivo_parcial_para_tras(self):
        with self.assertRaises(RehostError):
            download("https://x/y.mp4", self.destino, opener=opener_com(b""))

        self.assertFalse(os.path.exists(f"{self.destino}.parcial"))

    def test_falha_de_rede_vira_rehost_error(self):
        def abrir(url, timeout=None):
            raise OSError("conexão recusada")

        with self.assertRaises(RehostError) as ctx:
            download("https://x/y.mp4", self.destino, opener=abrir)

        self.assertIn("download falhou", str(ctx.exception))


class PublicUrlTest(unittest.TestCase):
    def test_usa_o_cdn_que_serve_com_o_tipo_certo(self):
        """raw.githubusercontent serve octet-stream com nosniff e a Meta recusa."""
        url = public_url("dono/repo", "main", "media/foto.jpg")

        self.assertEqual(url, "https://cdn.jsdelivr.net/gh/dono/repo@main/media/foto.jpg")
        self.assertNotIn("raw.githubusercontent", url)


class RehostTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.client = FakeClient(
            {
                ("GET", MEDIA_ID): {
                    "media_url": "https://cdn.example/v.mp4",
                    "media_type": "VIDEO",
                    "media_product_type": "REELS",
                }
            }
        )

    def test_fluxo_completo(self):
        caminho, url, tamanho = rehost(
            self.client,
            MEDIA_ID,
            nome="line-baguete",
            diretorio=self.dir.name,
            repo="dono/repo",
            opener=opener_com(b"video"),
        )

        self.assertTrue(caminho.endswith("line-baguete.mp4"), caminho)
        self.assertTrue(url.startswith("https://cdn.jsdelivr.net/gh/dono/repo@main/"))
        self.assertEqual(tamanho, 5)

    def test_sem_nome_usa_o_id(self):
        caminho, _, _ = rehost(
            self.client, MEDIA_ID, diretorio=self.dir.name, opener=opener_com(b"v")
        )

        self.assertTrue(caminho.endswith(f"{MEDIA_ID}.mp4"), caminho)

    def test_sem_repo_nao_inventa_url(self):
        _, url, _ = rehost(
            self.client, MEDIA_ID, diretorio=self.dir.name, opener=opener_com(b"v")
        )

        self.assertEqual(url, "")


if __name__ == "__main__":
    unittest.main()


class RehostCandidatesTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def candidatos(self):
        return [
            {"id": "2026-05-23-abc", "source_media_id": "111", "url": ""},
            {"id": "2026-01-13-def", "source_media_id": "222", "url": ""},
        ]

    def test_preenche_url_de_cada_candidato(self):
        client = FakeClient(
            {
                ("GET", "111"): {"media_url": "https://cdn/1.mp4", "media_type": "VIDEO"},
                ("GET", "222"): {"media_url": "https://cdn/2.jpg", "media_type": "IMAGE"},
            }
        )

        prontos, falhas = rehost_candidates(
            client,
            self.candidatos(),
            diretorio=self.dir.name,
            repo="dono/repo",
            opener=opener_com(b"bytes"),
        )

        self.assertEqual(falhas, [])
        self.assertTrue(prontos[0]["url"].endswith("2026-05-23-abc.mp4"))
        self.assertTrue(prontos[1]["url"].endswith("2026-01-13-def.jpg"))

    def test_falha_de_um_nao_derruba_os_outros(self):
        """Post de Shopping não expõe media_url — 1 faltando é melhor que 15 perdidos."""
        client = FakeClient(
            {
                ("GET", "111"): {"media_type": "IMAGE"},  # sem media_url
                ("GET", "222"): {"media_url": "https://cdn/2.jpg", "media_type": "IMAGE"},
            }
        )

        prontos, falhas = rehost_candidates(
            client,
            self.candidatos(),
            diretorio=self.dir.name,
            repo="dono/repo",
            opener=opener_com(b"bytes"),
        )

        self.assertEqual(len(prontos), 2)
        self.assertEqual(prontos[0]["url"], "", "o que falhou fica sem url, não com url errada")
        self.assertTrue(prontos[1]["url"])
        self.assertEqual([f[0] for f in falhas], ["111"])
