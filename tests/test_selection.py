"""Elegibilidade e sorteio: o que já saiu não volta sem prazo explícito."""
import random
import unittest
from datetime import datetime, timedelta, timezone

from tests.support import item

from poster.queue_file import parse_queue
from poster.selection import select_next
from poster.state import PublishedEntry

AGORA = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)


def publicado(item_id: str, quando: datetime) -> PublishedEntry:
    return PublishedEntry(
        item_id=item_id,
        media_id="media-1",
        container_id="container-1",
        media_type="IMAGE",
        published_at=quando.isoformat(timespec="seconds"),
    )


class MediaTypeFilterTest(unittest.TestCase):
    """O filtro por formato é o que dá três workflows sem três cópias da lógica."""

    def fila(self):
        reels = item(id="reels", media_type="REELS", url="https://x/v.mp4")
        stories = item(id="stories", media_type="STORIES", caption="")
        imagem = item(id="imagem")
        return parse_queue([reels, stories, imagem])

    def test_publica_so_o_formato_pedido(self):
        selecao = select_next(self.fila(), [], mode="order", media_types=("REELS",))

        self.assertEqual(selecao.item.id, "reels")
        self.assertEqual([i.id for i in selecao.eligible], ["reels"])

    def test_formato_aceita_mais_de_um(self):
        selecao = select_next(
            self.fila(), [], mode="order", media_types=("STORIES", "IMAGE")
        )

        self.assertEqual([i.id for i in selecao.eligible], ["stories", "imagem"])

    def test_descartado_por_formato_aparece_no_relato(self):
        selecao = select_next(self.fila(), [], mode="order", media_types=("REELS",))

        motivos = {s.item_id: s.reason for s in selecao.skipped}
        self.assertIn("fora do formato pedido", motivos["stories"])

    def test_sem_filtro_tudo_continua_elegivel(self):
        selecao = select_next(self.fila(), [], mode="order")

        self.assertEqual(len(selecao.eligible), 3)

    def test_formato_sem_item_nao_publica_nada(self):
        selecao = select_next(self.fila(), [], mode="order", media_types=("CAROUSEL",))

        self.assertIsNone(selecao.item)


class SelectionTest(unittest.TestCase):
    def test_item_ja_publicado_nao_volta(self):
        items = parse_queue([item(id="a"), item(id="b")])
        estado = [publicado("a", AGORA - timedelta(days=3))]

        selecao = select_next(items, estado, mode="order", now=AGORA)

        self.assertEqual(selecao.item.id, "b")
        self.assertEqual([s.item_id for s in selecao.skipped], ["a"])

    def test_repeat_after_days_ainda_no_prazo_continua_fora(self):
        items = parse_queue([item(id="a", repeat_after_days=30)])
        estado = [publicado("a", AGORA - timedelta(days=10))]

        selecao = select_next(items, estado, mode="order", now=AGORA)

        self.assertIsNone(selecao.item)
        self.assertIn("repete só a partir de", selecao.skipped[0].reason)

    def test_repeat_after_days_vencido_libera_o_item(self):
        items = parse_queue([item(id="a", repeat_after_days=30)])
        estado = [publicado("a", AGORA - timedelta(days=31))]

        selecao = select_next(items, estado, mode="order", now=AGORA)

        self.assertEqual(selecao.item.id, "a")

    def test_last_published_da_fila_tambem_conta(self):
        items = parse_queue([item(id="a", last_published="2026-09-10T10:00:00Z")])

        selecao = select_next(items, [], mode="order", now=AGORA)

        self.assertIsNone(selecao.item)

    def test_fila_toda_publicada_devolve_nada(self):
        items = parse_queue([item(id="a")])
        estado = [publicado("a", AGORA - timedelta(days=1))]

        selecao = select_next(items, estado, now=AGORA)

        self.assertIsNone(selecao.item)
        self.assertEqual(selecao.eligible, [])

    def test_sorteio_respeita_o_peso(self):
        items = parse_queue([item(id="leve", weight=1), item(id="pesado", weight=9)])
        rng = random.Random(7)

        escolhas = [
            select_next(items, [], now=AGORA, rng=rng).item.id for _ in range(400)
        ]

        pesados = escolhas.count("pesado")
        self.assertGreater(pesados, 300, f"peso 9x deveria dominar, veio {pesados}/400")
        self.assertGreater(escolhas.count("leve"), 0, "peso 1 nunca deveria zerar")

    def test_modo_order_e_deterministico(self):
        items = parse_queue([item(id="a"), item(id="b")])

        for _ in range(5):
            self.assertEqual(select_next(items, [], mode="order", now=AGORA).item.id, "a")

    def test_modo_invalido_falha_cedo(self):
        with self.assertRaises(ValueError):
            select_next(parse_queue([item()]), [], mode="aleatorio")


if __name__ == "__main__":
    unittest.main()
