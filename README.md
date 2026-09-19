# line-insta-poster

Automação de publicação no Instagram da loja.

Fila curada em YAML versionado, publicação pela Graph API, agendamento pelo
GitHub Actions. Sem servidor, sem banco: o repositório é o estado.

```
queue/posts.yaml      ← fila curada à mão (é onde você trabalha)
state/published.json  ← o que já saiu, commitado pelo próprio job
poster/               ← código
.github/workflows/    ← publish (diário), refresh-token (mensal), curate (mensal)
```

## Como funciona

```
1. lê queue/posts.yaml e valida item por item
2. descarta o que já está em state/published.json
3. sorteia o próximo (peso por item) ou pega o primeiro da fila
4. POST /{ig-user-id}/media            → container
5. GET  /{container-id}?status_code    → espera FINISHED (1x/min, teto 5 min)
6. POST /{ig-user-id}/media_publish    → publica
7. só então grava em state/published.json e commita
```

Falhou em qualquer passo? **Não marca nada** e dispara alerta. Marcar antes de
`media_publish` devolver id é o jeito clássico de perder post em silêncio.

## Decisões que valem explicar

**Facebook Login for Business, não Instagram Login.** A conta já está ligada à
Página do Facebook e ao Business Manager; o vínculo existe. Mesmo host das
chamadas de ads, caso um dia se queira unificar.

**Bucket público em vez de upload resumable.** Mais simples de escrever e de
depurar: uma URL, um `curl`. O resumable elimina o bucket e o risco de expor o
acervo, mas é mais código — fica para quando o bucket incomodar (o cliente aqui
não muda, só a criação do container).

**Fila em YAML, não banco.** O acervo é finito e curado à mão. Um arquivo no
repo dá diff, review e rollback de graça, e é editável pelo celular.

**`reviewed_price` não é decoração.** O acervo tem post com preço pré-reajuste.
A validação **recusa** publicar item sem a flag. É o controle que impede a
automação de queimar confiança no DM — e ele é humano, não automatizável.

## Antes do primeiro post

- [ ] Conta Business/Creator (o id vai no secret `IG_USER_ID`)
- [ ] Vinculada à Página do Facebook
- [ ] Usuário com tarefa `MANAGE` ou `CREATE_CONTENT` na Página
- [ ] PPA (Page Publishing Authorization) — só vale para Páginas de grande
      alcance; Página de loja normalmente não é exigida. Ver `docs/SETUP.md`
- [ ] App Meta tipo Business com o produto Instagram / Facebook Login for Business
- [ ] Permissões: `instagram_basic`, `instagram_content_publish`,
      `pages_read_engagement` (+ `instagram_manage_insights` para a curadoria)
- [ ] Secrets do repositório preenchidos (abaixo)
- [ ] Canal de alerta definido (`IG_ALERT_WEBHOOK`)

App Review **não** é necessário para publicar em conta própria administrada.

### Secrets

| Secret | Para quê |
|---|---|
| `IG_USER_ID` | id da conta Instagram Business |
| `IG_ACCESS_TOKEN` | long-lived token do usuário (renovado sozinho todo mês) |
| `META_APP_ID` / `META_APP_SECRET` | validade e renovação do token |
| `GH_SECRETS_TOKEN` | PAT fine-grained com `Secrets: read and write` neste repo |
| `IG_ALERT_WEBHOOK` | URL que recebe o alerta de falha (opcional, mas recomendado) |

O `GITHUB_TOKEN` padrão do Actions **não** escreve secrets — daí o PAT.

## Uso

```bash
pip install -r requirements.txt

python -m poster.cli validate              # valida a fila, não usa rede
python -m poster.cli publish --dry-run     # escolhe o item sem publicar
python -m poster.cli publish               # publica de verdade
python -m poster.cli token                 # dias restantes do token
python -m poster.cli refresh-token         # renova o long-lived token
python -m poster.cli curate --insights     # ranqueia o acervo e gera candidatos
python -m poster.cli rehost --media-id X   # baixa a mídia de um post para media/
```

Pelo celular: aba **Actions** → *Publicar no Instagram* → *Run workflow*.

## Duas filas, dois níveis de confiança

| Fila | O que entra | Publica |
|---|---|---|
| `queue/posts.yaml` | feed, Reels, carrossel | só com `reviewed_price: true` e legenda escrita |
| `queue/stories.yaml` | fotos da pasta do Drive | **sozinha**, um story por execução |

A diferença não é rigor a mais ou a menos: é o que cada formato carrega. A flag
`reviewed_price` existe para impedir preço velho **na legenda**, e story não tem
legenda — a API nem aceita o campo. Exigir a conferência ali seria burocracia
sem proteção.

O que isso **não** cobre: preço queimado dentro da imagem. Nenhuma validação
alcança pixel. Story dura 24h e dá para apagar pelo app.

Para mandar uma foto do Drive ao feed, copie o item para `queue/posts.yaml`,
troque o `media_type`, escreva a legenda e marque `reviewed_price: true`.

## Formato da fila

```yaml
- id: satchel-pockets-conhaque-2024
  media_type: IMAGE          # IMAGE | REELS | STORIES | CAROUSEL
  url: https://media.exemplo.com/pockets_conhaque.jpg
  caption: |
    Satchel Pockets em couro conhaque.
    Feito por pessoas, para pessoas.
  reviewed_price: true       # obrigatório — sem isto o item é recusado
  weight: 3                  # peso no sorteio
  repeat_after_days: 120     # sem isto, item publicado nunca repete
```

Formato completo e comentado: [`queue/posts.example.yaml`](queue/posts.example.yaml).
A validação recusa url não-https, REELS sem vídeo, carrossel fora de 2–10 itens,
caption acima de 2.200 caracteres ou 30 hashtags, id duplicado e peso não-positivo
— e lista **todos** os problemas de uma vez, não só o primeiro.

## Curadoria automatizada

`python -m poster.cli curate` coleta o acervo, ranqueia e escreve
`queue/candidates.yaml`. O workflow mensal abre um PR com o resultado.

O score é **relativo à época do post**, não absoluto:

```
score = (like_count + comments_count × 7) / mediana_da_janela_de_±45_dias
```

A base de seguidores multiplicou de tamanho ao longo do acervo — comparar números
absolutos mistura épocas incomparáveis. Mediana e não média: um viral distorce a
média e rebaixa todo o resto da janela.

Só curtidas e comentários entram no ranking universal: `impressions`, `plays` e
`video_views` foram depreciadas, e `views`/`reach`/`saved`/`shares` só existem
para mídia criada a partir de ~jul/2024. Insights enriquecem o recorte recente,
nunca o histórico.

**O que isto não resolve.** Ranquear por engajamento seleciona post bonito, não
post que vende: o post que puxou quase todos os pedidos de um mês recente foi um
de reajuste — urgência, não estética —, e um ranking por curtidas provavelmente o
colocaria em posição mediana. Isto resolve **frequência de publicação**; não resolve
**gatilho comercial**. São problemas diferentes, e o segundo é o que move receita.

**Campanha com data não entra nos candidatos.** Post de reajuste, promoção ou
"últimas peças" costuma performar bem justamente porque cria urgência — mas
urgência vence. Republicar "últimas peças" três meses depois, com a peça em
estoque, é falso, e quem responde no DM descobre. Esses posts não são ruins, são
**irrepetíveis**: `queue/exclusoes.yaml` lista os termos (sem depender de acento
ou caixa, com `*` para flexões) e é editável pelo celular.

Eles continuam contando na **mediana da época**, de propósito: fizeram parte
daquele mês, e tirá-los da base de comparação rebaixaria o denominador e
inflaria o score de todo o resto.

Por isso o pipeline gera candidatos, e o PR tem checklist: o preço e o "essa peça
ainda existe?" são decisão humana.

Cada candidato traz `source_media_url` — o link da Meta para baixar a mídia
original. Ele expira em algumas horas, então serve para rehospedar na hora da
revisão, nunca como `url` da fila.

## Documentação

- [`docs/SETUP.md`](docs/SETUP.md) — do zero ao primeiro post: PPA, app Meta,
  token, secrets e o teste sem plateia.
- [`docs/OPERACAO.md`](docs/OPERACAO.md) — runbook: o que fazer quando falha,
  limites da API, migração para resumable.

## Testes

```bash
python -m unittest discover -s tests -t . -v
```

Nenhum teste toca a rede: o transporte HTTP e o cliente da Graph API são
injetáveis, e o fluxo inteiro roda contra dublês.
