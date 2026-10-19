"""jsDelivr com 404 para arquivo que existe: limpa o cache ou usa o raw."""
import unittest

from poster import espelho

URL = "https://cdn.jsdelivr.net/gh/trevisollinux/line-store-media@main/inbox/foto.jpg"
RAW = "https://raw.githubusercontent.com/trevisollinux/line-store-media/main/inbox/foto.jpg"
PURGE = "https://purge.jsdelivr.net/gh/trevisollinux/line-store-media@main/inbox/foto.jpg"


class Resposta:
    def __init__(self, tipo):
        self.headers = {"Content-Type": tipo}

    def read(self, *_):
        return b""

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class Rede:
    """Cada URL responde, em ordem, com um tipo ou uma exceção."""

    def __init__(self, respostas):
        self.respostas = {url: list(lista) for url, lista in respostas.items()}
        self.pedidas = []

    def __call__(self, url, timeout=None):
        self.pedidas.append(url)
        lista = self.respostas.get(url) or [OSError("sem rota")]
        resposta = lista.pop(0) if len(lista) > 1 else lista[0]
        if isinstance(resposta, Exception):
            raise resposta
        return Resposta(resposta)


def escolher(rede, *, is_video=False, url=URL):
    return espelho.url_que_funciona(url, is_video=is_video, abrir=rede, esperar=lambda s: None)


class UrlQueFuncionaTest(unittest.TestCase):
    def test_jsdelivr_entregando_nao_mexe_em_nada(self):
        rede = Rede({URL: ["image/jpeg"]})

        self.assertEqual(escolher(rede), URL)
        self.assertEqual(rede.pedidas, [URL])

    def test_url_fora_do_jsdelivr_nem_e_consultada(self):
        rede = Rede({})

        self.assertEqual(escolher(rede, url="https://media.example/1.jpg"),
                         "https://media.example/1.jpg")
        self.assertEqual(rede.pedidas, [])

    def test_404_resolvido_pela_limpeza_do_cache(self):
        rede = Rede({URL: [OSError("HTTP Error 404"), "image/jpeg"], PURGE: ["application/json"]})

        self.assertEqual(escolher(rede), URL)
        self.assertIn(PURGE, rede.pedidas)

    def test_404_persistente_em_foto_vai_pelo_raw(self):
        rede = Rede({URL: [OSError("HTTP Error 404")], PURGE: ["application/json"],
                     RAW: ["image/jpeg"]})

        self.assertEqual(escolher(rede), RAW)

    def test_pagina_de_erro_nao_conta_como_foto(self):
        rede = Rede({URL: ["text/html"], PURGE: ["application/json"], RAW: ["image/jpeg"]})

        self.assertEqual(escolher(rede), RAW)

    def test_video_nao_usa_o_raw(self):
        # raw entrega .mp4 como octet-stream e a Meta recusa.
        url = URL.replace(".jpg", ".mp4")
        rede = Rede({url: [OSError("timed out")]})

        self.assertEqual(escolher(rede, is_video=True, url=url), url)
        self.assertNotIn(RAW.replace(".jpg", ".mp4"), rede.pedidas)

    def test_nada_responde_devolve_a_original(self):
        rede = Rede({})

        self.assertEqual(escolher(rede), URL)


if __name__ == "__main__":
    unittest.main()
