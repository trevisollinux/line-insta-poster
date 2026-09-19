# Runbook

## Rotina normal

| Workflow | Quando | O que faz |
|---|---|---|
| Publicar no Instagram | diário, 10h BRT | publica um item e commita o estado |
| Publicar Stories (automático) | diário, 18h e 21h BRT | publica um story de `queue/stories.yaml`, sem aprovação |
| Renovar token | dia 1, 6h BRT | renova o long-lived token e regrava o secret |
| Curadoria do acervo | dia 1, 8h BRT | ranqueia o acervo e abre PR com candidatos |
| Capturar métricas dos stories | de hora em hora | lê os stories no ar e grava em `state/stories_metrics.csv` e `state/stories_curva.csv` |
| Testes | push e PR | suíte + validação da fila versionada |

Códigos de saída da CLI: `0` sucesso, `1` falha (com alerta), `2` nada a fazer.
O workflow de publicação trata `2` como aviso, não como falha — fila vazia não é
erro, mas aparece no Summary do run.

### Por que a captura de story roda tanto

Story expira em 24h e a Graph API não guarda nada depois disso: `/stories`
devolve só o que está no ar agora. Métrica não capturada é métrica perdida, sem
recuperação possível.

A leitura é de hora em hora, cobrindo as 24h de vida de cada story. Isso gera
dois arquivos com papéis diferentes:

- `state/stories_metrics.csv` — uma linha por story, com o total de cada
  métrica. Responde "quanto rendeu".
- `state/stories_curva.csv` — uma linha por leitura, com a idade do story em
  horas. Responde "quando rendeu", que é a pergunta que decide se horário de
  publicação importa: se um story das 21h junta quase todas as visualizações
  nas duas primeiras horas, o horário decide; se elas pingam ao longo do dia
  seguinte, quase não decide.

Foi a curva que justificou sair de 4 em 4 horas para de hora em hora. Com o
intervalo maior dava para saber o total, mas não o formato da subida — e esse
dado não é recuperável depois.

O arquivo guarda uma linha por story e as métricas ficam com o maior valor já
lido, não com o mais recente: são contadores que só sobem, então número menor
numa captura seguinte é oscilação da API, não queda de audiência.

A coluna `posicao_dia` é calculada na gravação, não vem da API. Ela é o dado que
mais explicou o alcance até agora — o 2º story do dia rende consistentemente
menos que o 1º —, e recalcular tudo a cada gravação faz o arquivo se corrigir
sozinho se uma captura chegar fora de ordem.

## Quando falha

**Alerta chegou (ou o job ficou vermelho).** Abra o run, leia o Summary. O item
**não** foi marcado como publicado: corrigido o problema, ele volta a ser
sorteado sozinho no próximo disparo. Não existe estado pela metade.

**`container ... terminou como ERROR`.** A Meta rejeitou a mídia. Quase sempre é
a URL: precisa ser pública, `https`, sem redirecionamento e com o tipo certo
(JPEG para imagem; MP4/MOV para vídeo). Teste com `curl -I <url>`.

Um caso já visto: **link do CDN da Meta não serve como origem**. Usar o
`source_media_url` de um post existente falha com `2207076` — aquele link é de
entrega para player, assinado e com parâmetros de streaming, não um arquivo
servido para ingestão. Ele serve para **baixar** a mídia original na hora da
revisão; a fila precisa da cópia rehospedada.

Outras causas de `2207076`, quando a URL está certa: bitrate de vídeo acima de
25 Mbps, áudio fora de AAC 128 kbps, ou vídeo em HDR (exporte em SDR).

**`container ... ainda em IN_PROGRESS após 300s`.** Vídeo pesado. Suba
`IG_POLL_TIMEOUT`. Nada foi publicado — reexecutar é seguro.

**`limite de publicação quase estourado`.** O job lê `content_publishing_limit`
antes de criar qualquer container e desiste cedo. O teto varia por conta — a
documentação da Meta cita 25, e a conta da loja devolveu **100**. Por isso o
código nunca assume um número: usa o `quota_total` que a API responde.

**`token do Instagram: token INVÁLIDO`.** Renove à mão
(`python -m poster.cli refresh-token`) e confira se `GH_SECRETS_TOKEN` não
expirou. Token da Meta invalidado (troca de senha, revogação de permissão da
Página) exige refazer o fluxo de login no app Meta e regravar `IG_ACCESS_TOKEN`.

**Publicação falha só nesta Página, com mensagem de permissão.** Suspeite de PPA
pendente. Não há como detectar por API; confirme no Business Suite.

## Riscos que valem revisita

| Risco | Mitigação já no código | O que ainda é humano |
|---|---|---|
| Token expira em silêncio | renovação mensal + validade logada a cada publicação + alerta a 7 dias | conferir que o PAT `GH_SECRETS_TOKEN` não expirou |
| Post com preço antigo | `reviewed_price` obrigatória | conferir o preço de fato |
| Mídia duplicada entrega pior | `repeat_after_days` por item | legenda nova, corte diferente, áudio atual |
| Bucket público expõe acervo | — | nome de arquivo com hash, ou migrar para resumable |
| Falha silenciosa do Actions | alerta em toda falha + exit code | ausência de post não é detectável sozinha: o alerta é obrigatório |

## Limites e depreciações da API

- **Limite de publicações por 24h** lido de `content_publishing_limit`. A Meta
  documenta 25; a conta da loja devolve 100. Confie no valor da API, não no doc.
- **Container expira em 24h** — por isso nada é criado adiantado para publicar
  depois. Cada execução cria e publica no mesmo run.
- **Carrossel**: 2 a 10 itens.
- **Caption**: 2.200 caracteres, 30 hashtags, 20 menções.
- `impressions` foi depreciada em media insights (v22+, erro para mídia criada
  após 02/jul/2024), junto com `plays`, `clips_replays_count` e `video_views`.
  `views` a substitui, mas **só para mídia criada a partir de ~jul/2024** — daí o
  ranking universal usar apenas `like_count` e `comments_count`.
- Posts com tag de produto do Instagram Shopping não aparecem em
  `ads_get_ig_media` (conector de anúncios), mesmo sendo do próprio perfil.

## Onde a mídia pode morar

A Graph API busca a URL que você informa. Nem todo host serve — e o erro que ela
devolve não diz qual é o problema. O que já foi testado nesta conta:

| Origem | Funciona | Observação |
|---|---|---|
| `cdn.jsdelivr.net/gh/<owner>/<repo>@<branch>/<caminho>` | ✅ | é o que `poster rehost` gera; espelha o repositório público e serve com o tipo declarado |
| `raw.githubusercontent.com` | ❌ | serve `.mp4` como `application/octet-stream` com `nosniff` |
| `source_media_url` da própria API | ❌ | entrega para player, assinada; falha com `2207076` e expira em horas |
| Bucket (R2, S3) | ✅ | destino de operação — o repositório guarda histórico para sempre |
| GitHub Pages | ✅ esperado | serve com o tipo certo; exige ligar em Settings → Pages |

Antes de culpar o arquivo, confira o tipo que o host devolve:

```bash
curl -sI <url> | grep -i content-type
```

`video/mp4` ou `image/jpeg` é o que se espera. `application/octet-stream` com
`nosniff` é motivo suficiente para a recusa.

## Backfill do acervo

São milhares de posts: não saem numa execução. `curate` pagina com cursor persistido
em `state/catalog.json` e continua de onde parou a cada disparo. Rode com
`max_pages` alto algumas vezes ao longo de alguns dias; depois disso a coleta é
incremental. Os campos vêm todos numa requisição só (*field expansion*) para
gastar menos chamadas.

## Migrar para upload resumable (opcional)

O que muda é só a criação do container: em vez de mandar `image_url`/`video_url`
para a Graph API buscar, você inicia uma sessão de upload e envia os bytes. O
polling, o `media_publish`, a fila e o estado continuam iguais — o ponto de
alteração é `create_container()` em `poster/publisher.py`. Ganho: acaba o bucket
público e o risco de expor o acervo. Custo: mais código e mais coisa para depurar.
Só vale quando o bucket incomodar.

## Custo

| Item | Custo |
|---|---|
| Graph API | R$ 0 |
| Bucket (R2, acervo pequeno) | ~R$ 5–15/mês |
| GitHub Actions | R$ 0 (free tier) |
| **Total** | **< R$ 20/mês** |
