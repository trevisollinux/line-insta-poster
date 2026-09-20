# Feed e Reels — análise do acervo

LINE STORE · 135 posts de 19/09/2025 a 17/09/2026 · escrito em 20/09/2026

Fonte: `state/catalog.json`, coletado pela curadoria em 18/09/2026. Todos os
135 posts devolveram `views`, `reach`, `saved`, `shares` e `total_interactions`
pela Graph API — post de feed não expira como story, então a série inteira do
ano está disponível.

Leia junto com `docs/analise-stories.md`, que cobre o outro canal.

---

## 1. O tamanho da operação

| | |
|---|---|
| Posts no ano | 135 (11,2/mês · 2,6/semana) |
| Alcance somado | 138.084 |
| Views somadas | 188.220 |
| Salvamentos | 2.148 |
| Compartilhamentos | 415 |
| Curtidas / comentários | 4.316 / 262 |

O post mediano: **1.238 views, 982 de alcance, 40 interações, 27 curtidas,
1 comentário, 9 salvamentos.**

Taxa de engajamento (interações ÷ alcance): **4,12 %** na mediana. Nos últimos
60 dias, 4,07 % — estável.

Distribuição, para saber o que é normal e o que é exceção:

| Métrica | p25 | mediana | p75 | máximo |
|---|---|---|---|---|
| views | 916 | 1.238 | 1.648 | 9.651 |
| reach | 795 | 982 | 1.209 | 4.165 |
| interações | 23 | 40 | 63 | 709 |
| salvamentos | 4 | 9 | 18 | 328 |

Por formato:

| Formato | n | views (med.) | reach (med.) | interações | saves |
|---|---|---|---|---|---|
| REELS | 113 | 1.152 | 982 | 38 | 8 |
| FEED (foto/carrossel) | 22 | 1.990 | 1.048 | 45 | 14 |

O `views` mais alto do feed engana: em foto, uma "view" é impressão; em reel é
reprodução. O alcance, que é comparável, fica praticamente igual — 982 contra
1.048.

## 2. O feed alcança 7,3× mais que o story

| Canal | Alcance mediano |
|---|---|
| Story | 134 |
| Feed / Reels | 982 |

É a comparação mais importante deste arquivo. Story fala com quem já segue e
abre stories; reel recebe distribuição para quem não segue.

A automação inteira construída até agora atende o canal de 134. Isso não é
argumento para desligá-la — ela custa zero e funciona —, é argumento sobre onde
colocar esforço de produção e de otimização.

## 3. Horário não importa aqui também

| Faixa | n | reach (med.) |
|---|---|---|
| Manhã 6–12h | 14 | 874 |
| Tarde 12–18h | 61 | 979 |
| Noite 18–24h | 60 | 1.018 |

| Dia | n | reach | | Dia | n | reach |
|---|---|---|---|---|---|---|
| seg | 31 | 1.036 | | sex | 16 | 1.014 |
| ter | 17 | 898 | | sáb | 10 | 999 |
| qua | 30 | 1.048 | | dom | 7 | 977 |
| qui | 24 | 964 | | | | |

De 898 a 1.048 — 17 % entre o melhor e o pior dia, com amostras de 7 a 31. É
ruído. Mesma conclusão dos stories, por dois caminhos independentes:
**horário e dia não são a alavanca.**

## 4. O que separa o topo do fundo

Os cinco maiores:

| Post | reach | interações | saves |
|---|---|---|---|
| "Juniper 3 em 1 🥰" (reel) | 4.165 | 709 | 328 |
| "#readytogo" (reel) | 3.989 | 274 | 126 |
| "Qual cor combina mais com nossa Baguette?" | 2.959 | 219 | 80 |
| "Tour pela nossa mochila Wanderlust" | 2.144 | 147 | 50 |
| "Nosso reajuste está chegando 🤎 Até 16/08…" | 1.599 | 65 | 16 |

Os cinco menores têm legenda `"💞"`, vazia, `"Juniper Bag 🏵️"`, `"Mini ❤️"` —
entre 46 e 79 views.

Quatro padrões, nenhum deles sobre agenda:

1. **Versatilidade demonstrada.** "3 em 1" fez 328 salvamentos: **7,9 % de quem
   viu salvou**, contra 0,87 % da mediana da conta. Nove vezes.
2. **Pergunta na legenda.** "Qual cor combina mais?" gerou 219 interações
   contra mediana de 40. O segundo post de pergunta ("Qual é a sua cor
   favorita?") também entrou nos candidatos da curadoria.
3. **Tour do produto.** Dois "tour pela mochila", 50 salvamentos cada.
4. **Urgência com data.** O post de reajuste com prazo.

## 5. O salvamento é o sinal de compra

Para loja de bolsa, salvar é "quero essa, volto depois" — é a métrica mais
próxima de intenção que a API dá sem site instrumentado.

Mediana: 0,87 % do alcance. Melhor caso: 7,9 %.

**131 dos 135 posts têm legenda com menos de 80 caracteres**, e a mediana de
comentários é 1. Não há chamada para ação, preço, nem menção ao link da bio em
praticamente nenhum. É a correção mais barata que existe aqui: é texto, não
produção.

Hashtags: com elas, alcance mediano 1.077 contra 912 (+18 %) e interações 46
contra 37 (+24 %). Amostra desbalanceada (38 contra 97) e sem controle de
conteúdo — indício, não prova. Mas custa zero.

## 6. A armadilha que quase virou conclusão errada

A tabela por mês mostrava setembro/2026 despencando: 567 views medianas contra
1.200–1.450 dos outros meses. Parecia queda de 50 % no alcance da conta.

Está errado. A coleta é **uma foto única**, tirada em 18/09: o post de setembro
tinha dias de vida, o de outubro passado tinha um ano. Separando por idade:

| Idade na coleta | n | views (med.) | reach (med.) |
|---|---|---|---|
| 0–15 dias | 5 | 567 | 444 |
| 16–30 dias | 2 | 1.176 | 799 |
| 31–90 dias | 10 | 1.321 | 1.059 |
| 91–180 dias | 43 | 1.119 | 1.019 |
| 180+ dias | 75 | 1.264 | 1.026 |

**Reel amadurece em 2 a 3 semanas e depois para.** Setembro não caiu — é novo.
E de quebra: post de um ano não rende mais que post de um mês, ou seja, não
existe cauda longa relevante depois do primeiro mês.

Qualquer comparação entre meses usando esta coleta está contaminada por idade.
Para medir tendência de verdade são precisas **duas coletas** do catálogo em
datas diferentes — hoje a curadoria sobrescreve o arquivo a cada rodada.

## 7. O que fazer

1. **Despachar os 15 candidatos da curadoria** (issue #2). É o canal de 7,3× e
   a mídia já está rehospedada.
2. **Escrever legendas.** Pergunta + característica + chamada para o link da
   bio. Hoje não existe nenhuma.
3. **Produzir mais "3 em 1" e "tour".** É o formato com 9× a taxa de
   salvamento da conta — mostra a peça resolvendo mais de um uso.
4. **Hashtag sempre.**
5. **Parar de otimizar horário**, nos dois canais.

## 8. O que falta para esta análise melhorar

- **`follower_count`.** Sem ele não dá para dizer se 982 de alcance é bom ou
  ruim para o tamanho da conta. É o buraco que mais atrapalha aqui.
- **`website_clicks` e `profile_views` por dia.** São a ponte entre "alcance" e
  "alguém foi ver a loja". Sem link em story, esse é o único caminho medido.
- **Duas coletas do catálogo**, pela seção 6.

## 9. Ressalvas

Tudo aqui é observacional: o conteúdo não foi controlado, quem escolheu o que
postar escolheu com critério próprio, e as comparações de legenda e hashtag
sofrem do mesmo problema — quem escreve legenda melhor provavelmente também
escolhe foto melhor.

O que é sólido: as distribuições, a comparação de alcance entre canais, a
achatada dos horários e o efeito da idade na seção 6. O que é indício: hashtag,
formato de legenda e o padrão dos quatro tipos de post campeão.
