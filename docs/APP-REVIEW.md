# Análise do app (App Review) — liberar o bot de DM para todo mundo

Enquanto o app não tiver **acesso avançado**, a Meta só entrega ao bot eventos
de contas com papel no app (admin, desenvolvedor, testador). Este é o roteiro
para pedir esse acesso. Os textos para colar estão em inglês: o revisor
costuma ler em inglês, e texto vago é o motivo nº 1 de recusa.

## 0. Antes de tudo

- [ ] **Trocar o fluxo de teste pelo de verdade** em `dm/fluxos.yaml` (cupom,
      link da loja). O revisor vê o que estiver no ar — "[teste]" no vídeo
      enfraquece o pedido. Depois do merge, conferir que o deploy passou.
- [ ] **`DM_DRY_RUN` = `false`** e o bot funcionando com uma conta testadora.
- [ ] **Verificação da empresa** (business.facebook.com → Central de
      segurança, ou *Configurações do app → Básico*). Para acesso avançado a
      dados de outras pessoas a Meta costuma exigir. Leva alguns dias: comece
      por ela.

## 1. Configurações básicas do app

*Configurações do app → Básico*:

| Campo | Valor |
|---|---|
| URL da Política de Privacidade | `https://trevisollinux.github.io/line-insta-poster/privacidade.html` |
| Instruções de exclusão de dados (URL) | `https://trevisollinux.github.io/line-insta-poster/privacidade.html#exclusao` |
| Ícone do app | logo da loja, 1024×1024 |
| Categoria | Compras (Shopping) ou Mensagens (Messaging) |

A página sai de `site/privacidade.html`, publicada pelo workflow *Publicar
site (privacidade)*. **Uma vez só:** *Settings → Pages → Source: GitHub
Actions* neste repositório, e rodar o workflow.

Depois: **modo do app → Ao vivo (Live)**, no topo do painel.

## 2. Permissões a pedir (acesso avançado)

*Análise do app → Permissões e recursos* → **Solicitar acesso avançado**:

| Permissão | Para quê |
|---|---|
| `instagram_manage_messages` | mandar a DM |
| `instagram_manage_comments` | receber o comentário, resposta privada e resposta pública |
| `pages_manage_metadata` | inscrever a Página nos webhooks |
| `instagram_basic`, `pages_show_list`, `pages_read_engagement` | se o formulário pedir (são dependências) |

`Human Agent` (*recurso*, não permissão) só se a equipe precisar responder
clientes depois de 24h da última mensagem deles. Pode ficar para depois.

### Textos para colar

**instagram_manage_messages**

> LINE STORE is a small leather goods store in Brazil. This app is used only
> with our own Instagram professional account (@line_store), which we own and
> manage. When someone comments a specific keyword on one of our posts, replies
> to our story with it, or sends it to us in a direct message, our server (a
> Cloudflare Worker) receives the webhook and sends one automated reply in that
> conversation — for example a welcome message with a button that leads to a
> first-purchase coupon and a link to our online store. We only reply to people
> who contacted us first, always inside the 24-hour messaging window, and we
> never send unsolicited or bulk messages. Messages without a keyword are not
> answered automatically: they are left for our human team. Anyone can send
> "delete my data" to have the data we store about them erased immediately.

**instagram_manage_comments**

> We use this permission on our own Instagram professional account only. It
> lets us receive webhooks for new comments on our posts so we can check them
> for the campaign keyword, send a private reply to the person who commented
> (Private Replies), and post one short public reply to that same comment
> ("We sent you a DM"). Comment text is only checked for the keyword and is not
> stored. We do not hide, delete or moderate comments with this app.

**pages_manage_metadata**

> Our Instagram professional account is connected to our Facebook Page. We use
> this permission only to subscribe our own Page to our app's webhooks
> (POST /{page-id}/subscribed_apps), which is required to receive the Instagram
> messaging and comment webhooks described above. We do not change any other
> Page setting.

**instagram_basic / pages_show_list / pages_read_engagement** (se pedirem)

> Needed to find our Facebook Page and the Instagram professional account
> connected to it, and to obtain the Page access token our server uses to send
> the replies. Used only for our own Page and account.

### Instruções de teste para o revisor

Ajuste a palavra-chave ao fluxo que estiver no ar (`dm/fluxos.yaml`):

> 1. Open any post on instagram.com/line_store and comment: **cupom**
> 2. Within a few seconds you receive a direct message from @line_store with a
>    button, and our account replies to your comment publicly.
> 3. Tap the button: a second message arrives with the coupon and a link.
> 4. Send **cupom** again in the chat: you get a short "you already received
>    it" reply (the coupon is sent once per person).
> 5. Send **delete my data**: the stored data is erased and confirmed.
> Messages without the keyword are not answered automatically.

## 3. Roteiro do vídeo (screencast)

Um vídeo para cada permissão costuma ser aceito com o **mesmo arquivo**.
Grave a tela do celular (gravador nativo), 1–2 minutos, sem cortes no meio do
fluxo. Use uma **conta testadora** (não a da loja: o bot ignora a loja).

1. **Abertura (5 s)** — o perfil @line_store aberto.
2. **Comentário** — abra um post e comente a palavra-chave. Mostre o
   comentário publicado.
3. **DM chegando** — vá ao direct: a mensagem da loja com o botão. Volte ao
   post e mostre a resposta pública no comentário.
4. **Botão** — toque no botão; mostre a segunda mensagem e toque no link
   (abre a loja).
5. **Uma vez só** — mande a palavra-chave de novo: "você já recebeu".
6. **Exclusão** — mande `apagar meus dados`: a confirmação.
7. **Sem palavra-chave** — mande "quanto custa?": nada automático acontece
   (mostra que o bot não interfere no atendimento humano).

Se a Meta pedir para ver "como o usuário concede as permissões": grave o
Graph API Explorer gerando o token do app com as permissões marcadas e a
janela do Facebook escolhendo a Página e o Instagram da loja. O app não tem
tela própria — é usado só pela loja, na própria conta.

## 4. Depois de enviar

- Resposta em dias a semanas. Recusa vem com motivo; dá para corrigir e
  reenviar.
- Aprovado: qualquer pessoa que comentar a palavra-chave recebe a DM. Nada a
  mudar no código.
- Pode ser preciso renovar a verificação de uso de dados (*Data Use Checkup*)
  uma vez por ano — a Meta avisa por e-mail.
