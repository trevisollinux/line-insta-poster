// Executa as ações do motor pela Graph API.
//
// Mensagens saem por POST /me/messages com o TOKEN DA PÁGINA, não o de
// usuário da publicação. O de Página derivado de um token de usuário de longa
// duração não expira — o Worker não depende da renovação mensal do secret.

import { decidir } from "./motor.js";

export const JANELA_ALERTA = 3600; // sem permissão, TODA mensagem falha
const TRANSITORIOS = new Set([1, 2, 4, 17, 32, 341, 613]);

export class GraphError extends Error {
  constructor(mensagem, { status = 0, codigo = null } = {}) {
    super(mensagem);
    this.status = status;
    this.codigo = codigo;
    this.transitorio = status === 429 || status >= 500 || TRANSITORIOS.has(codigo);
  }
}

export class Enviador {
  constructor({ token, versao = "v21.0", dryRun = false, alertWebhook = "", fetchFn, log }) {
    this.token = token;
    this.versao = versao;
    this.dryRun = dryRun;
    this.alertWebhook = alertWebhook;
    this.fetch = fetchFn || ((...a) => fetch(...a));
    this.log = log || ((m) => console.log(m));
  }

  async post(caminho, params) {
    const url = `https://graph.facebook.com/${this.versao}/${caminho}`;
    let ultimo;
    for (let tentativa = 1; tentativa <= 2; tentativa++) {
      const resposta = await this.fetch(url, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${this.token}`,
          "Content-Type": "application/x-www-form-urlencoded",
        },
        body: new URLSearchParams(params).toString(),
      });
      let dados = {};
      try {
        dados = await resposta.json();
      } catch {
        // corpo vazio ou não-JSON: o status decide
      }
      if (resposta.ok) return dados;
      const erro = dados.error || {};
      ultimo = new GraphError(
        `POST /${caminho} → HTTP ${resposta.status}: ${erro.message || "sem mensagem"}` +
          (erro.code != null ? ` (code=${erro.code})` : ""),
        { status: resposta.status, codigo: erro.code ?? null },
      );
      if (!ultimo.transitorio) break;
    }
    throw ultimo;
  }

  async enviarMensagem(acao) {
    const corpo = (mensagem) => ({
      recipient: JSON.stringify(acao.destinatario),
      message: JSON.stringify(mensagem),
      messaging_type: "RESPONSE",
    });
    try {
      await this.post("me/messages", corpo(acao.mensagem));
    } catch (erro) {
      // Template recusado (resposta privada pode não aceitar botão, por
      // exemplo): tenta texto + respostas rápidas antes de desistir.
      if (erro.transitorio || !acao.alternativa) throw erro;
      this.log(`template recusado (${erro.message}); tentando texto simples`);
      await this.post("me/messages", corpo(acao.alternativa));
    }
  }

  async executar(acao, estado) {
    if (this.dryRun) {
      this.log(`[dry-run] ${JSON.stringify(acao)}`);
      if (acao.registrar) await estado.registrarEntrega(...acao.registrar);
      return true;
    }
    try {
      if (acao.tipo === "responder_comentario") {
        await this.post(`${acao.comentario_id}/replies`, { message: acao.texto });
      } else {
        await this.enviarMensagem(acao);
      }
    } catch (erro) {
      if (!(erro instanceof GraphError)) throw erro;
      await this.alertar(erro, acao, estado);
      return false;
    }
    if (acao.registrar) await estado.registrarEntrega(...acao.registrar);
    this.log(`ok: ${acao.tipo} ${JSON.stringify(acao.destinatario || acao.comentario_id)}`);
    return true;
  }

  async alertar(erro, acao, estado) {
    this.log(`falha: ${erro.message}`);
    if (!(await estado.podeAlertar(`${acao.tipo}:${erro.codigo}`, JANELA_ALERTA))) return;
    let dica = "";
    if ([3, 10, 200, 230].includes(erro.codigo) || erro.status === 403) {
      dica =
        " — parece permissão: confira instagram_manage_messages / instagram_manage_comments " +
        "e 'Permitir acesso a mensagens' no Instagram (docs/DM.md).";
    } else if (erro.codigo === 551 || /outside of allowed window/i.test(erro.message)) {
      dica = " — fora da janela de 24h (ou comentário com mais de 7 dias).";
    }
    const texto = `[LINE STORE] DM automática não enviada: ${erro.message}${dica}`;
    if (!this.alertWebhook) return;
    try {
      await this.fetch(this.alertWebhook, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: texto }),
      });
    } catch (e) {
      this.log(`alerta não entregue: ${e}`); // não mascara a falha original
    }
  }
}

// Deduplica, decide e executa. Devolve as ações tentadas.
export async function processar(evento, fluxos, estado, enviador, sortear) {
  if (!(await estado.marcarVisto(evento.id))) return [];
  const acoes = await decidir(evento, fluxos, estado, sortear);
  for (const acao of acoes) {
    const ok = await enviador.executar(acao, estado);
    // Sem a DM, a resposta pública ("te chamei no direct") seria mentira.
    if (!ok && acao.tipo === "enviar") break;
  }
  return acoes;
}
