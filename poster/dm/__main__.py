"""`python -m poster.dm` — sobe o servidor sem importar o resto da CLI.

A CLI completa puxa Drive, Pillow e cia.; o contêiner do servidor só precisa
do PyYAML. Mesmo comportamento de `python -m poster.cli dm-servir`.
"""
import argparse

from .cli import cmd_servir

raise SystemExit(cmd_servir(argparse.Namespace(fluxos="")))
