"""Respostas automáticas no direct — o "ManyChat" da loja.

Duas metades:

- **Aqui, em Python:** `dm/fluxos.yaml` é lido, validado (CI), simulado
  (`dm-simular`) e exportado em JSON já montado (`dm-exportar`).
- **`worker/`, em JavaScript:** o Cloudflare Worker que recebe o webhook da
  Meta em tempo real, decide com o JSON exportado e responde pela Send API.
  O GitHub Actions não serve para isso: o cron daqui atrasa horas.

    fluxos.py   lê, valida e exporta o YAML
    motor.py    decisão de referência (simulação); o Worker faz o mesmo em JS
    estado.py   memória da simulação; em produção é o D1
    cli.py      dm-validar, dm-simular, dm-exportar, dm-token-pagina

O que a API pública NÃO permite, e por isso não está aqui: mandar DM para quem
acabou de seguir. A Meta não emite evento de "novo seguidor". Ver `docs/DM.md`.
"""
