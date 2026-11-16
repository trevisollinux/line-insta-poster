// Traduz o webhook da Meta em eventos e decide o que responder. Sem rede.
//
// Espelho de poster/dm/motor.py. Os dois rodam os mesmos casos
// (tests/dm_casos.json) e não podem discordar. As mensagens já chegam
// montadas no fluxos.json exportado pelo Python: aqui só se escolhe qual.
//
// A regra mais importante é o que NÃO acontece: mensagem que não casa com
// nenhuma palavra não recebe resposta. O direct é onde a loja vende, e
// "quanto custa a caramelo?" é para gente responder.

export const PREFIXO_PAYLOAD = "passo:";

// Minúsculas e sem acento: "CUPOM!", "cupom" e "cúpom" são a mesma palavra.
export function normalizar(texto) {
  return (texto || "")
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .split(/\s+/u)
    .filter(Boolean)
    .join(" ");
}

function contemPalavra(texto, palavra) {
  if (!palavra) return false;
  const escapada = palavra.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  // Fronteira de palavra: "quero" não dispara em "queroseno".
  return new RegExp(`(?<![\\p{L}\\p{N}_])${escapada}(?![\\p{L}\\p{N}_])`, "u").test(texto);
}

export function gatilhoPara(fluxos, onde, texto, mediaId = "") {
  const normal = normalizar(texto);
  for (const gatilho of fluxos.gatilhos) {
    if (gatilho.onde !== onde) continue;
    if (gatilho.posts.length && !gatilho.posts.includes(mediaId)) continue;
    if (gatilho.palavras.some((p) => contemPalavra(normal, p))) return gatilho;
  }
  return null;
}

// ─── Exclusão de dados ─────────────────────────────────────────────────────
//
// Quem manda uma destas frases no direct tem os dados apagados na hora
// (política em site/privacidade.html). Vale antes de qualquer fluxo, e fica
// só no Worker: é sobre o banco, não sobre o que responder.

const FRASES_EXCLUSAO = [
  "apagar meus dados", "apague meus dados", "excluir meus dados", "exclua meus dados",
  "delete my data",
].map(normalizar);

export function pedeExclusao(texto) {
  const normal = normalizar(texto);
  return FRASES_EXCLUSAO.some((frase) => contemPalavra(normal, frase));
}

export const CONFIRMACAO_EXCLUSAO =
  "Pronto: apagamos os dados que o atendimento automático da LINE STORE guardava " +
  "sobre você. Se precisar de algo mais, é só responder aqui.";

// ─── Webhook → eventos ─────────────────────────────────────────────────────
//
// Mensagens, story e botões vêm em entry[].messaging[]; comentários em
// entry[].changes[]. O eco (is_echo) é a Meta reenviando o que NÓS mandamos:
// responder a ele é o laço infinito clássico de bot.

export function extrair(corpo, contaId = "") {
  if (!corpo || corpo.object !== "instagram") return [];
  const eventos = [];
  for (const entrada of corpo.entry || []) {
    for (const item of entrada.messaging || []) {
      const evento = deMensagem(item, contaId);
      if (evento) eventos.push(evento);
    }
    for (const mudanca of entrada.changes || []) {
      const evento = deComentario(mudanca, contaId);
      if (evento) eventos.push(evento);
    }
  }
  return eventos;
}

function passoDoPayload(payload) {
  const texto = String(payload || "");
  return texto.startsWith(PREFIXO_PAYLOAD) ? texto.slice(PREFIXO_PAYLOAD.length) : "";
}

function deMensagem(item, contaId) {
  const usuario = String(item.sender?.id || "");
  if (!usuario || (contaId && usuario === contaId)) return null;

  if (item.postback) {
    const passo = passoDoPayload(item.postback.payload);
    if (!passo) return null;
    const id = String(item.postback.mid || `pb-${usuario}-${item.timestamp}`);
    return { tipo: "botao", id, usuario, passo };
  }

  const mensagem = item.message;
  if (!mensagem || mensagem.is_echo || mensagem.is_deleted || !mensagem.mid) return null;
  const id = String(mensagem.mid);

  const rapida = passoDoPayload(mensagem.quick_reply?.payload);
  if (rapida) return { tipo: "botao", id, usuario, passo: rapida };

  const texto = String(mensagem.text || "");
  if (mensagem.reply_to?.story) return { tipo: "story", id, usuario, texto };
  if (!texto) return null; // foto, áudio, reação: humano responde
  return { tipo: "dm", id, usuario, texto };
}

function deComentario(mudanca, contaId) {
  if (mudanca.field !== "comments") return null;
  const valor = mudanca.value || {};
  const usuario = String(valor.from?.id || "");
  const comentarioId = String(valor.id || "");
  if (!usuario || !comentarioId) return null;
  if (contaId && usuario === contaId) return null; // a própria loja respondendo
  return {
    tipo: "comentario",
    id: comentarioId,
    usuario,
    texto: String(valor.text || ""),
    comentario_id: comentarioId,
    media_id: String(valor.media?.id || ""),
  };
}

// ─── Decisão ───────────────────────────────────────────────────────────────

const sortearPadrao = (opcoes) => opcoes[Math.floor(Math.random() * opcoes.length)];

export async function decidir(evento, fluxos, estado, sortear = sortearPadrao) {
  if (evento.tipo === "botao") {
    if (!fluxos.passos[evento.passo]) return []; // botão de versão antiga
    return enviar(evento.passo, { id: evento.usuario }, evento.usuario, fluxos, estado);
  }

  const gatilho = gatilhoPara(fluxos, evento.tipo, evento.texto, evento.media_id || "");
  if (!gatilho) return [];

  if (evento.tipo === "comentario") {
    // Resposta privada: destinatário é o comentário, não a pessoa. Única forma
    // de escrever para quem nunca falou no direct; 1 por comentário, até 7 dias.
    const acoes = await enviar(
      gatilho.passo, { comment_id: evento.comentario_id }, evento.usuario, fluxos, estado,
    );
    if (gatilho.resposta_publica.length) {
      acoes.push({
        tipo: "responder_comentario",
        comentario_id: evento.comentario_id,
        texto: sortear(gatilho.resposta_publica),
      });
    }
    return acoes;
  }

  return enviar(gatilho.passo, { id: evento.usuario }, evento.usuario, fluxos, estado);
}

async function enviar(passoId, destinatario, usuario, fluxos, estado) {
  const passo = fluxos.passos[passoId];
  if (passo.uma_vez && (await estado.jaEntregue(usuario, passoId))) {
    if (!passo.repetido) return [];
    return [{ tipo: "enviar", destinatario, mensagem: passo.repetido }];
  }
  const acao = { tipo: "enviar", destinatario, mensagem: passo.mensagem };
  if (passo.alternativa) acao.alternativa = passo.alternativa;
  if (passo.uma_vez) acao.registrar = [usuario, passoId];
  return [acao];
}
