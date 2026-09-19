# Contexto para retomar o projeto

Escrito em 19/09/2026, no fim da primeira maratona de implementação. O objetivo
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

## 2. Estado em 19/09/2026

Funcionando ponta a ponta:

- Token de longa duração válido até **17/11/2026**, com renovação automática
  mensal que regrava o próprio secret.
- Acervo de **135 posts** ranqueado em `state/catalog.json`.
- Caixa de entrada do Drive importando fotos e convertendo PNG/WebP em JPEG.
- **11 fotos** em `queue/stories.yaml`, **3 stories publicados** (1 teste em
  18/09, 2 reais em 19/09).
- Coletor de métricas de story rodando de hora em hora.
- Vigia de silêncio no ar, com alarme já testado de verdade (issue #6).
- **253 testes**, nenhum toca a rede.

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

### O vigia lê a agenda, não a copia

`poster/vigia.py` lê os horários do próprio `publicar-stories-auto.yml`. Se
copiasse, sairia de sincronia e passaria a cobrar um horário que ninguém usa —
em silêncio, que é exatamente o defeito que ele existe para pegar.

---

## 4. A restrição que molda tudo: o cron do GitHub atrasa horas

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

Por que 3-4h aqui, quando o relatado comum são minutos: **não sei**, e não dá
para descobrir de fora. Uma versão anterior deste texto culpava despriorização
de runner em repo público — a medição de fila 0s desmentiu.

**Consequências que já estão no código:**

- Os horários do cron são de **disparo**, não de publicação. Estão adiantados
  ~4h: `34 16 * * *` (13h34 BRT) e `34 20 * * *` (17h34 BRT), para o story sair
  entre 16h54-18h08 e 20h54-22h08.
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

- **Primeiro disparo com o minuto 34** é 20/09 às 13h34. Ainda não se sabe se
  ajuda no atraso.
- **Issue #6** (`[teste] Story não publicado`) é o ensaio do alarme e pode ser
  fechada.
- **Issue #2** tem os 15 candidatos da curadoria esperando aprovação humana.
  Nada foi republicado do acervo ainda.
- **`publish.yml` ainda tem cron próprio** (`0 13 * * *`) apontando para
  `queue/posts.yaml`, que está vazia. Não faz nada hoje, mas vai publicar
  sozinho no dia em que alguém aprovar um item para lá. Decidir se é isso mesmo.
- **`online_followers` não devolve dado** para esta conta. A métrica foi
  descontinuada para parte das contas.
- **Um story por dia em vez de dois** — recomendado pelos dados, não decidido.
- **Heartbeat dos 60 dias:** o GitHub desativa workflows agendados após 60 dias
  sem atividade no repositório. Ainda não há proteção contra isso.

---

## 8. Como mexer

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -t .    # 253 testes, nenhum usa rede
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
