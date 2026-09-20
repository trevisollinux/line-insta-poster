# Runbook

## Rotina normal

| Workflow | Quando | O que faz |
|---|---|---|
| Publicar no Instagram | diário, 10h BRT | publica um item e commita o estado |
| Publicar Stories (automático) | disparo 13h34 e 17h34 BRT; sai ~4h depois | publica um story de `queue/stories.yaml`, sem aprovação |
| Renovar token | dia 1, 6h BRT | renova o long-lived token e regrava o secret |
| Curadoria do acervo | dia 1, 8h BRT | ranqueia o acervo e abre PR com candidatos |
| Capturar métricas dos stories | de hora em hora | lê os stories no ar e grava em `state/stories_metrics.csv` e `state/stories_curva.csv` |
| Vigia dos stories | de hora em hora | abre issue quando o dia passou sem o story esperado |
| Testes | push e PR | suíte + validação da fila versionada |

Códigos de saída da CLI: `0` sucesso, `1` falha (com alerta), `2` nada a fazer.
O workflow de publicação trata `2` como aviso, não como falha — fila vazia não é
erro, mas aparece no Summary do run.

### Post de feed pela pasta `Feed/`

Mídia na subpasta `Feed/` não vira story: vira item de `queue/posts.yaml`.
Vídeo entra como REELS, imagem como IMAGE — o tipo sai do arquivo.

A legenda vai num arquivo de texto **com o mesmo nome da mídia**
(`bolsa.jpg` + `bolsa.txt`). Documento do Google também serve: o importador
exporta o texto. Texto cujo nome não bate com nenhuma mídia vira aviso no
e-mail, porque quase sempre é erro de digitação — e o sintoma sem o aviso
seria um post publicado sem legenda.

**Se a legenda falar de preço, a primeira linha do texto precisa ser `preço
conferido`** para o post poder ir ao ar. Sem ela o item entra na fila com
`reviewed_price: false` e fica parado. Valem também `preco ok`, `preço
conferido: sim` e variações — sem acento e em qualquer caixa.

**Legenda sem preço não precisa da marca.** Nem todo post traz valor, e sem
preço não há o que conferir. Exigir a marca sempre transformaria a conferência
em ritual, e ritual vira hábito: a pessoa marca sem olhar, inclusive nos posts
que realmente têm preço.

O gatilho é o **número**, não o assunto. Conta como preço: `R$ 890`,
`890,00`, `890 reais`, `6x de 148`, `preço: 890`, `por 890`, `a partir de 690`.

**Não** conta: "valor no direct", "consulte o preço na bio", "à vista com
desconto" — falam de preço sem trazer número, e o que envelhece é o número.
São as legendas mais comuns quando a peça não vai com valor publicado, e é por
isso que elas passam direto.

Também não alcança preço escrito por extenso ("oitocentos e noventa") nem preço
queimado dentro da imagem; disso nenhuma validação dá conta.

Só a primeira linha conta. Uma legenda que mencione "preço ok" no meio do
texto **não** aprova nada: a trava é a única coisa entre um reajuste e um
preço velho no perfil, e post de feed não some em 24h como story.

A importação reescreve `queue/posts.yaml` para acrescentar item novo. Os itens
que já estavam lá são preservados; comentário escrito no meio da lista, não.

### Horários da importação

A importação roda duas vezes por dia, mirando **9h e 17h**. Os crons estão em
05h00 e 13h00 BRT porque são horários de disparo, com o mesmo adiantamento de
~4h dos stories: a foto entra na fila entre 08h20-10h24 e 16h20-18h24.

Importar não publica nada — só enche `queue/stories.yaml`. Quem publica são os
horários dos stories.

### Tipo de conteúdo pelas subpastas do Drive

O nome da subpasta onde a foto está vira o campo `tipo` do item (`Bastidor da
Oficina` → `bastidor-da-oficina`). Foto largada na **raiz** entra sem tipo e
publica igual — só não participa da comparação de qual conteúdo rende.

É um nível só de profundidade. `bastidor/setembro/foto.jpg` não é importada:
melhor não importar do que rotular como "setembro".

O tipo viaja do rascunho para `state/published.json`, que é o que sobra depois
que a fila esvazia — é por ele que se liga o `media_id` medido pela API ao tipo
de foto que era.

Por que isto existe: horário e posição no dia mexem 10-15%; o tipo de conteúdo
mexeu 5x (891 views de um bastidor contra 147-170 das fotos de produto). Sem o
rótulo, o único fator que importa de verdade é invisível para a análise.

### Métricas da conta

`state/conta.csv` guarda um dia por linha: seguidores, publicações, alcance,
visitas ao perfil, cliques no link da bio e contas engajadas. É a régua que
faltava — sem saber o tamanho da conta, 982 de alcance não quer dizer nada.

Roda uma vez por dia e pede **7 dias** de janela. Isso é o que torna a
frequência baixa suficiente: a captura que o agendador descartar hoje se
conserta amanhã sozinha. O oposto do coletor de story, onde o que não for lido
enquanto está no ar está perdido — e é por isso que aquele roda de hora em
hora e este não precisa.

Duas armadilhas que estão resolvidas no código, com teste:

- **`end_time` é o fim da janela, não o dia.** `2026-09-20T07:00:00+0000`
  fecha o dia **19**. Sem o desconto, a série inteira fica um dia à frente.
- **Seguidores entram só na data mais recente.** Carimbar a contagem de hoje
  nos 7 dias da janela inventaria um histórico estável que ninguém mediu.

Na mesclagem vale a **leitura mais recente**, não a maior — ao contrário das
métricas de story. Seguidor pode cair, e leitura do meio do dia é parcial de
propósito.

Se alguma métrica não existir para esta conta, a API recusa o pedido inteiro
citando o nome dela; o código tira a recusada e tenta de novo, em vez de perder
as outras junto.

### O ponto zero da curva

Além do coletor de hora em hora, o próprio run que publica captura as métricas
logo depois de o story entrar no ar. Esse ponto é o único que não depende do
agendador — e o agendador entrega 25% das ocorrências, então a primeira leitura
de um story podia chegar horas depois.

Não duplica: a curva é indexada por (story, idade em horas arredondada) e a
tabela tem uma linha por story, ficando sempre com o maior valor lido. Uma
captura do coletor na mesma hora cai na mesma linha.

Se essa captura falhar, o job da publicação **não** fica vermelho: o story já
está no ar e já foi gravado, e um e-mail dizendo que a publicação falhou faria
alguém procurar problema onde não tem. Fica um aviso no log, e o coletor de
hora em hora pega o story depois.

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

## O cron deste repositório atrasa horas

Não é suposição. Medido em quatro execuções agendadas reais:

| Cron | Previsto | Rodou | Atraso |
|---|---|---|---|
| `0 13 * * *` | 13:00 | 17:34 | 4h34 |
| `0 13 * * *` | 13:00 | 17:00 | 4h00 |
| `0 13 * * *` | 13:00 | 16:20 | 3h20 |
| `0 12 * * *` | 12:00 | 15:45 | 3h45 |

### Onde o tempo é perdido

Não é falta de runner. Comparando `created_at` com `run_started_at` das mesmas
quatro execuções, a fila do job foi de **0 segundo** em todas: assim que o run
existiu, a máquina estava disponível.

O atraso inteiro está antes disso — o despachante de agendamentos do GitHub
simplesmente cria o run horas depois da hora marcada.

O que o GitHub documenta: o evento `schedule` é *best effort* e pode atrasar em
períodos de carga alta, sendo o início de cada hora o pior momento; sob carga,
uma execução pode até ser descartada, e não apenas adiada.

Medido na noite de 19→20/09: o agendador não é lento, ele **acorda pouco**.
Quando acorda, entrega em 12 a 51 min; o que varia é o intervalo entre
despertares (34 a 352 min nos doze observados). Cron diário espera o próximo
despertar — daí as 3-4h. Cron horário perde todas as ocorrências entre um
despertar e outro: taxa de entrega medida de **25%**.

**Madrugada é pior, não melhor.** Um cron único às 02:23 UTC disparou às 07:47,
**5h24 depois** — o pior atraso da série.

Por que este repositório recebe tão poucos despertares: não sei, e não dá para
descobrir de fora. Uma
primeira versão deste texto atribuía o atraso a despriorização de runner em
repositório público — a medição de fila 0s desmentiu isso, e a explicação foi
removida em vez de reescrita com outro palpite.

Duas observações dos quatro casos, ambas com amostra pequena demais para
concluir: o atraso do cron das 13h vem encolhendo (4h34 → 4h00 → 3h20), e os
dois crons de 19/09, marcados com 1h de diferença, dispararam com 35 min de
diferença — o que parece processamento de fila acumulada, não despertar fixo.

É por isso que o vigia existe. Execução agendada que pode ser descartada em
silêncio não é algo em que se confie sem conferência independente.

**Consequência prática:** o horário no cron é de *disparo*, não de publicação.
Os horários estão adiantados cerca de 4h para compensar:

- `34 11 * * *` → dispara 08h34 BRT → story sai entre 11h54 e 14h
- `34 15 * * *` → dispara 12h34 BRT → story sai entre 15h54 e 18h

Os dois caem na tarde, que é a faixa que rende nos dados (323 views contra 141
da noite). O intervalo de 4h entre eles é requisito: a dispersão da entrega é
de 2h04, e com menos que isso o segundo story poderia sair antes do primeiro.

O minuto 34 é hipótese não confirmada: as execuções medidas estavam todas em
minuto 00, o mais disputado da hora, e um minuto quebrado deve cair fora do
pico.

Isso também explica a tolerância do vigia abaixo, de 5h30. Ela não é frouxidão
— é o tamanho do atraso real mais margem.

## Quando nada acontece

Falha manda e-mail; ausência não. Run que nasce morto (`startup failure`) não
tem job, não tem log e não notifica ninguém — foi assim que o cron de stories
ficou quebrado sem que ninguém percebesse. Cron que não dispara não deixa nem
isso.

O **Vigia dos stories** cobre esse ponto cego. Ele não observa execuções: lê os
horários do próprio `publicar-stories-auto.yml`, conta quantos já venceram hoje
(com 45 min de tolerância, porque o cron do GitHub atrasa por rotina) e compara
com o que está em `state/published.json`. Faltando algum, abre uma issue — que
chega por e-mail. O título carrega a data, então 24 execuções por dia dão no
máximo uma issue.

Ele lê a agenda em vez de repetir os horários porque agenda duplicada sai de
sincronia: o vigia passaria a cobrar um horário que ninguém mais usa, e faria
isso em silêncio — exatamente o defeito que ele existe para pegar.

Mora num workflow separado do coletor de métricas de propósito. Se morasse
junto, um problema no coletor derrubaria justamente quem deveria perceber que
algo parou.

### O aviso de fila acabando

O mesmo workflow do vigia confere quantas fotos ainda podem sair e abre issue
quando restam **4 ou menos** — dois dias de folga no ritmo de dois por dia.

Por que antes e não depois: com a fila seca, o vigia normal passa a abrir uma
issue por dia dizendo que o story não saiu, todo dia, até alguém abastecer.
Este aviso existe para essa sequência nunca começar.

A contagem usa a elegibilidade de `selection`, a mesma do publish. Contar
linhas do arquivo daria um número folgado com a fila já seca, porque o
publicado continua lá.

### Testar o alarme

Actions → *Vigia dos stories* → *Run workflow* → **simular: true**. Abre uma
issue com `[teste]` no título, que pode ser fechada na hora.

Vale repetir isso de vez em quando. Alarme que nunca tocou é alarme em que não
dá para confiar, e a parte que quebra calada não é a conta — é o caminho que
cria a issue. Descobrir que ele parou de funcionar no dia do incidente é
descobrir tarde demais.

### Recuperação: o story que faltou

Em 20/09 nenhum dos dois disparos de story virou execução, e o dia terminaria
com um story só. O vigia percebe e avisa — mas avisar não publica, e automação
que depende de alguém abrir o Actions no fim do dia não é automação.

O workflow **Recuperar story do dia** dispara às 18h BRT (cron `0 21 * * *`) e
publica **só se o dia estiver devendo**: se já saíram os dois, ele sai sem
fazer nada. O limite vem de `max_por_dia`, que a fila do publish respeita.

Mora em arquivo separado de propósito. O vigia lê os horários de
`publicar-stories-auto.yml` para saber quantos stories o dia devia ter; um
terceiro cron ali dentro o faria cobrar três por dia, todo dia — o alarme
viraria ruído diário, que é o defeito que ele existe para não ter. Há teste
ligando o limite da recuperação ao tamanho daquela agenda.

Com o atraso de 3h20 a 5h24, a recuperação sai à noite. Hora ruim é melhor que
hora nenhuma. Se passar da meia-noite, ela conta para o dia seguinte — é o
preço de não haver horário confiável.

### O GitHub desativa cron parado — e o heartbeat

Depois de **60 dias sem atividade no repositório**, o GitHub desativa os
workflows agendados de repositório público. Desativa calado: o cron para de
disparar e não sobra rastro. Levaria junto o próprio vigia, e o sistema
inteiro ficaria mudo parecendo saudável — a pior falha possível aqui.

O workflow **Heartbeat** pulsa segunda e quinta: grava a data em
`state/heartbeat.txt` e empurra o commit, zerando o contador. Duas vezes por
semana, e não uma vez por mês, porque o agendador descarta ocorrências — pulso
marcado não é pulso dado. Mesmo perdendo a maioria, sobra folga dentro dos 60
dias.

**O que aqui é hipótese, não medição:** o commit sai como
`github-actions[bot]`. Não está verificado que commit de bot conte como
atividade para esse contador — há relato de que só push de pessoa conta. Se não
contar, o repositório já estaria em risco hoje, porque tudo o que ele recebe
são commits de bot.

Por isso o segundo passo do heartbeat confere pela API se algum workflow está
`disabled_inactivity`, reativa e abre issue. É essa issue que responde a
pergunta: se ela aparecer, commit de bot não conta, e a saída é um PAT com
Contents RW só deste repositório para o pulso sair como pessoa.

O limite, dito de frente: se **todos** os agendados forem desativados de uma
vez, o heartbeat morre junto e não sobra ninguém para reativar. Aí é manual —
aba Actions, botão de reativar. Nenhuma automação dentro do GitHub cobre esse
caso.

**Ensaiar o alarme:** Actions → *Heartbeat* → *Run workflow* → **simular:
true**. Abre uma issue com `[teste]` no título e **não reativa nada** — ensaio
que mexe em workflow de verdade poderia desfazer um `disabled_manually` de
alguém. Vale repetir de vez em quando, pela mesma razão do vigia: o caminho que
abre a issue só roda no dia do problema.

## O resumo da semana

Toda segunda de manhã, uma issue com o que aconteceu: stories publicados,
views (mediana, mínimo, máximo e **n**), melhor e pior do período, desempenho
por tipo de conteúdo, o estado da conta com a variação da semana, e quantas
fotos sobraram na fila.

É o contrário do vigia. Ele avisa quando algo quebrou; este conta o que
aconteceu quando nada quebrou — informação que hoje some, porque fica em CSV e
CSV ninguém abre de segunda de manhã.

**Regra que atravessa o relatório: nenhum número sai sem o tamanho da amostra
ao lado.** Uma semana tem 10 a 14 stories; mediana de 3 não é tendência, e
escrever como se fosse é a forma mais barata de alguém decidir errado com cara
de dado. A tabela por tipo traz o `n` em coluna própria, e há teste exigindo
isso.

Segunda de manhã de propósito: é quando ainda dá para mudar a semana. Resumo
na sexta informa sobre uma semana que já acabou.

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
| Cron desativado após 60 dias sem atividade | heartbeat 2x/semana + reativação pela API | se todos os agendados caírem juntos, reativar na mão na aba Actions |

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
