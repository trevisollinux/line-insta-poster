// Rotas do Worker, separadas do ponto de entrada para dar para testar.
//
//   GET  /webhook   verificação da Meta (hub.challenge) ao cadastrar a URL
//   POST /webhook   eventos; assinatura conferida com o App Secret
//   GET  /saude     "ok"
//
// O POST responde 200 na hora e processa em ctx.waitUntil: a Meta reentrega o
// que demora.

import { Enviador, processar } from "./envio.js";
import { EstadoD1 } from "./estado.js";
import { extrair } from "./motor.js";

function hex(buffer) {
  return [...new Uint8Array(buffer)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function iguais(a, b) {
  if (a.length !== b.length) return false;
  let diferenca = 0;
  for (let i = 0; i < a.length; i++) diferenca |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diferenca === 0;
}

export async function assinaturaValida(corpo, cabecalho, segredo) {
  if (!segredo || !cabecalho || !cabecalho.startsWith("sha256=")) return false;
  const chave = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(segredo), { name: "HMAC", hash: "SHA-256" }, false, ["sign"],
  );
  const assinatura = hex(await crypto.subtle.sign("HMAC", chave, corpo));
  return iguais(assinatura, cabecalho.slice("sha256=".length));
}

const texto = (status, corpo = "") =>
  new Response(corpo, { status, headers: { "Content-Type": "text/plain; charset=utf-8" } });

export function criarApp(fluxos, { fetchFn, log, sortear } = {}) {
  function montar(env) {
    const estado = new EstadoD1(env.DB);
    const enviador = new Enviador({
      token: env.IG_PAGE_ACCESS_TOKEN,
      versao: env.IG_GRAPH_VERSION || "v21.0",
      dryRun: String(env.DM_DRY_RUN || "").toLowerCase() === "true",
      alertWebhook: env.IG_ALERT_WEBHOOK || "",
      fetchFn,
      log,
    });
    return { estado, enviador };
  }

  async function tratar(dados, env) {
    const { estado, enviador } = montar(env);
    for (const evento of extrair(dados, env.IG_USER_ID || "")) {
      try {
        await processar(evento, fluxos, estado, enviador, sortear);
      } catch (erro) {
        // um evento ruim não derruba os outros
        (log || console.error)(`erro tratando ${JSON.stringify(evento)}: ${erro}`);
      }
    }
  }

  return {
    tratar,

    async fetch(request, env, ctx) {
      const url = new URL(request.url);

      if (request.method === "GET" && url.pathname === "/saude") return texto(200, "ok");

      if (url.pathname !== "/webhook") return texto(404);

      if (request.method === "GET") {
        const p = url.searchParams;
        const token = p.get("hub.verify_token") || "";
        if (
          p.get("hub.mode") === "subscribe" &&
          env.DM_VERIFY_TOKEN &&
          iguais(token, env.DM_VERIFY_TOKEN)
        ) {
          return texto(200, p.get("hub.challenge") || "");
        }
        return texto(403, "verify_token não confere");
      }

      if (request.method !== "POST") return texto(405);

      const corpo = await request.arrayBuffer();
      const assinatura = request.headers.get("X-Hub-Signature-256") || "";
      if (!(await assinaturaValida(corpo, assinatura, env.META_APP_SECRET))) return texto(401);

      let dados;
      try {
        dados = JSON.parse(new TextDecoder().decode(corpo));
      } catch {
        return texto(400);
      }
      ctx.waitUntil(tratar(dados, env));
      return texto(200);
    },

    // Cron diário (wrangler.toml): limpa ids de evento antigos.
    async scheduled(_evento, env) {
      const removidos = await new EstadoD1(env.DB).limparVistos();
      (log || console.log)(`limpeza: ${removidos} eventos antigos removidos`);
    },
  };
}
