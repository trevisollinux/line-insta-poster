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
PDF = DriveFile("pdf000xyz", "tabela.pdf", "application/pdf", 512)


class TriagemTest(unittest.TestCase):
    def test_video_longo_demais_para_story_e_recusado(self):
        longo = DriveFile("vlong", "tour.mp4", "video/mp4", 9999, duration_ms=95000)

        novos, _, recusados = triagem([longo], {})

        self.assertEqual(novos, [])
        self.assertIn("60s", recusados[0].motivo_recusa)

    def test_video_curto_passa(self):
        curto = DriveFile("vcurto", "clipe.mp4", "video/mp4", 9999, duration_ms=12000)

        novos, _, recusados = triagem([curto], {})

        self.assertEqual([a.id for a in novos], ["vcurto"])
        self.assertEqual(recusados, [])

    def test_separa_novo_repetido_e_recusado(self):
        ja = {"abc123def": Imported("abc123def", "Satchel Conhaque.jpg", "p", "u", "t")}

        novos, repetidos, recusados = triagem([FOTO, VIDEO, PDF], ja)

        self.assertEqual([a.id for a in novos], ["vid456ghi"])
        self.assertEqual([a.id for a in repetidos], ["abc123def"])
        self.assertEqual([a.id for a in recusados], ["pdf000xyz"])

    def test_png_entra_como_novo_porque_sera_convertido(self):
        novos, _, recusados = triagem([PNG], {})

        self.assertEqual([a.id for a in novos], ["png789jkl"])
        self.assertEqual(recusados, [])

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
    def test_tudo_vira_story(self):
        """Story não leva legenda, e é o formato que publica sem aprovação."""
        self.assertEqual(draft(FOTO, "https://cdn/x.jpg")["media_type"], "STORIES")
        self.assertEqual(draft(VIDEO, "https://cdn/x.mp4")["media_type"], "STORIES")

    def test_nao_carrega_legenda_nem_flag_de_preco(self):
        item = draft(FOTO, "https://cdn/x.jpg")

        self.assertNotIn("caption", item)
        self.assertNotIn("reviewed_price", item)

    def test_guarda_de_onde_veio(self):
        self.assertIn("Satchel Conhaque.jpg", draft(FOTO, "https://cdn/x.jpg")["origem"])

    def test_item_gerado_e_publicavel(self):
        """O que o inbox escreve tem de passar na validação da fila."""
        from poster.queue_file import parse_queue

        [parsed] = parse_queue([draft(FOTO, "https://cdn.example/x.jpg")])

        self.assertEqual(parsed.media_type, "STORIES")

    def test_item_de_story_nao_entra_no_feed_sem_aprovacao(self):
        """Mudar o formato para IMAGE reativa a exigência de preço."""
        from poster.queue_file import QueueError, parse_queue

        item = draft(FOTO, "https://cdn.example/x.jpg")
        item["media_type"] = "IMAGE"

        with self.assertRaises(QueueError) as ctx:
            parse_queue([item])

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

    def test_itens_anteriores_sobrevivem(self):
        """Foto ainda não publicada não pode sumir na importação seguinte."""
        caminho = os.path.join(self.dir.name, "stories.yaml")
        write_drafts([draft(FOTO, "https://cdn/a.jpg")], caminho)

        anteriores = load_drafts(caminho)
        write_drafts(anteriores + [draft(VIDEO, "https://cdn/b.mp4")], caminho)

        self.assertEqual(len(load_drafts(caminho)), 2)

    def test_arquivo_avisa_que_publica_sozinho(self):
        """Quem abrir o arquivo precisa entender o que ele faz sem perguntar."""
        caminho = os.path.join(self.dir.name, "stories.yaml")
        write_drafts([draft(FOTO, "https://cdn/a.jpg")], caminho)

        with open(caminho, encoding="utf-8") as handle:
            conteudo = handle.read()
        self.assertIn("PUBLICA sozinha", conteudo)
        self.assertIn("sem repetir", conteudo)
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

    def test_explica_o_formato_recusado(self):
        texto = report_markdown([], [PDF], [], [])

        self.assertIn("tabela.pdf", texto)
        self.assertIn("não publicável", texto)

    def test_avisa_que_publica_sozinho(self):
        texto = report_markdown([(FOTO, "https://cdn/a.jpg")], [], [], [])

        self.assertIn("publicam sozinhas", texto)
        self.assertNotIn("queue/drafts.yaml", texto)

    def test_pasta_sem_novidade(self):
        self.assertIn("Nenhuma mídia nova", report_markdown([], [], [], []))

    def test_falha_de_download_aparece(self):
        texto = report_markdown([], [], [], [("foto.jpg", "timeout")])

        self.assertIn("Falharam no download", texto)
        self.assertIn("timeout", texto)


class TipoDeConteudoTest(unittest.TestCase):
    """Sem tipo não há como perguntar qual conteúdo rendeu — e conteúdo é o
    único fator que mexeu 5x. Com tipo errado é pior: a resposta vem confiante
    e falsa."""

    def test_subpasta_vira_tipo_no_rascunho(self):
        arquivo = DriveFile(
            id="1", name="foto.jpg", mime_type="image/jpeg", pasta="Bastidor da Oficina"
        )

        item = draft(arquivo, "https://cdn/x/2026-09-20-foto.jpg")

        self.assertEqual(item["tipo"], "bastidor-da-oficina")

    def test_arquivo_da_raiz_entra_sem_tipo(self):
        # A Lélia leva tempo para se organizar; foto na raiz precisa publicar
        # igual, só não entra na comparação.
        arquivo = DriveFile(id="1", name="foto.jpg", mime_type="image/jpeg")

        item = draft(arquivo, "https://cdn/x/2026-09-20-foto.jpg")

        self.assertNotIn("tipo", item)


if __name__ == "__main__":
    unittest.main()
