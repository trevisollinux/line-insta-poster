"""A fila é o portão de qualidade: item incompleto não pode virar post."""
import unittest

from tests.support import item

from poster.queue_file import QueueError, parse_queue


class QueueValidationTest(unittest.TestCase):
    def test_item_valido_vira_queue_item(self):
        [parsed] = parse_queue([item(weight=3, repeat_after_days=30)])

        self.assertEqual(parsed.id, "item-1")
        self.assertEqual(parsed.media_type, "IMAGE")
        self.assertEqual(parsed.urls, ("https://media.example/foto.jpg",))
        self.assertEqual(parsed.weight, 3.0)
        self.assertEqual(parsed.repeat_after_days, 30)
        self.assertTrue(parsed.reviewed_price)

    def test_stories_dispensa_reviewed_price(self):
        """A flag protege preço na legenda, e STORIES não tem legenda."""
        payload = item(media_type="STORIES", caption="")
        payload.pop("reviewed_price")

        [parsed] = parse_queue([payload])

        self.assertEqual(parsed.media_type, "STORIES")
        self.assertFalse(parsed.reviewed_price)

    def test_legenda_com_preco_continua_exigindo(self):
        for formato, extra in (
            ("IMAGE", {}),
            ("REELS", {"url": "https://media.example/v.mp4"}),
        ):
            with self.subTest(formato=formato):
                payload = item(media_type=formato, caption="Bolsa R$ 890", **extra)
                payload.pop("reviewed_price")

                with self.assertRaises(QueueError) as ctx:
                    parse_queue([payload])

                self.assertIn("reviewed_price", str(ctx.exception))

    def test_legenda_sem_preco_dispensa(self):
        """Nem todo post traz preço — e sem preço não há o que conferir.

        Exigir a marca sempre transforma a conferência em ritual, e ritual
        repetido vira hábito: a pessoa marca sem olhar, inclusive nos posts que
        realmente têm preço. A trava vale mais aplicada só onde protege.
        """
        payload = item(caption="Juniper 3 em 1 🥰")
        payload.pop("reviewed_price")

        [parsed] = parse_queue([payload])

        self.assertFalse(parsed.reviewed_price)

    def test_o_que_conta_como_preco_na_legenda(self):
        """O gatilho é o NÚMERO, não o assunto.

        O que envelhece é o valor. "Valor no direct" e "consulte o preço" não
        envelhecem — e são as legendas mais comuns desta loja, que nem sempre
        publica preço. Uma trava que dispara no caso mais frequente vira
        ritual, e ritual vira hábito de marcar sem olhar.
        """
        for legenda in (
            "R$ 890",
            "890,00 no pix",
            "6x de 148",
            "preço: 890",
            "por 890",
            "a partir de 690",
            "890 reais",
        ):
            with self.subTest(exige=legenda):
                payload = item(caption=legenda)
                payload.pop("reviewed_price")
                with self.assertRaises(QueueError):
                    parse_queue([payload])

        for legenda in (
            "valor no direct",
            "consulte o preço na bio",
            "preço no direct 💬",
            "à vista com desconto",
            "Juniper 3 em 1 🥰",
            "#readytogo",
            "12 meses de garantia",
        ):
            with self.subTest(livre=legenda):
                payload = item(caption=legenda)
                payload.pop("reviewed_price")
                parse_queue([payload])

    def test_sem_reviewed_price_a_fila_inteira_falha(self):
        with self.assertRaises(QueueError) as ctx:
            parse_queue([item(reviewed_price=False, caption="Bolsa R$ 890")])

        self.assertIn("reviewed_price", str(ctx.exception))

    def test_reviewed_price_ausente_tambem_falha(self):
        payload = item(caption="Bolsa R$ 890")
        payload.pop("reviewed_price")

        with self.assertRaises(QueueError):
            parse_queue([payload])

    def test_url_precisa_ser_https(self):
        with self.assertRaises(QueueError) as ctx:
            parse_queue([item(url="http://media.example/foto.jpg")])

        self.assertIn("https", str(ctx.exception))

    def test_reels_exige_video(self):
        with self.assertRaises(QueueError) as ctx:
            parse_queue([item(media_type="REELS", url="https://media.example/a.jpg")])

        self.assertIn("REELS precisa de vídeo", str(ctx.exception))

    def test_image_recusa_arquivo_de_video(self):
        with self.assertRaises(QueueError):
            parse_queue([item(url="https://media.example/a.mp4")])

    def test_stories_nao_aceita_caption(self):
        with self.assertRaises(QueueError) as ctx:
            parse_queue([item(media_type="STORIES", caption="oi")])

        self.assertIn("STORIES não aceita caption", str(ctx.exception))

    def test_carrossel_precisa_de_duas_a_dez_midias(self):
        uma_so = item(media_type="CAROUSEL", urls=["https://media.example/1.jpg"])
        uma_so.pop("url")

        with self.assertRaises(QueueError) as ctx:
            parse_queue([uma_so])

        self.assertIn("CAROUSEL precisa de 2 a 10 urls", str(ctx.exception))

    def test_carrossel_aceita_imagens_e_videos(self):
        payload = item(
            media_type="CAROUSEL",
            urls=["https://media.example/1.jpg", "https://media.example/2.mp4"],
        )
        payload.pop("url")

        [parsed] = parse_queue([payload])

        self.assertEqual(len(parsed.urls), 2)

    def test_id_duplicado_e_erro(self):
        with self.assertRaises(QueueError) as ctx:
            parse_queue([item(), item()])

        self.assertIn("id duplicado", str(ctx.exception))

    def test_caption_longa_demais(self):
        with self.assertRaises(QueueError) as ctx:
            parse_queue([item(caption="x" * 2201)])

        self.assertIn("2200", str(ctx.exception))

    def test_limite_de_hashtags(self):
        caption = " ".join(f"#tag{i}" for i in range(31))

        with self.assertRaises(QueueError) as ctx:
            parse_queue([item(caption=caption)])

        self.assertIn("hashtags", str(ctx.exception))

    def test_weight_precisa_ser_positivo(self):
        with self.assertRaises(QueueError):
            parse_queue([item(weight=0)])

    def test_erro_lista_todos_os_problemas_de_uma_vez(self):
        with self.assertRaises(QueueError) as ctx:
            parse_queue([
                item(
                    id="a",
                    reviewed_price=False,
                    caption="Bolsa R$ 890",
                    url="http://x/a.jpg",
                )
            ])

        mensagem = str(ctx.exception)
        self.assertIn("reviewed_price", mensagem)
        self.assertIn("https", mensagem)

    def test_fila_vazia_e_valida(self):
        self.assertEqual(parse_queue([]), [])
        self.assertEqual(parse_queue({"posts": []}), [])


if __name__ == "__main__":
    unittest.main()
