"""Memória do motor durante a simulação local.

Em produção a memória é o D1 do Worker (`worker/schema.sql`): evento já visto
e quem já recebeu qual passo. Aqui só o segundo importa, para `dm-simular
--vezes 2` mostrar o `se_repetido`.
"""
from __future__ import annotations


class Estado:
    def __init__(self) -> None:
        self._entregues: set[tuple[str, str]] = set()

    def ja_entregue(self, usuario: str, passo: str) -> bool:
        return (usuario, passo) in self._entregues

    def registrar_entrega(self, usuario: str, passo: str) -> None:
        self._entregues.add((usuario, passo))
