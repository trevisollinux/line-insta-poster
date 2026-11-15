# Respostas automáticas no direct

O "ManyChat" da loja: palavra-chave em comentário, story ou DM → mensagem com
botões no direct, cupom entregue uma vez por pessoa.

```
dm/fluxos.yaml   ← o que responder (é onde você trabalha)
poster/dm/       ← código
Dockerfile       ← o servidor
fly.toml         ← deploy no Fly.io
```

## O que faz e o que não faz

| Gatilho | Faz? |
|---|---|
| Comentário com palavra-chave → DM privada + resposta no comentário | ✅ |
| Resposta a story com palavra-chave → DM | ✅ |
| Palavra-chave no direct → DM | ✅ |
| Botões que levam a outra mensagem / a um link | ✅ |
| Cupom uma vez por pessoa (`uma_vez`) | ✅ |
| **"Começou a seguir" → DM** (o print do João & Maria) | ❌ |

O último não existe na API pública: a Meta não emite evento de novo seguidor.
O gatilho do ManyChat vem de uma parceria exclusiva com a Meta (out/2025), e
mesmo lá os usuários reclamam de falha. Se ele for indispensável, a saída é
assinar o ManyChat **só para isso** e deixar o resto aqui — mas aí as duas
ferramentas disputam a mesma caixa de entrada; dividir os gatilhos com cuidado
(o ManyChat sem palavras-chave).

**O bot não responde o que não casa com uma palavra.** Pergunta de preço,
resposta ao CTA do story ("caramelo ou marinho?"), pedido — tudo continua com
gente. É de propósito: o direct é onde a loja vende.

## Editar os fluxos

Ver o cabeçalho de `dm/fluxos.yaml`. Antes de subir, sempre:

```bash
python -m poster.cli dm-validar
python -m poster.cli dm-simular comentario "eu quero o cupom"
python -m poster.cli dm-simular botao cupom --vezes 2   # testa o uma_vez
python -m poster.cli dm-simular dm "quanto custa?"       # → nenhuma resposta
```

O arquivo versionado tem `TROCAR` no cupom e no link. Assim ele valida (CI
verde), mas o servidor **se recusa a ligar** até alguém preencher — cupom de
mentira para cliente é pior que nada. A validade de 24h do cupom se configura
na loja virtual; o texto só avisa.

Mudou o arquivo? Faça deploy de novo — o servidor lê os fluxos ao subir.

## Por que um servidor, se o resto é Actions

A Meta avisa de cada comentário/mensagem por **webhook**, na hora, e espera
resposta em segundos. O cron do Actions atrasa de 3h a 5h aqui (ver
`inbox.yml`). Não tem como.

O servidor é pequeno: stdlib + PyYAML, um SQLite com duas tabelas (evento já
visto; quem já recebeu qual passo). Perder o SQLite não é grave — no pior caso
alguém ganha um cupom de boas-vindas a mais.

Decisões:

- **Responde 200 antes de processar.** A Meta reentrega o que demora; o
  trabalho vai para uma fila com um trabalhador só.
- **Marca o evento como visto antes de enviar.** Entre não responder e
  responder duas vezes, o segundo é pior.
- **Comentário: a DM sai primeiro, a resposta pública depois.** Se a DM falhar,
  a pública ("te chamei no direct!") não sai — seria mentira.
- **Template recusado → texto + respostas rápidas.** A resposta privada a
  comentário pode não aceitar botão; o fluxo continua igual, só a aparência muda.
- **Token da Página, não de usuário.** O de Página derivado de um token de
  usuário de longa duração não expira, então o servidor não depende da
  renovação mensal que regrava o secret do GitHub (ele nem enxerga esse secret).
- **Alerta de falha no máximo 1x/hora por tipo de erro.** Sem permissão, toda
  mensagem falha.

## Ligar (quando as permissões saírem)

### 1. Permissões no app Meta

No app que já publica (`docs/SETUP.md`), caso de uso *Gerenciar mensagens e
conteúdo no Instagram*, adicionar:

- `instagram_manage_messages` — mandar DM
- `instagram_manage_comments` — receber comentários e responder
- `pages_manage_metadata` — inscrever a Página no webhook

Para clientes de verdade é preciso **acesso avançado** (App Review: vídeo do
fluxo, política de privacidade). Enquanto não sai, o webhook só dispara para
quem tem papel no app (admin/testador) — ótimo para testar.

No Instagram da loja: *Configurações → Mensagens e respostas a stories →
Ferramentas conectadas → Permitir acesso a mensagens*. Sem isso a Send API
recusa mesmo com permissão.

### 2. Token da Página

Com um `IG_ACCESS_TOKEN` gerado **depois** de adicionar as permissões novas:

```bash
IG_ACCESS_TOKEN=... IG_USER_ID=... python -m poster.cli dm-token-pagina
```

Imprime o token da Página ligada ao Instagram. Ele vai no servidor, não no
GitHub. Não cole em issue nem em log.

### 3. Hospedagem (Fly.io)

Qualquer lugar com HTTPS e um disco serve; o `fly.toml` está pronto para o
Fly.io (região São Paulo, uma máquina pequena sempre ligada + volume de 1 GB —
na faixa de poucos dólares por mês).

```bash
fly launch --no-deploy --copy-config        # ajusta o nome do app
fly volumes create dm_dados --size 1 --region gru
fly secrets set \
  IG_USER_ID=... \
  IG_PAGE_ACCESS_TOKEN=... \
  META_APP_SECRET=... \
  DM_VERIFY_TOKEN="$(openssl rand -hex 16)" \
  IG_ALERT_WEBHOOK=...
fly deploy
curl https://<app>.fly.dev/saude             # → ok
```

Guarde o `DM_VERIFY_TOKEN` gerado — ele vai no próximo passo.

Para ligar sem enviar nada (só log), `fly secrets set DM_DRY_RUN=true`. Em
dry-run o servidor aceita `TROCAR` e dispensa o token da Página.

### 4. Webhook

No painel do app → *Webhooks* → objeto **Instagram**:

- URL: `https://<app>.fly.dev/webhook`
- Verify token: o `DM_VERIFY_TOKEN`
- Campos: `messages`, `messaging_postbacks`, `comments`

E inscrever a Página no app (uma vez):

```bash
curl -X POST "https://graph.facebook.com/v21.0/<PAGE_ID>/subscribed_apps" \
  -d "subscribed_fields=feed" -d "access_token=<IG_PAGE_ACCESS_TOKEN>"
```

### 5. Teste

Com uma conta que tenha papel no app, comente "cupom" num post. Em segundos:
DM na conta de teste e resposta no comentário. Logs: `fly logs`.

## Variáveis

| Variável | |
|---|---|
| `IG_USER_ID` | id da conta Instagram (ignora eventos da própria loja) |
| `IG_PAGE_ACCESS_TOKEN` | token da Página (`dm-token-pagina`) |
| `META_APP_SECRET` | confere a assinatura de cada webhook |
| `DM_VERIFY_TOKEN` | frase combinada com a Meta no cadastro do webhook |
| `DM_DB` | SQLite (padrão `state/dm.sqlite3`; no Fly, `/data/dm.sqlite3`) |
| `DM_FLUXOS` | outro arquivo de fluxos (padrão `dm/fluxos.yaml`) |
| `DM_DRY_RUN` | `true` = só registra o que mandaria |
| `IG_ALERT_WEBHOOK` | mesmo canal de alerta da publicação |

## Regras da Meta que limitam o bot

- **Janela de 24h:** só se escreve para quem interagiu nas últimas 24h. O bot
  só responde a interação, então está sempre dentro.
- **Resposta privada a comentário:** uma por comentário, até 7 dias depois dele.
- **Nada de disparo em massa** para a base de seguidores — não existe na API.

## Quando der problema

| Sintoma | Provável causa |
|---|---|
| Alerta "parece permissão" | falta permissão / acesso avançado, ou "Permitir acesso a mensagens" desligado no Instagram |
| Nada chega no `fly logs` | webhook não cadastrado, campos não marcados, ou Página não inscrita (`subscribed_apps`) |
| Só funciona com a conta de teste | app sem acesso avançado (App Review) |
| POST /webhook 401 | `META_APP_SECRET` errado |
| Servidor não sobe: "TROCAR" | preencher o cupom e o link em `dm/fluxos.yaml` |
