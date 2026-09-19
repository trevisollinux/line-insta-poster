"""Importação da pasta do Drive: triagem, nomes e a trava do reviewed_price."""
import json
import os
import tempfile
import unittest

import yaml

from poster.drive import DriveFile
from poster.inbox import (
    Imported,
    draft,
    load_drafts,
    load_imported,
    media_filename,
    media_public_url,
    report_markdown,
    save_imported,
    slugify,
    triagem,
    write_drafts,
)

FOTO = DriveFile("abc123def", "Satchel Conhaque.jpg", "image/jpeg", 2048)
VIDEO = DriveFile("vid456ghi", "tour bolsa.mp4", "video/mp4", 4096)
PNG = DriveFile("png789jkl", "necessaire.png", "image/png", 1024)


class TriagemTest(unittest.TestCase):
    def test_separa_novo_repetido_e_recusado(self):
        ja = {"abc123def": Imported("abc123def", "Satchel Conhaque.jpg", "p", "u", "t")}

        novos, repetidos, recusados = triagem([FOTO, VIDEO, PNG], ja)

        self.assertEqual([a.id for a in novos], ["vid456ghi"])
        self.assertEqual([a.id for a in repetidos], ["abc123def"])
        self.assertEqual([a.id for a in recusados], ["png789jkl"])

    def test_pasta_vazia(self):
        self.assertEqual(triagem([], {}), ([], [], []))

    def test_sem_historico_tudo_publicavel_e_novo(self):
        novos, repetidos, _ = triagem([FOTO, VIDEO], {})

        self.assertEqual(len(novos), 2)
        self.assertEqual(repetidos, [])


class NomeDeArquivoTest(unittest.TestCase):
    def test_nome_legivel_com_data_e_pedaco_do_id(self):
        nome = media_filename(FOTO, hoje="2026-09-19")

        self.assertEqual(nome, "2026-09-19-satchel-conhaque-abc123.jpg")

    def test_acento_e_espaco_viram_slug(self):
        arquivo = DriveFile("id1234", "Bolsa Ação Café.jpg", "image/jpeg")

        self.assertEqual(media_filename(arquivo, hoje="2026-09-19"), "2026-09-19-bolsa-a-o-caf-id1234.jpg")

    def test_nome_vazio_nao_gera_arquivo_sem_nome(self):
        arquivo = DriveFile("id1234", "!!!.jpg", "image/jpeg")

        self.assertIn("midia", media_filename(arquivo, hoje="2026-09-19"))

    def test_slug_nao_estoura_o_tamanho(self):
        self.assertLessEqual(len(slugify("a" * 200)), 60)

    def test_extensao_vem_do_tipo(self):
        """Foto de celular chega com nome sem extensão."""
        arquivo = DriveFile("id1234", "IMG_0042", "image/jpeg")

        self.assertTrue(media_filename(arquivo, hoje="2026-09-19").endswith(".jpg"))


class DraftTest(unittest.TestCase):
    def test_rascunho_nasce_travado(self):
        item = draft(FOTO, "https://cdn/x.jpg")

        self.assertFalse(item["reviewed_price"], "rascunho não pode ir ao ar sozinho")
        self.assertEqual(item["caption"], "", "legenda é decisão humana")

    def test_video_vira_reels_e_foto_vira_image(self):
        self.assertEqual(draft(VIDEO, "https://cdn/x.mp4")["media_type"], "REELS")
        self.assertEqual(draft(FOTO, "https://cdn/x.jpg")["media_type"], "IMAGE")

    def test_guarda_de_onde_veio(self):
        self.assertIn("Satchel Conhaque.jpg", draft(FOTO, "https://cdn/x.jpg")["origem"])

    def test_rascunho_e_recusado_pela_validacao_da_fila(self):
        """A trava não é decorativa: a fila recusa mesmo."""
        from poster.queue_file import QueueError, parse_queue

        with self.assertRaises(QueueError) as ctx:
            parse_queue([draft(FOTO, "https://cdn.example/x.jpg")])

        self.assertIn("reviewed_price", str(ctx.exception))


class ArquivosTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def test_ida_e_volta_do_estado(self):
        caminho = os.path.join(self.dir.name, "inbox.json")
        registros = {"abc": Imported("abc", "foto.jpg", "inbox/a.jpg", "https://cdn/a.jpg", "2026-09-19T10:00:00+00:00")}

        save_imported(registros, caminho)
        lido = load_imported(caminho)

        self.assertEqual(lido["abc"].name, "foto.jpg")
        with open(caminho, encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["version"], 1)

    def test_estado_ausente_vira_vazio(self):
        self.assertEqual(load_imported(os.path.join(self.dir.name, "nao_existe.json")), {})

    def test_rascunhos_anteriores_sobrevivem(self):
        caminho = os.path.join(self.dir.name, "drafts.yaml")
        write_drafts([draft(FOTO, "https://cdn/a.jpg")], caminho)

        anteriores = load_drafts(caminho)
        write_drafts(anteriores + [draft(VIDEO, "https://cdn/b.mp4")], caminho)

        self.assertEqual(len(load_drafts(caminho)), 2)

    def test_arquivo_de_rascunhos_avisa_que_nao_e_a_fila(self):
        caminho = os.path.join(self.dir.name, "drafts.yaml")
        write_drafts([draft(FOTO, "https://cdn/a.jpg")], caminho)

        with open(caminho, encoding="utf-8") as handle:
            conteudo = handle.read()
        self.assertIn("NÃO é a fila", conteudo)
        self.assertEqual(len(yaml.safe_load(conteudo)), 1)


class UrlTest(unittest.TestCase):
    def test_aponta_para_o_repositorio_de_midia(self):
        url = media_public_url("trevisollinux/line-store-media", "main", "2026-09-19-foto-abc.jpg")

        self.assertEqual(
            url,
            "https://cdn.jsdelivr.net/gh/trevisollinux/line-store-media@main/inbox/2026-09-19-foto-abc.jpg",
        )


class ReportTest(unittest.TestCase):
    def test_lista_importados_com_link(self):
        texto = report_markdown([(FOTO, "https://cdn/a.jpg")], [], [], [])

        self.assertIn("Satchel Conhaque.jpg", texto)
        self.assertIn("https://cdn/a.jpg", texto)

    def test_explica_o_png_recusado(self):
        texto = report_markdown([], [PNG], [], [])

        self.assertIn("necessaire.png", texto)
        self.assertIn("JPEG", texto)

    def test_pasta_sem_novidade(self):
        self.assertIn("Nenhuma mídia nova", report_markdown([], [], [], []))

    def test_falha_de_download_aparece(self):
        texto = report_markdown([], [], [], [("foto.jpg", "timeout")])

        self.assertIn("Falharam no download", texto)
        self.assertIn("timeout", texto)


if __name__ == "__main__":
    unittest.main()
