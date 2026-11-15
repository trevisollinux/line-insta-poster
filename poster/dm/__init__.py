"""Respostas automáticas no direct — o "ManyChat" da loja.

Diferente do resto do projeto, isto **não roda no GitHub Actions**: a Meta avisa
de cada comentário e mensagem por webhook, em tempo real, e o cron daqui atrasa
horas. Precisa de um processo sempre no ar (`python -m poster.cli dm-servir`).

    dm/fluxos.yaml   ← o que responder, e quando (é onde você trabalha)
    fluxos.py        lê e valida o YAML
    eventos.py       traduz o JSON do webhook em eventos simples
    motor.py         decide o que fazer com cada evento (sem rede)
    envio.py         manda pela Send API
    estado.py        SQLite: evento já visto, cupom já entregue
    servidor.py      HTTP: verificação da Meta, assinatura, fila de trabalho

O que a API pública NÃO permite, e por isso não está aqui: mandar DM para quem
acabou de seguir. A Meta não emite evento de "novo seguidor" — o gatilho do
ManyChat usa uma integração exclusiva. Ver `docs/DM.md`.
"""
