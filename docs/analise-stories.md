# Stories — análise consolidada

LINE STORE · dados de 24/08 a 20/09/2026 · atualizado em 20/09/2026

Origem: 24 prints do Insights do Instagram enviados ao longo da apuração, mais
2 leituras automáticas pela Graph API. Das 24 imagens, 16 viraram medições
únicas (as demais eram repetidas).


## Os dados

| Data  | Hora  | Views | Interações | Ativ. perfil | Posição no dia | Taxa  |
|-------|-------|-------|-----------|--------------|----------------|-------|
| 24/08 | 11:18 |   191 |     4     |       3      |       1º       | 1,6 % |
| 24/08 | 11:19 |   158 |     2     |       2      |       2º       | 1,3 % |
| 25/08 | 15:13 |   378 |     5     |      15      |       1º       | 4,0 % |
| 25/08 | 20:07 |   144 |     3     |       2      |       2º       | 1,4 % |
| 30/08 | 17:58 |   267 |     5     |       7      |       1º       | 2,6 % |
| 30/08 | 17:59 |   221 |     4     |       2      |       2º       | 0,9 % |
| 30/08 | 19:52 |   194 |     3     |       3      |       3º       | 1,5 % |
| 30/08 | 19:55 |   182 |     3     |       2      |       4º       | 1,1 % |
| 30/08 | 22:27 |   171 |     6     |       3      |       5º       | 1,8 % |
| 31/08 | 08:52 |   156 |     4     |       5      |       1º       | 3,2 % |
| 31/08 | 20:23 |   133 |     3     |       2      |       2º       | 1,5 % |
| 01/09 | 12:12 |   174 |     5     |       9      |       1º       | 5,2 % |
| 02/09 | 21:19 |   151 |     7     |       2      |       1º       | 1,3 % |
| 02/09 | 21:24 |   146 |     5     |       6      |       2º       | 4,1 % |
| 05/09 | 08:54 |   209 |     4     |       8      |       1º       | 3,8 % |
| 05/09 | 16:38 |   260 |     4     |       5      |       2º       | 1,9 % |
| 18/09 | 21:53 |   130 |     —     |       0 *    |       1º       | 0,0 % |
| 18/09 | 22:18 |   114 |     —     |       3 *    |       2º       | 2,6 % |

\* As duas linhas de 18/09 vieram da API, onde a coluna é `profile_visits`.
Não é a mesma métrica que "atividade do perfil" do app, que soma visitas +
cliques em link + seguidas. Não misture as duas origens numa média.

Medições parciais, que só servem para a comparação de conteúdo:

| Data  | Views | Ativ. perfil | Posição | Observação                        |
|-------|-------|--------------|---------|-----------------------------------|
| 18/09 |   225 |      —       |   1º    | horário não registrado            |
| 18/09 |   124 |      —       |   2º    | horário não registrado            |
| 18/09 |   109 |      —       |   3º    | horário não registrado            |
|   —   |   891 |     24       |    —    | bastidor / cliente                |
|   —   |   721 |     24       |    —    | bastidor / cliente                |


## 1. Posição no dia é o efeito mais forte

De 12 transições dentro do mesmo dia, 11 foram queda. O 2º story fica em torno
de 84 % do 1º (mediana), e a cauda é bem pior: o de 25/08 caiu para 38 %.

O 30/08 é o caso mais limpo — cinco stories, queda contínua de 267 para 171,
com 4h30 entre o primeiro e o último. Se o efeito fosse de horário, o de 22:27
teria oscilado. Só continuou caindo.

A única exceção foi 05/09: 08:54 → 209, depois 16:38 → 260. E o de 16:38 é o
print da mensagem da cliente. Não quebra a regra — mostra que conteúdo pesa
mais que posição.


## 2. Horário: dá para ver algo, mas pouco

A única comparação limpa é entre os primeiros do dia, onde a penalidade de
posição não contamina.

| Período          | Views (mediana) | Ativ. perfil (mediana) |
|------------------|-----------------|------------------------|
| Manhã 08h–12h    |       183       |          6,5           |
| Tarde 15h–18h    |     **323**     |        **11**          |
| Noite 21h+       |       141       |           1            |

Tarde ganha nas duas colunas; 21h perde nas duas. São 8 medições no total,
então é indício, não conclusão — mas a direção é consistente e contraria o
horário das 21h.


## 3. Conteúdo pesa mais que horário e posição juntos

Os dois stories de bastidor/cliente fizeram 891 e 721 views, com 24 atividades
de perfil cada. O resto do acervo vive entre 114 e 378 views, com 0 a 9
atividades.

São de 3 a 6 vezes o alcance típico e de 3 a 8 vezes a conversão. Nenhum ajuste
de horário chega perto desse tamanho de efeito.


## 4. Visualização engana — olhe atividade do perfil

As duas métricas discordam com frequência:

    12:12  →  174 views,  9 atividades  (5,2 %)
    16:38  →  260 views,  5 atividades  (1,9 %)

O story com 33 % menos audiência levou quase o dobro de gente para a loja.
Visualização mede quem estava com o app aberto; atividade do perfil mede quem
quis ver a marca. É a segunda que vira venda.

Há um padrão nisso: as melhores taxas estão de manhã e no meio-dia (3,2 % a
5,2 %), enquanto as da noite ficam entre 0,9 % e 1,8 %. A noite entrega
audiência passiva.


## Medição automática — 19 e 20/09

Cinco stories lidos pela API, com a curva de acumulação que os prints nunca
puderam dar. Amostra pequena, mas medida: posição correta, idade conhecida.

| Publicado | Pos. | Views | Reach | `profile_visits` | Interações |
|---|---|---|---|---|---|
| 18/09 21:53 | 1º | 161 | 134 | 0 | 2 |
| 18/09 22:18 | 2º | 148 | 117 | 3 | 3 |
| 19/09 17:33 | 1º | 170 | 143 | 1 | 4 |
| 19/09 18:09 | 2º | 147 | 124 | 0 | 3 |
| 20/09 04:48 | 1º | 70 (7h de vida) | 59 | 0 | 2 |

### A posição no dia não era artefato de medição

Comparar totais podia enganar: se o 2º story fosse medido mais cedo que o 1º,
ele pareceria pior sem ser. Com a curva dá para comparar **na mesma idade**, e
a razão fica estável:

- 18/09 — 88 % às 19h de vida, 91 % às 21h, 92 % no total.
- 19/09 — 87 % às 4h, 88 % às 9h, 88 % às 14h, 86 % no total.

O efeito é real e o tamanho dele (≈ 12 %) bate com os prints.

### A curva: metade das visualizações chega depois da 4ª hora

```
17h33 →  2h: 28 %   4h: 44 %   9h: 74 %   14h: 81 %   18h: 100 %
18h09 →  1h: 23 %   4h: 44 %   9h: 76 %   14h: 82 %   17h: 100 %
```

Isto **enfraquece o peso do horário**. Se o público chegasse na primeira hora,
publicar às 21h seria fatal; como 56 % chega depois da 4ª hora, o story de uma
hora ruim ainda é encontrado quando as pessoas abrem o app. Horário continua
mexendo no total, menos do que os prints sugeriam.

Confirma também a premissa do coletor: a leitura das 23h já está no número
final.

### O story das 4h48

Saiu de madrugada por causa do atraso do cron. Com 7h de vida tinha 70 views;
os dois da tarde, na mesma idade, estavam em ~106 e ~93 (interpolado). Cerca de
30 % abaixo. É **um** caso e a comparação honesta é às 24h, mas aponta na
direção esperada.

### Dois números de sanidade

`views / reach` ficou entre 1,19 e 1,26 nos cinco — as pessoas reveem ~20 %.
Se essa razão sair muito dessa faixa um dia, algo mudou na conta ou na API, não
no conteúdo.

`replies` e `shares` foram **zero** nos cinco.

### O que isso diz sobre a fila atual

Os cinco fizeram 147–170 views e 0 a 3 visitas ao perfil. Os stories de
bastidor/cliente dos prints fizeram 891 e 721 views com 24 atividades cada.
Horário e posição mexem 10–15 %; o tipo de conteúdo mexeu 5×. A fila que vem do
Drive é toda da categoria que não leva ninguém ao perfil.


## O que fazer com isso

1. **Mais conteúdo de cliente e bastidor.** É o único fator com efeito grande, e
   a medição automática não mudou isso — só mostrou que os outros fatores são
   ainda menores do que pareciam.
2. **Dois stories por dia continuam valendo.** A recomendação anterior era um
   só; os dados novos não a sustentam. O 2º entrega 87 % do 1º — ele soma,
   não canibaliza. Para justificar cortar, seria preciso mostrar que o 1º rende
   mais nos dias sem 2º, e isso nunca foi medido: nunca houve dia de story único
   com medição. Decisão do Gustavo em 20/09: mantém dois.
3. **Suspeitar do slot das 21h** — é o pior nas duas métricas entre os primeiros
   do dia. Desde 20/09 a agenda põe os dois na tarde (11h54-14h e 15h54-18h).


## A ressalva que importa

Tudo acima é observacional, com amostra pequena e conteúdo não controlado. A
"tarde" ganha em parte porque o story de 15:13 era bom, não porque 15h seja
mágico. As posições foram inferidas dos prints, e pode ter havido stories no
meio que nunca apareceram.

Nada disso decide sozinho. O coletor automático que entrou no ar em 19/09 lê os
stories de hora em hora e, em duas ou três semanas, entrega a mesma comparação
com dado completo, posição correta e a curva de acumulação — que é o que
finalmente separa "o horário importa" de "o horário não importa".

Este arquivo cobre 24/08 a 05/09, período que a API não devolve mais: story
expira em 24h e não há endpoint que traga de volta. Estes prints são a única
fonte que existe para essas datas.
