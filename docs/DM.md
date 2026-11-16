# Respostas automáticas no direct

O "ManyChat" da loja: palavra-chave em comentário, story ou DM → mensagem com
botões no direct, cupom entregue uma vez por pessoa.

```
dm/fluxos.yaml        ← o que responder (é onde você trabalha)
poster/dm/            ← Python: valida, simula e exporta os fluxos
worker/               ← Cloudflare Worker: recebe o webhook e responde
tests/dm_casos.json   ← casos que Python e Worker precisam decidir igual
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
verde), mas o deploy **se recusa a publicar** até alguém preencher — cupom de
mentira para cliente é pior que nada. A validade de 24h do cupom se configura
na loja virtual; o texto só avisa.

Mudou o arquivo? Leve para `main`: o workflow *Deploy do bot de DM* publica
de novo sozinho.

## Por que um Worker, se o resto é Actions

A Meta avisa de cada comentário/mensagem por **webhook**, na hora, e espera
resposta em segundos. O cron do Actions atrasa de 3h a 5h aqui (ver
`inbox.yml`), e o GitHub Pages só serve arquivo pronto — não recebe POST nem
roda código.

O Cloudflare Worker roda só quando chega um aviso, sem servidor ligado. O plano
grátis (pelo que a Cloudflare anunciava: 100 mil chamadas/dia, D1 incluso)
sobra para o volume de uma loja — confira a página de preços ao criar a conta.

Como as metades conversam:

1. `dm/fluxos.yaml` é a fonte. O Python valida (CI) e **exporta**
   `worker/src/fluxos.json` com as mensagens já montadas — o Worker não lê
   YAML nem monta template.
2. O workflow *Deploy do bot de DM* exporta, testa e publica o Worker a cada
   push em `main` que mexa nos fluxos ou no código.
3. O Worker guarda no **D1** (SQLite da Cloudflare) o evento já visto, quem já
   recebeu qual passo e o último alerta.

Decisões:

- **Responde 200 antes de processar** (`ctx.waitUntil`). A Meta reentrega o
  que demora.
- **Marca o evento como visto antes de enviar.** Entre não responder e
  responder duas vezes, o segundo é pior.
- **Comentário: a DM sai primeiro, a resposta pública depois.** Se a DM falhar,
  a pública ("te chamei no direct!") não sai — seria mentira.
- **Template recusado → texto + respostas rápidas.** A resposta privada a
  comentário pode não aceitar botão; o fluxo continua igual.
- **Token da Página, não de usuário.** Não expira, então o Worker não depende
  da renovação mensal do secret da publicação.
- **Alerta de falha no máximo 1x/hora por tipo de erro.** Sem permissão, toda
  mensagem falha.
- **Python e Worker decidem igual.** `tests/dm_casos.json` roda nos testes das
  duas linguagens; mudou a regra num lado, o outro quebra no CI.

## Ligar

Tudo pelo navegador — nada para instalar no computador.

### 1. Permissões no app Meta

No app que já publica (`docs/SETUP.md`), caso de uso *Gerenciar mensagens e
conteúdo no Instagram*, adicionar:

- `instagram_manage_messages` — mandar DM
- `instagram_manage_comments` — receber comentários e responder
- `pages_manage_metadata` — inscrever a Página no webhook

`pages_manage_metadata` **não aparece** no caso de uso do Instagram: é
permissão de Página. Antes de ir atrás dela, teste o passo 6 sem ela — se o
`subscribed_apps` responder `success: true`, ela não faz falta. Se der erro
de permissão (#200 ou #10), adicione o caso de uso **Gerenciar tudo na sua
Página** (*Casos de uso → Adicionar caso de uso*), que a traz.

Para clientes de verdade é preciso **acesso avançado** (App Review: vídeo do
fluxo, política de privacidade). Enquanto não sai, o webhook só dispara para
quem tem papel no app (admin/testador) — ótimo para testar.

No Instagram da loja: *Configurações → Mensagens e respostas a stories →
Ferramentas conectadas → Permitir acesso a mensagens*. Sem isso a Send API
recusa mesmo com permissão.

### 2. Token da Página

Com um `IG_ACCESS_TOKEN` gerado no Graph API Explorer **depois** de adicionar
as permissões novas:

```bash
IG_ACCESS_TOKEN=... IG_USER_ID=... python -m poster.cli dm-token-pagina
```

Imprime o token da Página ligada ao Instagram. Não cole em issue nem em log.

### 3. Cloudflare (conta grátis)

1. Crie a conta em [dash.cloudflare.com](https://dash.cloudflare.com).
2. **Workers & Pages** → na primeira visita a Cloudflare pede para escolher o
   subdomínio `*.workers.dev` (ex.: `linestore`). A URL do bot será
   `https://line-store-dm.<subdomínio>.workers.dev`.
3. **Storage & Databases → D1 → Create database**, nome `line-store-dm`.
   Copie o **Database ID**.
4. **Account ID**: aparece na página inicial do Workers & Pages (barra lateral)
   ou na URL do painel.
5. **Token de API**: ícone do perfil → *My Profile → API Tokens → Create
   Token* → modelo **Edit Cloudflare Workers** → em *Permissions*, adicione
   *Account → D1 → Edit* → crie e copie.

### 4. GitHub

*Settings → Secrets and variables → Actions* deste repositório:

| Onde | Nome | Valor |
|---|---|---|
| Secret | `CLOUDFLARE_API_TOKEN` | token do passo 3.5 |
| Secret | `CLOUDFLARE_ACCOUNT_ID` | passo 3.4 |
| Secret | `IG_PAGE_ACCESS_TOKEN` | passo 2 |
| Secret | `DM_VERIFY_TOKEN` | uma frase qualquer, longa (vai no passo 6) |
| Variable | `DM_D1_ID` | Database ID do passo 3.3 |
| Variable | `DM_DRY_RUN` | `true` no começo (só registra, não envia) |

`IG_USER_ID`, `META_APP_SECRET` e `IG_ALERT_WEBHOOK` já existem (são da
publicação) e o deploy reaproveita.

Para desligar o dry-run, mude `DM_DRY_RUN` para `false` e rode o workflow —
**não apague** a variável: o deploy só envia o que tem valor, e o `true`
antigo ficaria lá.

### 5. Deploy

Preencha o cupom e o link em `dm/fluxos.yaml` (os `TROCAR`) e leve para
`main`. O workflow **Deploy do bot de DM** roda sozinho (ou *Actions → Deploy
do bot de DM → Run workflow*). Enquanto faltar configuração ou houver
`TROCAR`, ele pula com um aviso no resumo, sem falhar.

Conferir: `https://line-store-dm.<subdomínio>.workers.dev/saude` → `ok`.

### 6. Webhook na Meta

Painel do app → *Casos de uso → (Instagram) → Configuração da API com login
do Facebook → 3. Configurar webhooks*:

- URL de callback: `https://line-store-dm.<subdomínio>.workers.dev/webhook`
- Verificar token: o `DM_VERIFY_TOKEN`
- Certificado de cliente: desligado
- Depois de salvar, assine `messages`, `messaging_postbacks` e `comments`

E inscrever a Página no app (uma vez):

```bash
curl -X POST "https://graph.facebook.com/v21.0/<PAGE_ID>/subscribed_apps" \
  -d "subscribed_fields=feed" -d "access_token=<IG_PAGE_ACCESS_TOKEN>"
```

### 7. Teste

Com uma conta que tenha papel no app, comente "cupom" num post. Em dry-run, o
que o bot *mandaria* aparece nos logs: Cloudflare → Workers & Pages →
`line-store-dm` → **Logs**. Com `DM_DRY_RUN=false`, chega a DM de verdade.

## Variáveis do Worker

| Nome | |
|---|---|
| `IG_USER_ID` | id da conta Instagram (ignora eventos da própria loja) |
| `IG_PAGE_ACCESS_TOKEN` | token da Página (`dm-token-pagina`) |
| `META_APP_SECRET` | confere a assinatura de cada webhook |
| `DM_VERIFY_TOKEN` | frase combinada com a Meta no cadastro do webhook |
| `DM_DRY_RUN` | `true` = só registra nos logs o que mandaria |
| `IG_ALERT_WEBHOOK` | mesmo canal de alerta da publicação |
| `DB` | o D1 (configurado no `wrangler.toml` pelo deploy) |

## Regras da Meta que limitam o bot

- **Janela de 24h:** só se escreve para quem interagiu nas últimas 24h. O bot
  só responde a interação, então está sempre dentro.
- **Resposta privada a comentário:** uma por comentário, até 7 dias depois dele.
- **Nada de disparo em massa** para a base de seguidores — não existe na API.

## Quando der problema

| Sintoma | Provável causa |
|---|---|
| Alerta "parece permissão" | falta permissão / acesso avançado, ou "Permitir acesso a mensagens" desligado no Instagram |
| Nada nos logs do Worker | webhook não cadastrado, campos não marcados, ou Página não inscrita (`subscribed_apps`) |
| Só funciona com a conta de teste | app sem acesso avançado (App Review) |
| POST /webhook 401 nos logs | `META_APP_SECRET` errado |
| "Verificar e salvar" falha na Meta | Worker não publicado, ou `DM_VERIFY_TOKEN` diferente do digitado |
| Deploy pulado | ver o resumo do run: falta secret/variável, ou ainda há `TROCAR` |
