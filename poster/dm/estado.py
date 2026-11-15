"""Memória do bot, em SQLite.

Duas perguntas só:

1. **Este evento já foi tratado?** A Meta reentrega webhook (rede instável,
   resposta lenta), e sem isso o cliente recebe o cupom duas vezes.
2. **Esta pessoa já recebeu este passo?** É o que faz `uma_vez` funcionar —
   o cupom de primeira compra não pode virar cupom infinito.

Não é o repositório, como o resto do projeto, porque aqui são dezenas de
escritas por dia vindas de um processo que não é o Actions. Perder este arquivo
não é grave: no pior caso alguém recebe um cupom de boas-vindas a mais.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time


class Estado:
    def __init__(self, caminho: str = ":memory:") -> None:
        if caminho != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(caminho)), exist_ok=True)
        self._con = sqlite3.connect(caminho, check_same_thread=False)
        self._trava = threading.Lock()
        with self._trava, self._con:
            self._con.execute(
                "CREATE TABLE IF NOT EXISTS vistos (id TEXT PRIMARY KEY, em REAL NOT NULL)"
            )
            self._con.execute(
                "CREATE TABLE IF NOT EXISTS entregues ("
                " usuario TEXT NOT NULL, passo TEXT NOT NULL, em REAL NOT NULL,"
                " PRIMARY KEY (usuario, passo))"
            )

    def marcar_visto(self, evento_id: str) -> bool:
        """True se é a primeira vez. Marca antes de processar, de propósito:
        entre não responder e responder duas vezes, o segundo é pior."""
        with self._trava, self._con:
            cursor = self._con.execute(
                "INSERT OR IGNORE INTO vistos (id, em) VALUES (?, ?)", (evento_id, time.time())
            )
            return cursor.rowcount == 1

    def ja_entregue(self, usuario: str, passo: str) -> bool:
        with self._trava:
            linha = self._con.execute(
                "SELECT 1 FROM entregues WHERE usuario = ? AND passo = ?", (usuario, passo)
            ).fetchone()
        return linha is not None

    def registrar_entrega(self, usuario: str, passo: str) -> None:
        with self._trava, self._con:
            self._con.execute(
                "INSERT OR IGNORE INTO entregues (usuario, passo, em) VALUES (?, ?, ?)",
                (usuario, passo, time.time()),
            )

    def limpar_vistos(self, mais_velhos_que_dias: int = 30) -> int:
        """Reentrega acontece em minutos; guardar id de mês passado é peso morto."""
        limite = time.time() - mais_velhos_que_dias * 86400
        with self._trava, self._con:
            return self._con.execute("DELETE FROM vistos WHERE em < ?", (limite,)).rowcount
