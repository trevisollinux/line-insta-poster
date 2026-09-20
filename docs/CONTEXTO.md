# Contexto para retomar o projeto

Escrito em 19/09/2026 e atualizado em 20/09 de manhã, depois da noite de
medição do agendador do GitHub. O objetivo
é que outra sessão (ou outra pessoa) consiga continuar sem reconstruir o
raciocínio do zero. Prioriza o **porquê** das decisões — o *o quê* está no
código, e o código não explica sozinho por que não foi feito do jeito óbvio.

Leia junto com `README.md` (o que o sistema é) e `docs/OPERACAO.md` (runbook).

---

## 1. O que é

Automação de publicação no Instagram da LINE STORE (@line_store), loja de
bolsas e mochilas de couro. Tudo roda em GitHub Actions; não há servidor.

Dois repositórios, ambos **públicos**:

- **`trevisollinux/line-insta-poster`** — código, filas, estado, workflows.
- **`trevisollinux/line-store-media`** — só arquivos de mídia.

O segundo é público **por necessidade, não por escolha**: quem baixa a mídia é
o servidor da Meta, que não tem credencial nenhuma. Repositório privado
simplesmente não funciona para isso. Se privacidade virar requisito, a resposta
é bucket com URL pré-assinada, não repositório privado.

---

## 2. Estado em 20/09/2026, 09h BRT

Funcionando ponta a ponta:

- Token de longa duração válido até **17/11/2026**, com renovação automática
  mensal que regrava o próprio secret.
- Acervo de **135 posts** ranqueado em `state/catalog.json`.
- Caixa de entrada do Drive importando fotos e convertendo PNG/WebP em JPEG.
- **8 fotos** restantes em `queue/stories.yaml`.
- Coletor de métricas de story no ar — mas com **25% de entrega**, ver a
  ressalva na seção 3.
- Vigia de silêncio no ar, com alarme testado de verdade (issue #6).
- **275 testes**, nenhum toca a rede.

Stories publicados até agora:

| Quando (BRT) | Media | O que foi |
|---|---|---|
| 18/09 12:50 | `17961062295200190` | teste inicial |
| 19/09 17:33 | `17971817322069714` | slot das 16h40, na mão após o bug do `queue` |
| 19/09 18:09 | `18123811351859916` | slot das 18h, na mão |
| 20/09 04:48 | `18111631310156210` | experimento noturno — saiu 5h24 atrasado |

O de 20/09 saiu às 4h48 da manhã porque o cron atrasou 5h24. Publicou certo, em
hora que ninguém vê. Se a métrica dele vier péssima, é o horário, não a foto.

`queue/posts.yaml` (feed/Reels, exige aprovação humana) está **vazio**.

---

## 3. Decisões que não são óbvias

Estas são as que mais custaram a chegar. Mudá-las sem entender o motivo vai
reintroduzir um problema já resolvido.

### jsDelivr, não raw.githubusercontent

A Meta busca a mídia pela URL pública. O `raw.githubusercontent.com` serve
`.mp4` como `application/octet-stream` com `nosniff`, e a Meta recusa. O
jsDelivr (`cdn.jsdelivr.net/gh/owner/repo@branch/caminho`) serve com o tipo
certo. Está em `poster/rehost.py`.

Também não funciona usar o `source_media_url` que a própria API devolve: é link
assinado de player, expira em horas e dá erro 2207076 na publicação.

### A aprovação do preço mora na legenda, não num botão

Post de feed exige `reviewed_price: true`, e a pergunta era onde esse "sim"
acontece. Ficou na primeira linha do arquivo de legenda: `preço conferido`.

Decisão do Gustavo em 20/09, e o argumento é bom: quem escreve o preço é quem
confere o preço, no momento em que escreve, com a peça em mente. Um botão
depois seria uma segunda pessoa confirmando um número que ela não olhou.

Só a primeira linha é lida como marca. Varrer o texto inteiro faria uma legenda
que diz "preço ok" no meio da frase virar aprovação — e a trava é a única coisa
entre um reajuste e um preço velho no perfil, que em feed não expira em 24h.

E a exigência é **condicional à legenda ter preço**, não ao formato. É o mesmo
raciocínio que já dispensava STORIES: a flag protege preço velho na legenda, e
legenda sem preço não tem o que conferir. Exigir sempre viraria ritual, e
ritual vira hábito — a pessoa marca sem olhar, inclusive onde importa.

Três testes do repositório congelavam a regra antiga (formato com legenda
sempre exige). Foram atualizados para dizer a regra nova com o gatilho
explícito na própria chamada, em vez de escondido na fixture.

### O tipo de conteúdo vem da subpasta, não de um formulário

O nome da subpasta do Drive vira o campo `tipo` do item. Podia ser um campo
para alguém preencher; não seria preenchido. A pasta já faz parte do gesto de
subir a foto, e quem ainda não se organizou larga na raiz e publica sem tipo.

Um nível só: `bastidor/setembro/` diria que o tipo é "setembro", e rótulo
errado é pior que rótulo nenhum — a análise sai confiante e falsa.

O tipo é copiado para `state/published.json` no momento da publicação. A fila
é mexida e esvaziada; o estado é o que resta, e é ele que liga o `media_id` que
a API mede ao tipo de foto que era.

### Caixa de entrada ≠ hospedagem

A Lélia sobe fotos numa pasta do Google Drive. O Drive é **caixa de entrada**,
não host: a Meta nunca busca nada lá. O código baixa do Drive e republica no
repositório de mídia, que é de onde a Meta puxa. Separar as duas coisas é o que
permite a pasta do Drive continuar privada.

### STORIES não exige `reviewed_price`

A flag existe para impedir preço velho **na legenda**. Story não tem legenda (a
API não aceita), então exigi-la ali seria burocracia sem proteção. O que a flag
nunca cobriu — preço queimado dentro da imagem — nenhuma validação cobre; story
dura 24h e dá para apagar pelo app. Feed e Reels continuam exigindo.

### Mediana, não média

O score da curadoria é `(curtidas + comentários×7) / mediana da janela de ±45
dias`. Mediana porque um viral isolado não pode decidir o que é "normal" para
aquele mês. Posts excluídos (promoção, últimas peças, reajuste) **continuam na
base da mediana** — eles fizeram parte da época, só não entram como candidatos.

### Só grava o estado depois que publicou

`state/published.json` só recebe o item depois que `media_publish` devolveu um
id. Gravar antes gera post perdido em silêncio: o item sai da fila sem nunca
ter ido ao ar.

### Métricas de story ficam com o MAIOR valor lido

São contadores que só sobem. Valor menor numa captura seguinte é oscilação da
API, não queda de audiência.

### ⚠️ O coletor de hora em hora NÃO garante captura completa

Isto corrige uma afirmação minha que estava errada. Eu disse que rodar de hora
em hora garantiria que nenhum story expirasse sem medição. **Não garante.**

Taxa de entrega medida nas primeiras 16 horas: **4 execuções de ~16 esperadas,
25%**. O GitHub descarta as ocorrências que caem entre um despertar e outro do
agendador, em vez de enfileirá-las.

Consequência prática: um story pode nascer e expirar sem nunca ser lido, e o
buraco no CSV fica indistinguível de um dia sem story. Quem for analisar
`stories_curva.csv` precisa saber que **ausência de linha não significa
ausência de story**.

Continua valendo muito mais que print manual — mas não é a rede de segurança
que eu descrevi.

Medido de novo em 20/09, com 22h de runs: **5 execuções de ~21, 24%** — o
número se sustenta. Os buracos entre capturas foram de 2h34 a **5h04**. Como o
story vive 24h, na prática ele recebe 4 ou 5 leituras, e o cenário de "nasceu e
expirou sem nenhuma medição" exigiria uma seca quatro vezes pior que a pior já
vista. Improvável, não impossível — e o aviso acima continua de pé: buraco no
CSV não é o mesmo que dia sem story.

Desde 20/09 o run que publica captura as métricas logo depois de publicar. Esse
ponto de idade 0 não passa pelo agendador, e é o começo da curva que faltava.

### O vigia lê a agenda, não a copia

`poster/vigia.py` lê os horários do próprio `publicar-stories-auto.yml`. Se
copiasse, sairia de sincronia e passaria a cobrar um horário que ninguém usa —
em silêncio, que é exatamente o defeito que ele existe para pegar.

---

## 4. A restrição que molda tudo: o agendador do GitHub acorda pouco

**Medido, não estimado.** Quatro execuções agendadas reais:

| Cron | Previsto | Rodou | Atraso |
|---|---|---|---|
| `0 13 * * *` | 13:00 | 17:34 | 4h34 |
| `0 13 * * *` | 13:00 | 17:00 | 4h00 |
| `0 13 * * *` | 13:00 | 16:20 | 3h20 |
| `0 12 * * *` | 12:00 | 15:45 | 3h45 |

Comparando `created_at` com `run_started_at`, a fila do job foi **0 segundo**
em todas. Não falta runner: o despachante de agendamentos do GitHub é que cria
o run horas depois. O GitHub documenta que `schedule` é *best effort* e que sob
carga a execução pode ser **descartada**, não só adiada.

### O modelo que explica os números (medido na noite de 19→20/09)

O agendador não é *lento*: ele **acorda pouco e de forma irregular**. Quando
acorda, entrega em 12 a 51 minutos. O que varia é o intervalo entre despertares.

Doze despertares observados, com intervalos de **34 a 352 minutos**. Isso
explica de uma vez os dois comportamentos que pareciam contraditórios:

- **Cron diário** (13:00): o run nasce no primeiro despertar após o horário. Se
  o próximo despertar é às 17:34, o "atraso" é de 4h34. Não é lentidão — é
  espera pelo despertar.
- **Cron horário**: quando o agendador acorda, encontra uma ocorrência recente
  (no máximo 1h atrás), então o atraso *parece* pequeno. Mas todas as horas
  entre um despertar e outro são **descartadas, não enfileiradas**.

**A madrugada não ajuda — piora.** Testado com um cron único às 02:23 UTC
(23h23 BRT): disparou às **07:47 UTC, 5h24 depois**. É o pior atraso já medido
aqui, contra os 3h20-4h34 do horário comercial. E os intervalos entre
despertares na madrugada foram os maiores da série (269 e 352 min).

Por que este repositório recebe tão poucos despertares: **não sei**, e não dá
para descobrir de fora. Uma versão anterior deste texto culpava despriorização
de runner em repo público — a medição de fila 0s desmentiu.

**Consequências que já estão no código:**

- Os horários do cron são de **disparo**, não de publicação. Estão adiantados
  ~4h: `34 11 * * *` (08h34 BRT) e `34 15 * * *` (12h34 BRT), para o story sair
  entre 11h54-14h e 15h54-18h — os dois dentro da tarde, que é a faixa que
  rende. A agenda anterior (13h34 e 17h34) jogava o segundo para 20h54-23h.
- **As 4h entre um disparo e outro são requisito, não estética.** A dispersão
  da entrega é de 2h04; com intervalo menor, o segundo story pode sair antes do
  primeiro — e a ordem importa, porque o segundo do dia fica em ~84% do
  primeiro.
- O minuto 34 é hipótese não confirmada: as quatro medições estavam todas em
  minuto 00, o mais disputado. Pode não mudar nada.
- A tolerância do vigia é de 5h30. Não é frouxidão — é o pior atraso medido
  mais margem.

**Minutos de Actions em repositório público são ilimitados e gratuitos.** O
limite de 2.000 min/mês é só para repositório privado. Frequência não custa.

---

## 5. Bugs já encontrados — não reintroduzir

Cada um destes tem teste de regressão. Se um teste parecer arbitrário, é
provavelmente um destes.

1. **`inputs.queue` usado sem ser declarado** em `publish.yml`. Passar input
   não declarado para workflow reutilizável é `startup_failure`: o run nasce
   morto, sem job, sem log e **sem e-mail de falha**. O cron de stories ficou
   quebrado um dia inteiro parecendo que não disparava.
2. **`git diff --quiet` não enxerga arquivo novo.** A curadoria coletou 135
   posts, escreveu os candidatos e descartou tudo continuando verde. Sempre
   `git add` antes de `git diff --cached --quiet`.
3. **Heredoc dentro de `run:`** encerrava o bloco YAML e o workflow nascia
   morto. Corpo de issue grande vai em arquivo separado com `--body-file`.
4. **Comparar hora do dia em vez de data completa** em `vigia.horarios_vencidos`.
   Com tolerância de horas, `agora - folga` cai no dia anterior de madrugada; às
   2h da manhã o vigia acusaria todos os horários de um dia que mal começou.
5. **Workflow citando caminho que o código renomeou** (`queue/drafts.yaml` →
   `queue/stories.yaml`). Há teste que compara caminhos citados nos workflows
   com os que o código usa.
6. **`max()` em sequência vazia** no comando de audiência: a API responde 200
   com série vazia quando não há dado.
7. **Teste acoplado à fila viva** do repositório — quebrou quando o primeiro
   item real entrou. Teste usa fixture própria.
8. **Testes presos a relógio fixo.** As classes do vigia quebraram duas vezes
   ao mexer na agenda e na tolerância, com o código correto nas duas. Agora os
   horários dos casos são calculados a partir da agenda mais `TOLERANCIA_MIN`.

---

## 6. O que descobrimos sobre o conteúdo

De 24 prints do Insights (16 medições únicas) mais 2 leituras pela API.
Análise completa em `docs/analise-stories.md`; dados brutos em
`dados/stories-prints.csv`.

Esses arquivos cobrem 24/08 a 05/09, período que **a API não devolve mais**:
story expira em 24h e não há endpoint que traga de volta. Os prints são a única
fonte que existe para essas datas, e por isso estão versionados.

1. **Posição no dia é o efeito mais forte.** 11 de 12 transições dentro do
   mesmo dia foram queda; o 2º story fica em ~84% do 1º (mediana). Em 30/08,
   cinco stories caíram de 267 para 171 com 4h30 de intervalo — se fosse
   horário, teria oscilado.
2. **Horário: tarde ganha, 21h perde.** Entre os primeiros do dia: manhã 183
   views / 6,5 atividades; tarde 323 / 11; noite 141 / 1. Oito medições — é
   indício, não conclusão.
3. **Conteúdo pesa mais que horário e posição juntos.** Dois stories de
   bastidor/cliente fizeram 891 e 721 views com 24 atividades de perfil cada,
   contra 114-378 views e 0-9 atividades do resto. É o único fator com efeito
   grande.
4. **Visualização engana.** Um story com 174 views levou 9 pessoas ao perfil;
   outro com 260 levou 5. Atividade do perfil é o que vira venda.

**Cuidado ao misturar fontes:** `profile_visits` da API **não** é a mesma coisa
que "atividade do perfil" do app, que soma visitas + cliques em link + seguidas.

---

## 7. Coisas em aberto

- **O minuto 34 ainda não foi avaliado.** O primeiro disparo é 20/09 às 13h34
  BRT (16h34 UTC). Pelo modelo dos despertares, é improvável que o minuto
  importe: o que decide é quando o agendador acorda, não em que minuto a
  ocorrência estava marcada.
- **Horário de publicação previsível não é possível com cron do GitHub.** A
  medição fechou essa porta. Se virar requisito, a saída é um gatilho externo
  chamando `workflow_dispatch` pela API na hora certa — o que exige guardar um
  token fora do GitHub, e essa é uma decisão de segurança do Gustavo, não
  técnica. Não foi decidido.
- **Issue #6** (`[teste] Story não publicado`) é o ensaio do alarme e pode ser
  fechada.
- **Issue #2** tem os 15 candidatos da curadoria esperando aprovação humana.
  Nada foi republicado do acervo ainda.
- **`publish.yml` ainda tem cron próprio** (`0 13 * * *`) apontando para
  `queue/posts.yaml`, que está vazia. Não faz nada hoje, mas vai publicar
  sozinho no dia em que alguém aprovar um item para lá. Decidir se é isso mesmo.
- **`online_followers` não devolve dado** para esta conta. A métrica foi
  descontinuada para parte das contas.
- **Um story por dia:** descartado em 20/09. A medição pela API mostrou que o
  2º story entrega 87% do 1º na mesma idade — soma, não canibaliza. Cortar só se
  alguém medir que o 1º rende mais nos dias sem 2º, o que nunca foi feito.
- **Heartbeat dos 60 dias:** resolvido pela metade, de propósito. O workflow
  `heartbeat.yml` pulsa segunda e quinta (commit em `state/heartbeat.txt`) e
  confere pela API se algum agendado caiu por inatividade, reativando e abrindo
  issue. **O que não está verificado:** que commit de bot conte como atividade
  para o contador dos 60 dias — há relato de que só push de pessoa conta, e a
  issue do heartbeat é o que vai responder isso. Se ela aparecer, a saída é um
  PAT com Contents RW só deste repositório. E se todos os agendados forem
  desativados de uma vez, o heartbeat cai junto: recuperação manual na aba
  Actions.

---

## 8. Como mexer

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -t .    # 275 testes, nenhum usa rede
python -m poster.cli validate                # valida a fila, sem rede
python -m poster.cli publish --dry-run       # escolhe sem publicar
python -m poster.cli watch-stories --simular # ensaia o alarme
```

Testar o alarme pelo celular: Actions → *Vigia dos stories* → *Run workflow* →
`simular: true`. Abre issue com `[teste]` no título, que pode ser fechada na
hora.

**Secrets** (todos em `line-insta-poster`, onde os workflows rodam — nunca no
repositório de mídia):

| Secret | Para quê |
|---|---|
| `IG_USER_ID`, `IG_ACCESS_TOKEN` | Graph API |
| `META_APP_ID`, `META_APP_SECRET` | renovação do token |
| `GH_SECRETS_TOKEN` | regravar o `IG_ACCESS_TOKEN` (escopo: Secrets RW) |
| `GH_MEDIA_TOKEN` | escrever no repo de mídia (escopo: Contents RW) |
| `GDRIVE_SERVICE_ACCOUNT`, `GDRIVE_FOLDER_ID` | caixa de entrada do Drive |
| `IG_ALERT_WEBHOOK` | opcional, hoje vazio |

Os dois PATs são separados de propósito: cada um com o escopo mínimo, em vez de
um token que faz tudo.

**Nunca** colar token, app secret ou o JSON da conta de serviço em chat. O JSON
é chave privada: se vazar, regerar na hora.

---

## 9. Onde eu errei, para não repetirem

- Disse que o atraso do cron era fila de runner despriorizada. Era palpite; a
  medição de fila 0s desmentiu.
- Disse que os dois crons de story estavam funcionando quando nunca tinham
  publicado nada — o `startup_failure` não gera e-mail e eu não conferi.
- Escrevi um teste de regressão que **não pegava** o bug que ele deveria pegar
  (somava `workflow_call` com `workflow_dispatch`, e o GitHub valida só o
  primeiro). Só apareceu porque reintroduzi o bug de propósito para conferir.
  **Reintroduza o bug para validar o teste; não confie no verde.**
- Em certo momento parti para fotos do catálogo do site quando o pedido era
  republicar posts que já funcionaram no Instagram.
- Afirmei que o coletor de hora em hora garantiria que nenhum story expirasse
  sem medição. A taxa real é de 25%. Ver a ressalva na seção 3 — é o tipo de
  garantia falsa que faz alguém confiar num dado incompleto meses depois.
- Desenhei o experimento do cron noturno com um disparo único (`23 2 20 9 *`),
  que casa com um minuto do ano. Se o GitHub tivesse perdido a janela, não
  mediria nada e eu não saberia distinguir de "ainda não acordou". Deu certo
  por sorte. **Para medir agendamento, use cron recorrente: várias chances.**
