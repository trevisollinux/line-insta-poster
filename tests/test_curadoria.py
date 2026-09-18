"""Ranking: normalização por mediana da época e coleta em lotes."""
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import yaml

from tests.support import FakeClient

from poster.curadoria import (
    DEFAULT_EXCLUSIONS,
    EXCLUSIONS_PATH,
    INSIGHTS_CUTOFF,
    MediaPost,
    candidates_document,
    collect_media,
    compile_exclusions,
    excluded_by,
    fetch_insights,
    load_catalog,
    load_exclusions,
    merge_catalog,
    raw_score,
    save_catalog,
    score_catalog,
    split_recyclable,
    write_candidates,
)

IG = "17841000000000000"
BASE = datetime(2024, 1, 1, tzinfo=timezone.utc)


def post(id_, dias, likes=100, comentarios=0, **kwargs):
    return MediaPost(
        id=id_,
        timestamp=BASE + timedelta(days=dias),
        like_count=likes,
        comments_count=comentarios,
        **kwargs,
    )


class ScoreTest(unittest.TestCase):
    def test_comentario_pesa_mais_que_curtida(self):
        self.assertEqual(raw_score(post("a", 0, likes=10, comentarios=1), 7.0), 17.0)

    def test_score_e_relativo_a_mediana_da_janela(self):
        posts = [post(str(i), i * 5, likes=100) for i in range(6)]
        posts.append(post("destaque", 10, likes=300))

        ranking = {s.post.id: s for s in score_catalog(posts)}

        self.assertEqual(ranking["destaque"].score, 3.0)
        self.assertEqual(ranking["0"].score, 1.0)

    def test_viral_nao_rebaixa_a_janela_inteira(self):
        """Mediana em vez de média: um pico não achata o resto da época."""
        posts = [post(str(i), i, likes=100) for i in range(10)]
        posts.append(post("viral", 5, likes=100000))

        ranking = {s.post.id: s for s in score_catalog(posts)}

        self.assertEqual(ranking["3"].score, 1.0)  # com média, cairia para ~0,01
        self.assertGreater(ranking["viral"].score, 900)

    def test_epocas_diferentes_sao_comparadas_separadamente(self):
        """Mesmo desempenho relativo em bases diferentes dá o mesmo score."""
        antigos = [post(f"a{i}", i, likes=100) for i in range(5)]
        recentes = [post(f"r{i}", 300 + i, likes=1000) for i in range(5)]
        antigos.append(post("antigo-bom", 2, likes=200))
        recentes.append(post("recente-bom", 302, likes=2000))

        ranking = {s.post.id: s for s in score_catalog(antigos + recentes)}

        self.assertEqual(ranking["antigo-bom"].score, ranking["recente-bom"].score)

    def test_janela_sem_engajamento_nao_divide_por_zero(self):
        posts = [post(str(i), i, likes=0) for i in range(3)]

        for item in score_catalog(posts):
            self.assertEqual(item.score, 0.0)

    def test_ranking_sai_ordenado_do_melhor_para_o_pior(self):
        posts = [post("fraco", 0, likes=10), post("forte", 1, likes=1000)]

        self.assertEqual([s.post.id for s in score_catalog(posts)][0], "forte")


class CollectTest(unittest.TestCase):
    def test_pagina_ate_acabar_e_zera_o_cursor(self):
        client = FakeClient(
            {
                ("GET", f"{IG}/media"): [
                    {
                        "data": [{"id": "1", "timestamp": "2026-01-01T10:00:00+0000"}],
                        "paging": {"cursors": {"after": "CUR1"}, "next": "https://..."},
                    },
                    {
                        "data": [{"id": "2", "timestamp": "2026-01-02T10:00:00+0000"}],
                        "paging": {"cursors": {"after": "CUR2"}},
                    },
                ]
            }
        )

        posts, cursor = collect_media(client, IG, max_pages=5)

        self.assertEqual([p.id for p in posts], ["1", "2"])
        self.assertIsNone(cursor)

    def test_lote_encerrado_devolve_cursor_para_a_proxima_execucao(self):
        client = FakeClient(
            {
                ("GET", f"{IG}/media"): [
                    {
                        "data": [{"id": "1", "timestamp": "2026-01-01T10:00:00+0000"}],
                        "paging": {"cursors": {"after": "CUR1"}, "next": "https://..."},
                    }
                ]
            }
        )

        posts, cursor = collect_media(client, IG, max_pages=1)

        self.assertEqual(cursor, "CUR1")
        self.assertEqual(len(posts), 1)

    def test_cursor_salvo_e_reenviado(self):
        client = FakeClient({("GET", f"{IG}/media"): [{"data": [], "paging": {}}]})

        collect_media(client, IG, cursor="CUR9", max_pages=1)

        self.assertEqual(client.chamadas[0][2]["after"], "CUR9")


class InsightsTest(unittest.TestCase):
    def test_midia_antiga_nao_chama_insights(self):
        antigo = MediaPost(id="velho", timestamp=INSIGHTS_CUTOFF - timedelta(days=1))
        client = FakeClient({})

        self.assertEqual(fetch_insights(client, antigo), {})
        self.assertEqual(client.chamadas, [])

    def test_midia_recente_le_metricas(self):
        recente = MediaPost(id="novo", timestamp=INSIGHTS_CUTOFF + timedelta(days=30))
        client = FakeClient(
            {
                ("GET", "novo/insights"): {
                    "data": [
                        {"name": "saved", "values": [{"value": 12}]},
                        {"name": "shares", "values": [{"value": 4}]},
                    ]
                }
            }
        )

        self.assertEqual(fetch_insights(client, recente), {"saved": 12, "shares": 4})


class CatalogTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = os.path.join(self.dir.name, "catalog.json")

    def test_ida_e_volta_com_cursor(self):
        save_catalog([post("1", 0, likes=5)], "CUR1", self.path)

        posts, cursor = load_catalog(self.path)

        self.assertEqual(posts[0].like_count, 5)
        self.assertEqual(cursor, "CUR1")

    def test_merge_atualiza_contadores_e_preserva_insights(self):
        antigo = post("1", 0, likes=10)
        antigo.insights = {"saved": 3}
        novo = post("1", 0, likes=40)

        [resultado] = merge_catalog([antigo], [novo])

        self.assertEqual(resultado.like_count, 40)
        self.assertEqual(resultado.insights, {"saved": 3})


class CandidatesTest(unittest.TestCase):
    def test_candidato_nasce_sem_preco_revisado(self):
        ranking = score_catalog([post("1", 0, likes=100), post("2", 1, likes=900)])

        documento = candidates_document(ranking, top_n=2)

        self.assertEqual(len(documento), 2)
        for linha in documento:
            self.assertFalse(linha["reviewed_price"])
            self.assertEqual(linha["url"], "")

    def test_peso_fica_entre_1_e_5(self):
        ranking = score_catalog([post("1", 0, likes=1), post("2", 1, likes=100000)])

        pesos = [linha["weight"] for linha in candidates_document(ranking)]

        self.assertTrue(all(1.0 <= peso <= 5.0 for peso in pesos), pesos)

    def test_arquivo_gerado_e_yaml_valido_com_aviso_de_revisao(self):
        destino = os.path.join(tempfile.mkdtemp(), "candidates.yaml")
        ranking = score_catalog([post("1", 0, likes=100, comentarios=2)])

        write_candidates(ranking, path=destino, top_n=1)

        with open(destino, encoding="utf-8") as handle:
            conteudo = handle.read()
        self.assertIn("NÃO é a fila", conteudo)
        self.assertEqual(yaml.safe_load(conteudo)[0]["source_media_id"], "1")


if __name__ == "__main__":
    unittest.main()


class ExclusionTest(unittest.TestCase):
    """Campanha de urgência é irrepetível: republicar depois vira mentira."""

    def setUp(self):
        self.pats = compile_exclusions(load_exclusions(EXCLUSIONS_PATH))

    def test_post_de_acervo_passa(self):
        self.assertIsNone(
            excluded_by("Satchel Pockets em couro conhaque.", self.pats)
        )

    def test_reajuste_e_barrado(self):
        self.assertEqual(excluded_by("REAJUSTE a partir de segunda", self.pats), "reajuste")

    def test_acento_e_caixa_nao_importam(self):
        self.assertIsNotNone(excluded_by("PROMOÇÃO de inverno", self.pats))
        self.assertIsNotNone(excluded_by("promocao de inverno", self.pats))

    def test_expressao_com_espaco_casa_sem_acento(self):
        self.assertEqual(
            excluded_by("ultimas pecas disponiveis", self.pats), "últimas peças"
        )

    def test_curinga_cobre_as_flexoes(self):
        for legenda in ("peça esgotada", "peças esgotadas", "modelo esgotado"):
            self.assertIsNotNone(excluded_by(legenda, self.pats), legenda)

    def test_termo_nao_casa_dentro_de_outra_palavra(self):
        """'promo' não pode barrar 'promovido'... mas 'promoçã*' sim, por desenho."""
        pats = compile_exclusions(["promo", "off"])

        self.assertIsNone(excluded_by("office bag em couro", pats))
        self.assertIsNone(excluded_by("promovido pela revista", pats))
        self.assertIsNotNone(excluded_by("promo de julho", pats))

    def test_legenda_vazia_passa(self):
        self.assertIsNone(excluded_by("", self.pats))

    def test_arquivo_ausente_cai_no_padrao(self):
        self.assertEqual(load_exclusions("/nao/existe.yaml"), list(DEFAULT_EXCLUSIONS))

    def test_arquivo_versionado_e_legivel(self):
        termos = load_exclusions(EXCLUSIONS_PATH)

        self.assertIn("reajuste", termos)
        self.assertGreater(len(termos), 10)


class SplitRecyclableTest(unittest.TestCase):
    def setUp(self):
        self.pats = compile_exclusions(["reajuste"])

    def test_separa_reciclaveis_de_campanha(self):
        acervo = post("acervo", 0, likes=100)
        acervo.caption = "Bolsa em couro conhaque"
        campanha = post("campanha", 1, likes=900)
        campanha.caption = "REAJUSTE na segunda"
        ranking = score_catalog([acervo, campanha])

        reciclaveis, excluidos = split_recyclable(ranking, self.pats)

        self.assertEqual([r.post.id for r in reciclaveis], ["acervo"])
        self.assertEqual([(e.post.id, termo) for e, termo in excluidos], [("campanha", "reajuste")])

    def test_excluido_continua_na_mediana_da_janela(self):
        """O filtro é de candidatura, não de base de comparação."""
        acervo = [post(f"a{i}", i, likes=100) for i in range(5)]
        campanha = post("campanha", 2, likes=100000)
        campanha.caption = "REAJUSTE"
        ranking = score_catalog(acervo + [campanha])
        mediana_com_campanha = {s.post.id: s.window_median for s in ranking}

        reciclaveis, _ = split_recyclable(ranking, self.pats)

        for item in reciclaveis:
            self.assertEqual(item.window_median, mediana_com_campanha[item.post.id])
            self.assertEqual(item.window_size, 6)  # os 6 posts da época, não 5

    def test_candidatos_saem_sem_a_campanha(self):
        acervo = post("acervo", 0, likes=100)
        acervo.caption = "Bolsa"
        campanha = post("campanha", 1, likes=900)
        campanha.caption = "Últimas peças"
        ranking = score_catalog([acervo, campanha])

        reciclaveis, _ = split_recyclable(
            ranking, compile_exclusions(load_exclusions(EXCLUSIONS_PATH))
        )
        documento = candidates_document(reciclaveis, top_n=10)

        self.assertEqual([linha["source_media_id"] for linha in documento], ["acervo"])


class SourceMediaUrlTest(unittest.TestCase):
    def test_candidato_traz_o_link_para_baixar_o_original(self):
        item = post("1", 0, likes=10)
        item.media_url = "https://scontent.example/original.jpg"

        [linha] = candidates_document(score_catalog([item]), top_n=1)

        self.assertEqual(linha["source_media_url"], "https://scontent.example/original.jpg")
        self.assertEqual(linha["url"], "", "url só é preenchida com a mídia rehospedada")


class SinceTest(unittest.TestCase):
    """Recorte por data: a API entrega do mais novo para o mais antigo."""

    def pagina(self, ids_e_datas, tem_proxima=True):
        return {
            "data": [
                {"id": i, "timestamp": d.isoformat()} for i, d in ids_e_datas
            ],
            "paging": (
                {"cursors": {"after": "CUR"}, "next": "https://..."}
                if tem_proxima
                else {"cursors": {"after": "CUR"}}
            ),
        }

    def test_para_ao_alcancar_post_mais_antigo_que_o_corte(self):
        hoje = datetime(2026, 9, 18, tzinfo=timezone.utc)
        corte = hoje - timedelta(days=365)
        client = FakeClient(
            {
                ("GET", f"{IG}/media"): [
                    self.pagina([("novo", hoje), ("recente", hoje - timedelta(days=100))]),
                    self.pagina(
                        [
                            ("limite", hoje - timedelta(days=364)),
                            ("velho", hoje - timedelta(days=400)),
                        ]
                    ),
                    self.pagina([("nunca", hoje - timedelta(days=500))]),
                ]
            }
        )

        posts, cursor = collect_media(client, IG, max_pages=5, since=corte)

        self.assertEqual([p.id for p in posts], ["novo", "recente", "limite"])
        self.assertIsNone(cursor, "recorte por data recomeça do topo na próxima vez")
        self.assertEqual(len(client.chamadas), 2, "não pagina além do corte")

    def test_sem_corte_o_comportamento_nao_muda(self):
        hoje = datetime(2026, 9, 18, tzinfo=timezone.utc)
        client = FakeClient(
            {
                ("GET", f"{IG}/media"): [
                    self.pagina([("a", hoje - timedelta(days=500))], tem_proxima=False)
                ]
            }
        )

        posts, cursor = collect_media(client, IG, max_pages=5)

        self.assertEqual([p.id for p in posts], ["a"])
        self.assertIsNone(cursor)

    def test_lote_inteiro_dentro_do_corte_continua_paginando(self):
        hoje = datetime(2026, 9, 18, tzinfo=timezone.utc)
        client = FakeClient(
            {
                ("GET", f"{IG}/media"): [
                    self.pagina([("a", hoje)]),
                    self.pagina([("b", hoje - timedelta(days=1))]),
                ]
            }
        )

        posts, cursor = collect_media(
            client, IG, max_pages=2, since=hoje - timedelta(days=365)
        )

        self.assertEqual([p.id for p in posts], ["a", "b"])
        self.assertEqual(cursor, "CUR", "lote acabou por max_pages, não por data")
