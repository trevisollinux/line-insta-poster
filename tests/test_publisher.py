"""Fluxo de publicação — inclusive os caminhos em que nada pode ser marcado."""
import unittest
from datetime import datetime, timezone

from tests.support import FakeClient, item

from poster.publisher import (
    PublishError,
    container_params,
    create_container,
    publish_item,
    publishing_limit,
    wait_for_container,
)
from poster.queue_file import parse_queue

IG = "17841000000000000"
AGORA = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)

LIMITE_OK = {"data": [{"quota_usage": 3, "config": {"quota_total": 25}}]}


def um(**kwargs):
    return parse_queue([item(**kwargs)])[0]


def cliente_feliz(sobrescreve=None):
    respostas = {
        ("GET", f"{IG}/content_publishing_limit"): LIMITE_OK,
        ("POST", f"{IG}/media"): {"id": "container-1"},
        ("GET", "container-1"): {"status_code": "FINISHED"},
        ("POST", f"{IG}/media_publish"): {"id": "media-9"},
        ("GET", "media-9"): {"permalink": "https://instagram.com/p/abc"},
    }
    respostas.update(sobrescreve or {})
    return FakeClient(respostas)


class ContainerParamsTest(unittest.TestCase):
    def test_imagem_usa_image_url_e_caption(self):
        params = container_params(um())

        self.assertEqual(params["image_url"], "https://media.example/foto.jpg")
        self.assertEqual(params["caption"], "legenda")
        self.assertNotIn("media_type", params)

    def test_reels_usa_video_url_e_share_to_feed(self):
        params = container_params(
            um(media_type="REELS", url="https://media.example/v.mp4", share_to_feed=False)
        )

        self.assertEqual(params["media_type"], "REELS")
        self.assertEqual(params["video_url"], "https://media.example/v.mp4")
        self.assertEqual(params["share_to_feed"], "false")

    def test_stories_em_video_usa_video_url_e_nao_manda_caption(self):
        params = container_params(
            um(media_type="STORIES", url="https://media.example/v.mp4", caption="")
        )

        self.assertEqual(params["media_type"], "STORIES")
        self.assertIn("video_url", params)
        self.assertNotIn("caption", params)


class CreateContainerTest(unittest.TestCase):
    def test_carrossel_cria_filhos_e_depois_o_pai(self):
        client = FakeClient(
            {
                ("POST", f"{IG}/media"): [
                    {"id": "filho-1"},
                    {"id": "filho-2"},
                    {"id": "pai-1"},
                ]
            }
        )
        carrossel = parse_queue(
            [
                {
                    "id": "c",
                    "media_type": "CAROUSEL",
                    "urls": ["https://media.example/1.jpg", "https://media.example/2.mp4"],
                    "caption": "linha completa",
                    "reviewed_price": True,
                }
            ]
        )[0]

        container_id, filhos = create_container(client, IG, carrossel)

        self.assertEqual(container_id, "pai-1")
        self.assertEqual(filhos, ["filho-1", "filho-2"])
        primeiro, segundo, pai = [c[2] for c in client.chamadas]
        self.assertEqual(primeiro["is_carousel_item"], "true")
        self.assertEqual(segundo["media_type"], "VIDEO")  # .mp4 vira filho de vídeo
        self.assertEqual(pai["children"], "filho-1,filho-2")
        self.assertEqual(pai["caption"], "linha completa")


class WaitForContainerTest(unittest.TestCase):
    def test_espera_ate_finished(self):
        client = FakeClient(
            {
                ("GET", "container-1"): [
                    {"status_code": "IN_PROGRESS"},
                    {"status_code": "IN_PROGRESS"},
                    {"status_code": "FINISHED"},
                ]
            }
        )
        dormidas = []

        status = wait_for_container(
            client,
            "container-1",
            interval=60,
            timeout=300,
            sleep=dormidas.append,
            monotonic=lambda: 0.0,
        )

        self.assertEqual(status, "FINISHED")
        self.assertEqual(dormidas, [60, 60])

    def test_status_error_aborta(self):
        client = FakeClient({("GET", "c"): {"status_code": "ERROR", "status": "mídia inválida"}})

        with self.assertRaises(PublishError) as ctx:
            wait_for_container(client, "c", sleep=lambda _: None, monotonic=lambda: 0.0)

        self.assertIn("ERROR", str(ctx.exception))

    def test_expired_aborta(self):
        client = FakeClient({("GET", "c"): {"status_code": "EXPIRED"}})

        with self.assertRaises(PublishError):
            wait_for_container(client, "c", sleep=lambda _: None, monotonic=lambda: 0.0)

    def test_estouro_de_tempo_aborta_sem_publicar(self):
        client = FakeClient({("GET", "c"): {"status_code": "IN_PROGRESS"}})
        relogio = iter([0.0, 60.0, 120.0, 180.0, 240.0, 300.0, 360.0])

        with self.assertRaises(PublishError) as ctx:
            wait_for_container(
                client,
                "c",
                interval=60,
                timeout=300,
                sleep=lambda _: None,
                monotonic=lambda: next(relogio),
            )

        self.assertIn("abortado sem publicar", str(ctx.exception))


class PublishItemTest(unittest.TestCase):
    def test_fluxo_feliz_na_ordem_certa(self):
        client = cliente_feliz()

        resultado = publish_item(
            client, IG, um(), sleep=lambda _: None, monotonic=lambda: 0.0, now=lambda: AGORA
        )

        self.assertEqual(resultado.media_id, "media-9")
        self.assertEqual(resultado.container_id, "container-1")
        self.assertEqual(resultado.permalink, "https://instagram.com/p/abc")
        self.assertEqual(
            client.paths(),
            [
                f"{IG}/content_publishing_limit",
                f"{IG}/media",
                "container-1",
                f"{IG}/media_publish",
                "media-9",
            ],
        )

    def test_publish_usa_o_creation_id_do_container(self):
        client = cliente_feliz()

        publish_item(client, IG, um(), sleep=lambda _: None, monotonic=lambda: 0.0)

        publicacao = [c for c in client.chamadas if c[1] == f"{IG}/media_publish"][0]
        self.assertEqual(publicacao[2], {"creation_id": "container-1"})

    def test_entrada_de_estado_sai_do_resultado(self):
        client = cliente_feliz()

        resultado = publish_item(
            client, IG, um(), sleep=lambda _: None, monotonic=lambda: 0.0, now=lambda: AGORA
        )
        entrada = resultado.to_entry()

        self.assertEqual(entrada.item_id, "item-1")
        self.assertEqual(entrada.media_id, "media-9")
        self.assertEqual(entrada.published_at, "2026-09-16T12:00:00+00:00")

    def test_container_com_erro_nao_chega_a_publicar(self):
        client = cliente_feliz({("GET", "container-1"): {"status_code": "ERROR"}})

        with self.assertRaises(PublishError):
            publish_item(client, IG, um(), sleep=lambda _: None, monotonic=lambda: 0.0)

        self.assertNotIn(f"{IG}/media_publish", client.paths())

    def test_limite_de_24h_estourado_bloqueia_a_publicacao(self):
        client = cliente_feliz(
            {
                ("GET", f"{IG}/content_publishing_limit"): {
                    "data": [{"quota_usage": 25, "config": {"quota_total": 25}}]
                }
            }
        )

        with self.assertRaises(PublishError) as ctx:
            publish_item(client, IG, um(), sleep=lambda _: None, monotonic=lambda: 0.0)

        self.assertIn("limite de publicação", str(ctx.exception))
        self.assertNotIn(f"{IG}/media", client.paths())

    def test_permalink_indisponivel_nao_derruba_a_publicacao(self):
        client = cliente_feliz({("GET", "media-9"): {}})

        resultado = publish_item(
            client, IG, um(), sleep=lambda _: None, monotonic=lambda: 0.0
        )

        self.assertEqual(resultado.media_id, "media-9")
        self.assertIsNone(resultado.permalink)


class PublishingLimitTest(unittest.TestCase):
    def test_le_uso_e_total(self):
        client = FakeClient({("GET", f"{IG}/content_publishing_limit"): LIMITE_OK})

        self.assertEqual(publishing_limit(client, IG), (3, 25))

    def test_resposta_vazia_vira_desconhecido(self):
        client = FakeClient({("GET", f"{IG}/content_publishing_limit"): {"data": []}})

        self.assertEqual(publishing_limit(client, IG), (None, None))


if __name__ == "__main__":
    unittest.main()
