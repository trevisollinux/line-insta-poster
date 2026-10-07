"""Repetição de stories: só tapa buraco, respeita o intervalo e repete o que
levou gente ao perfil."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from tests.support import item

from poster.cli import main
from poster.queue_file import parse_queue
from poster.repeticao import notas_por_item, selecionar
from poster.state import PublishedEntry

AGORA = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)


def story(item_id: str) -> dict:
    return item(id=item_id, media_type="STORIES", caption="",
                url=f"https://media.example/{item_id}.jpg")


def saiu(item_id: str, dias_atras: float, media_id: str = "") -> PublishedEntry:
    quando = AGORA - timedelta(days=dias_atras)
    return PublishedEntry(
        item_id=item_id,
        media_id=media_id or f"m-{item_id}-{dias_atras}",
        container_id="c",
        media_type="STORIES",
        published_at=quando.isoformat(timespec="seconds"),
    )


def medida(media_id: str, views: str, visitas: str) -> dict:
    return {"media_id": media_id, "views": views, "profile_visits": visitas}


class NotasTest(unittest.TestCase):
    def test_nota_e_a_media_das_publicacoes(self):
        # Rendeu bem na estreia e mal na repetição: tem que descer, não ficar
        # preso no topo pelo resultado antigo.
        publicados = [saiu("a", 50, "m1"), saiu("a", 25, "m2")]
        metricas = [medida("m1", "200", "6"), medida("m2", "100", "0")]

        nota = notas_por_item(publicados, metricas)["a"]

        self.assertEqual((nota.visitas, nota.views, nota.medicoes), (3.0, 150.0, 2))

    def test_leitura_vazia_nao_conta_como_zero(self):
        # Linha sem views = o coletor não chegou a ler. Não é nota baixa.
        publicados = [saiu("a", 50, "m1"), saiu("a", 25, "m2")]
        metricas = [medida("m1", "200", "6"), medida("m2", "", "")]

        nota = notas_por_item(publicados, metricas)["a"]

        self.assertEqual((nota.visitas, nota.medicoes), (6.0, 1))

    def test_item_sem_linha_nenhuma_fica_sem_nota(self):
        self.assertEqual(notas_por_item([saiu("a", 30)], []), {})


class SelecionarTest(unittest.TestCase):
    def fila(self, *ids):
        return parse_queue([story(i) for i in ids])

    def test_repete_primeiro_quem_levou_mais_gente_ao_perfil(self):
        publicados = [saiu("muita-view", 30, "m1"), saiu("muita-visita", 30, "m2")]
        metricas = [medida("m1", "260", "5"), medida("m2", "174", "9")]

        selecao = selecionar(self.fila("muita-view", "muita-visita"), publicados,
                             metricas, apos_dias=21, now=AGORA)

        self.assertEqual(selecao.item.id, "muita-visita")

    def test_views_so_desempata(self):
        publicados = [saiu("a", 30, "m1"), saiu("b", 30, "m2")]
        metricas = [medida("m1", "100", "2"), medida("m2", "180", "2")]

        selecao = selecionar(self.fila("a", "b"), publicados, metricas,
                             apos_dias=21, now=AGORA)

        self.assertEqual([i.id for i in selecao.eligible], ["b", "a"])

    def test_respeita_o_intervalo_desde_a_ultima_vez(self):
        # Saiu há 30 dias e de novo há 10: a última vez é que conta.
        publicados = [saiu("a", 30), saiu("a", 10), saiu("b", 22)]

        selecao = selecionar(self.fila("a", "b"), publicados, [],
                             apos_dias=21, now=AGORA)

        self.assertEqual([i.id for i in selecao.eligible], ["b"])
        motivos = {p.item_id: p.reason for p in selecao.skipped}
        self.assertIn("repete só a partir de 2026-10-31", motivos["a"])

    def test_nada_vencido_nao_repete_nada(self):
        selecao = selecionar(self.fila("a"), [saiu("a", 5)], [],
                             apos_dias=21, now=AGORA)

        self.assertIsNone(selecao.item)

    def test_item_que_nunca_saiu_nao_e_assunto_da_repeticao(self):
        # Se a seleção normal não o escolheu, foi por um motivo que vale aqui.
        selecao = selecionar(self.fila("novo"), [], [], apos_dias=21, now=AGORA)

        self.assertIsNone(selecao.item)

    def test_sem_medicao_vai_para_o_fim_o_mais_antigo_primeiro(self):
        publicados = [saiu("sem-1", 40), saiu("sem-2", 60), saiu("medido", 25, "m1")]
        metricas = [medida("m1", "50", "0")]

        selecao = selecionar(self.fila("sem-1", "sem-2", "medido"), publicados,
                             metricas, apos_dias=21, now=AGORA)

        self.assertEqual([i.id for i in selecao.eligible], ["medido", "sem-2", "sem-1"])

    def test_bloqueado_por_falha_nao_repete(self):
        publicados = [saiu("a", 30, "m1"), saiu("b", 30, "m2")]
        metricas = [medida("m1", "200", "9"), medida("m2", "100", "1")]

        selecao = selecionar(self.fila("a", "b"), publicados, metricas,
                             apos_dias=21, now=AGORA,
                             bloqueados={"a": "quarentena"})

        self.assertEqual(selecao.item.id, "b")

    def test_respeita_o_formato(self):
        fila = parse_queue([story("s"), item(id="feed")])
        publicados = [saiu("s", 30), saiu("feed", 30)]

        selecao = selecionar(fila, publicados, [], apos_dias=21, now=AGORA,
                             media_types=("STORIES",))

        self.assertEqual([i.id for i in selecao.eligible], ["s"])

    def test_intervalo_zero_e_erro(self):
        with self.assertRaises(ValueError):
            selecionar(self.fila("a"), [], [], apos_dias=0, now=AGORA)


class PublishComRepeticaoTest(unittest.TestCase):
    """Pela linha de comando, como o workflow chama."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        base = self.dir.name
        self.fila = os.path.join(base, "stories.yaml")
        self.state = os.path.join(base, "published.json")
        self.falhas = os.path.join(base, "falhas.json")
        self.metricas = os.path.join(base, "metricas.csv")
        with open(self.fila, "w", encoding="utf-8") as handle:
            for n in ("velha-boa", "velha-fraca", "nova"):
                handle.write(f"- id: {n}\n  media_type: STORIES\n"
                             f"  url: https://media.example/{n}.jpg\n")
        with open(self.metricas, "w", encoding="utf-8") as handle:
            handle.write("media_id,views,profile_visits\nm-boa,150,8\nm-fraca,300,1\n")
        os.environ.pop("IG_DRY_RUN", None)
        os.environ["IG_SELECTION"] = "order"
        self.addCleanup(os.environ.pop, "IG_SELECTION", None)

    def gravar_estado(self, *entradas):
        agora = datetime.now(timezone.utc)
        linhas = [
            {"item_id": i, "media_id": m, "container_id": "c", "media_type": "STORIES",
             "published_at": (agora - timedelta(days=d)).isoformat()}
            for i, m, d in entradas
        ]
        with open(self.state, "w", encoding="utf-8") as handle:
            json.dump({"version": 1, "published": linhas}, handle)

    def rodar(self, *extra):
        saida = io.StringIO()
        with contextlib.redirect_stdout(saida):
            codigo = main([
                "publish", "--dry-run", "--queue", self.fila, "--state", self.state,
                "--falhas", self.falhas, "--metricas", self.metricas,
                "--media-type", "STORIES", *extra,
            ])
        return codigo, saida.getvalue()

    def test_foto_nova_ganha_da_repeticao(self):
        self.gravar_estado(("velha-boa", "m-boa", 30), ("velha-fraca", "m-fraca", 30))

        codigo, saida = self.rodar("--repetir-apos-dias", "21")

        self.assertEqual(codigo, 0)
        self.assertIn("escolhido: nova (STORIES)\n", saida)

    def test_sem_foto_nova_repete_a_que_levou_ao_perfil(self):
        self.gravar_estado(("velha-boa", "m-boa", 30), ("velha-fraca", "m-fraca", 30),
                           ("nova", "m-nova", 1))

        codigo, saida = self.rodar("--repetir-apos-dias", "21")

        self.assertEqual(codigo, 0)
        self.assertIn("escolhido: velha-boa (STORIES) — repetição", saida)

    def test_sem_a_opcao_nao_repete_nada(self):
        # O padrão continua sendo nunca repetir: só o workflow de stories liga.
        self.gravar_estado(("velha-boa", "m-boa", 30), ("velha-fraca", "m-fraca", 30),
                           ("nova", "m-nova", 1))

        codigo, _ = self.rodar()

        self.assertEqual(codigo, 2)

    def test_nada_vencido_continua_sem_publicar(self):
        self.gravar_estado(("velha-boa", "m-boa", 5), ("velha-fraca", "m-fraca", 5),
                           ("nova", "m-nova", 1))

        codigo, _ = self.rodar("--repetir-apos-dias", "21")

        self.assertEqual(codigo, 2)


if __name__ == "__main__":
    unittest.main()
