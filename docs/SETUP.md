# Do zero ao primeiro post

Ordem importa: o passo 1 pode bloquear tudo, e descobrir isso depois de escrever
configuração é desperdício. Os nomes de menu da Meta mudam com frequência — se a
tela não bater com o texto, procure pelo termo em negrito na busca do próprio
painel.

---

## 1. Confirmar a PPA da Página

**Page Publishing Authorization.** Provavelmente **não se aplica** a esta Página
— e não achar a opção é o resultado esperado, não busca mal feita.

A exigência vale para Páginas de grande alcance: veículos de notícia e quem
publica sobre temas sociais, eleições ou política. Página de loja não entra no
critério, e nesse caso a opção simplesmente não existe nas configurações.

Como confirmar sem caçar menu:

1. **A Meta avisaria.** Quando é exigida, os admins recebem notificação e a
   Página exibe aviso; ficando pendente, a publicação é restringida. Sem aviso e
   sem a entrada em Configurações da Página = não é exigida.
2. **O primeiro post de teste é a prova definitiva.** Com PPA pendente, a
   publicação falha com erro de permissão citando a autorização. O teste do
   passo 5 (um `STORIES`, que some em 24h) já cobre isso — verificação de graça.

Referência da Meta, se algum dia a Página mudar de categoria:
[Get authorized to post or interact as your Page](https://www.facebook.com/help/1939753742723975).

Por que isto continua sendo o item 1: *se* aplicasse, bloquearia tudo e levaria
dias para resolver. Verificar custa um minuto; descobrir tarde custa a semana.

---

## 2. Criar o app Meta e obter o token

### 2.1. O app

1. [developers.facebook.com](https://developers.facebook.com/apps/) → **Criar
   app** → tipo **Business** (Negócios).
2. Vincule ao portfólio comercial (Business Portfolio) que administra a Página.
3. Adicione o produto **Instagram** → configuração **com Facebook Login**
   (Facebook Login for Business).
4. **Configurações → Básico**: `ID do aplicativo` e `Chave secreta` são os
   secrets `META_APP_ID` e `META_APP_SECRET`.

**App Review não é necessário** para publicar em conta própria administrada —
o app pode ficar em modo de desenvolvimento.

### 2.2. O token

1. [Graph API Explorer](https://developers.facebook.com/tools/explorer/) →
   selecione o app → **Get User Access Token**.
2. Marque as permissões:
   - `instagram_basic`
   - `instagram_content_publish`
   - `pages_show_list`
   - `pages_read_engagement`
   - `business_management` (costuma ser necessária para listar as Páginas do
     portfólio)
   - `instagram_manage_insights` (só se for usar a curadoria)
3. Gere e copie. **Esse token é de curta duração (~1h)** — ele ainda não serve.

### 2.3. Descobrir o `IG_USER_ID`

Uma chamada resolve (troque `SEU_TOKEN`):

```bash
curl -s "https://graph.facebook.com/v21.0/me/accounts?fields=id,name,instagram_business_account&access_token=SEU_TOKEN"
```

O `instagram_business_account.id` da sua Página é o `IG_USER_ID`. O `id` da
Página é o id da Página (útil para conferir o vínculo, não vai em secret).

### 2.4. Trocar por um token de ~60 dias

O mesmo comando que o workflow mensal usa serve para a primeira troca:

```bash
export IG_ACCESS_TOKEN=SEU_TOKEN_CURTO
export META_APP_ID=...
export META_APP_SECRET=...

python -m poster.cli refresh-token     # imprime o token novo e a validade
```

Sem Python à mão, a chamada crua é:

```bash
curl -s "https://graph.facebook.com/v21.0/oauth/access_token\
?grant_type=fb_exchange_token&client_id=$META_APP_ID\
&client_secret=$META_APP_SECRET&fb_exchange_token=$IG_ACCESS_TOKEN"
```

O `access_token` devolvido é o que vai para o secret `IG_ACCESS_TOKEN`. Confira
a validade:

```bash
IG_ACCESS_TOKEN=<o novo> python -m poster.cli token
# token válido por mais 59 dias (expira em ...)
```

---

## 3. Preencher os secrets

**Settings → Secrets and variables → Actions → New repository secret.**

| Secret | Valor |
|---|---|
| `IG_USER_ID` | id do passo 2.3 |
| `IG_ACCESS_TOKEN` | token long-lived do passo 2.4 |
| `META_APP_ID` | Configurações → Básico |
| `META_APP_SECRET` | Configurações → Básico |
| `GH_SECRETS_TOKEN` | PAT, abaixo |
| `IG_ALERT_WEBHOOK` | URL de alerta, abaixo |

### `GH_SECRETS_TOKEN`

O `GITHUB_TOKEN` padrão do Actions **não escreve secrets**, e sem isso a
renovação mensal não consegue guardar o token novo.

1. [Fine-grained PAT](https://github.com/settings/personal-access-tokens/new)
2. **Resource owner**: sua conta · **Repository access**: *Only select
   repositories* → este repositório
3. **Repository permissions → Secrets**: *Read and write*
4. Expiração: o PAT também vence. Anote a data — PAT vencido quebra a renovação
   do token da Meta, que é uma falha de segunda ordem chata de diagnosticar.

### `IG_ALERT_WEBHOOK`

Recebe `POST` com `{"text": "...", "context": {...}}`. Esse formato funciona
direto em **webhook de entrada do Slack**. Discord espera `content` em vez de
`text` e precisaria de um ajuste em `poster/alerts.py` — peça se for o caso.

Opcional, mas: sem canal de alerta, falha é silêncio, e ausência de post não é
detectável sozinha.

### Se for usar a curadoria

**Settings → Actions → General → Workflow permissions** → marque *Allow GitHub
Actions to create and approve pull requests*. Sem isso o job de curadoria roda,
gera o ranking e falha na hora de abrir o PR.

---

## 4. Testar sem publicar nada

Três níveis, do mais barato ao mais real:

**a) A fila e a escolha** (não usa rede) — Actions → *Publicar no Instagram* →
*Run workflow* → `dry_run = true`. Valida a fila e mostra o item escolhido. Com
a fila vazia, o run termina com "nada a publicar" no Summary — é o esperado.

**b) A credencial** — Actions → *Renovar token do Instagram* → *Run workflow*.
Ele imprime a validade atual, renova e regrava o secret. Renovar cedo não custa
nada (o token novo nasce com ~60 dias) e prova de uma vez que `META_APP_ID`,
`META_APP_SECRET` e `GH_SECRETS_TOKEN` estão certos.

**c) A publicação de verdade, sem plateia** — o primeiro post real pode ser um
`STORIES`: some em 24h. Se algo estiver torto no formato da mídia, o estrago
é pequeno.

---

## 5. O primeiro post

Antes: a mídia precisa estar num **endereço https público** — a Graph API busca
a URL para montar o container. Bucket (R2, S3) é o destino final; para o teste,
qualquer host público serve.

1. Edite `queue/posts.yaml` (dá para fazer pelo próprio GitHub, no celular):

```yaml
- id: primeiro-teste-stories
  media_type: STORIES
  url: https://seu-bucket.exemplo.com/teste.jpg
  reviewed_price: true
```

2. Commit na `main`. O workflow *Testes* valida a fila no push — se você errou o
   formato, descobre aqui, não na hora do cron.
3. Actions → *Publicar no Instagram* → *Run workflow* com `dry_run = false`.
4. Confira: o Summary traz o media id, o permalink e o consumo do limite de 24h;
   e um commit novo registra o item em `state/published.json`.

Falhou? Nada foi marcado. Corrija e rode de novo — o item continua elegível.
O runbook de falhas está em [`OPERACAO.md`](OPERACAO.md).

---

## Depois que estiver rodando

- O cron publica todo dia às 10h (BRT). Mude em `.github/workflows/publish.yml`.
- A fila é onde está o trabalho real: manter itens com preço conferido.
- `repeat_after_days` libera repetição de um item — com legenda nova e corte
  diferente, senão a entrega piora.
- O GitHub **desativa workflows agendados após 60 dias sem atividade** no
  repositório. Publicação normal commita estado e mantém o cron vivo; fila vazia
  por dois meses, não.
