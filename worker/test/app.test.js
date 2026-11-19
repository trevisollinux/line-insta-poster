import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { beforeEach, test } from "node:test";

import { assinaturaValida, criarApp } from "../src/app.js";
import { Enviador, processar } from "../src/envio.js";
import { EstadoD1 } from "../src/estado.js";
import { casos, d1Falso, exportar, fetchFalso, primeiro } from "./apoio.js";

const CONTA = "17841-loja";
const fluxos = exportar(casos().fluxos);
const OK = [200, { message_id: "x" }];

let logs;
beforeEach(() => {
  logs = [];
});

function enviador(respostas, extra = {}) {
  const fetchFn = fetchFalso(respostas);
  const e = new Enviador({
    token: "TOKEN-PAGINA", fetchFn, log: (m) => logs.push(m), alertWebhook: "https://alerta.example/x",
    ...extra,
  });
  return { e, fetchFn };
}

const comentario = (id = "c1") => ({
  tipo: "comentario", id, usuario: "u1", texto: "cupom", comentario_id: id, media_id: "",
});
const dm = (id = "d1") => ({ tipo: "dm", id, usuario: "u1", texto: "cupom" });

test("comentário: DM privada, depois resposta pública", async () => {
  const { e, fetchFn } = enviador({ "me/messages": OK, "c1/replies": [200, { id: "r" }] });
  await processar(comentario(), fluxos, new EstadoD1(d1Falso()), e, primeiro);
  const [msg, publica] = fetchFn.chamadas;
  assert.deepEqual(JSON.parse(msg.params.recipient), { comment_id: "c1" });
  assert.equal(msg.params.messaging_type, "RESPONSE");
  assert.equal(msg.init.headers.Authorization, "Bearer TOKEN-PAGINA");
  assert.ok(!msg.url.includes("TOKEN"));
  assert.deepEqual(publica.params, { message: "Te chamei no direct!" });
});

test("evento reentregue não responde de novo", async () => {
  const { e, fetchFn } = enviador({ "me/messages": OK, "c1/replies": [200, {}] });
  const estado = new EstadoD1(d1Falso());
  await processar(comentario(), fluxos, estado, e, primeiro);
  assert.deepEqual(await processar(comentario(), fluxos, estado, e, primeiro), []);
  assert.equal(fetchFn.chamadas.length, 2);
});

test("cupom só é registrado depois de enviado", async () => {
  const estado = new EstadoD1(d1Falso());
  let { e } = enviador({ "me/messages": [400, { error: { code: 100, message: "x" } }], "alerta.example/x": [200, {}] });
  await processar(dm("d1"), fluxos, estado, e);
  assert.equal(await estado.jaEntregue("u1", "cupom"), false);

  ({ e } = enviador({ "me/messages": OK }));
  await processar(dm("d2"), fluxos, estado, e);
  assert.equal(await estado.jaEntregue("u1", "cupom"), true);

  // terceira vez: se_repetido
  const { e: e3, fetchFn } = enviador({ "me/messages": OK });
  await processar(dm("d3"), fluxos, estado, e3);
  assert.deepEqual(JSON.parse(fetchFn.chamadas[0].params.message), { text: "Você já pegou: LINE10." });
});

test("template recusado cai para texto com link", async () => {
  const { e, fetchFn } = enviador({
    "me/messages": [[400, { error: { code: 100, message: "template" } }], OK],
  });
  await processar(dm(), fluxos, new EstadoD1(d1Falso()), e);
  const segunda = JSON.parse(fetchFn.chamadas[1].params.message);
  assert.match(segunda.text, /https:\/\/loja\.example\//);
  assert.ok(!fetchFn.chamadas.some((c) => c.url.includes("alerta")));
});

test("erro transitório tenta de novo uma vez", async () => {
  const { e, fetchFn } = enviador({ "me/messages": [[503, {}], OK] });
  await processar(dm(), fluxos, new EstadoD1(d1Falso()), e);
  assert.equal(fetchFn.chamadas.length, 2);
});

test("sem DM, não responde em público; alerta com dica de permissão", async () => {
  const { e, fetchFn } = enviador({
    "me/messages": [403, { error: { code: 10, message: "sem permissão" } }],
    "alerta.example/x": [200, {}],
  });
  await processar(comentario(), fluxos, new EstadoD1(d1Falso()), e, primeiro);
  const urls = fetchFn.chamadas.map((c) => c.url);
  assert.ok(!urls.some((u) => u.endsWith("c1/replies")));
  const alerta = fetchFn.chamadas.find((c) => c.url.includes("alerta"));
  assert.match(JSON.parse(alerta.init.body).text, /parece permissão/);
});

test("alerta repetido é segurado por uma hora", async () => {
  const { e, fetchFn } = enviador({
    "me/messages": [403, { error: { code: 10, message: "x" } }],
    "alerta.example/x": [200, {}],
  });
  const estado = new EstadoD1(d1Falso());
  for (const id of ["a", "b", "c"]) await processar(dm(id), fluxos, estado, e);
  assert.equal(fetchFn.chamadas.filter((c) => c.url.includes("alerta")).length, 1);
});

test("dry-run não chama a API", async () => {
  const { e, fetchFn } = enviador({}, { dryRun: true });
  await processar(comentario(), fluxos, new EstadoD1(d1Falso()), e, primeiro);
  assert.equal(fetchFn.chamadas.length, 0);
  assert.ok(logs.every((l) => l.startsWith("[dry-run]")));
});

// ─── HTTP ──────────────────────────────────────────────────────────────────

const assinar = (corpo, segredo = "segredo") =>
  "sha256=" + createHmac("sha256", segredo).update(corpo).digest("hex");

function ambiente(extra = {}) {
  return {
    DB: d1Falso(), IG_USER_ID: CONTA, META_APP_SECRET: "segredo", DM_VERIFY_TOKEN: "frase",
    IG_PAGE_ACCESS_TOKEN: "TOKEN-PAGINA", ...extra,
  };
}

function contexto() {
  const pendentes = [];
  return { waitUntil: (p) => pendentes.push(p), pendentes };
}

test("assinatura", async () => {
  const corpo = new TextEncoder().encode('{"a":1}');
  assert.equal(await assinaturaValida(corpo, assinar('{"a":1}'), "segredo"), true);
  assert.equal(await assinaturaValida(corpo, assinar('{"a":1}', "outro"), "segredo"), false);
  assert.equal(await assinaturaValida(corpo, "", "segredo"), false);
  assert.equal(await assinaturaValida(corpo, assinar('{"a":1}'), ""), false);
});

test("verificação da Meta", async () => {
  const app = criarApp(fluxos);
  const base = "https://dm.example/webhook?hub.mode=subscribe&hub.challenge=42&hub.verify_token=";
  const ok = await app.fetch(new Request(base + "frase"), ambiente(), contexto());
  assert.equal(ok.status, 200);
  assert.equal(await ok.text(), "42");
  const ruim = await app.fetch(new Request(base + "errada"), ambiente(), contexto());
  assert.equal(ruim.status, 403);
  const semToken = await app.fetch(new Request(base), ambiente({ DM_VERIFY_TOKEN: "" }), contexto());
  assert.equal(semToken.status, 403);
});

test("webhook de ponta a ponta", async () => {
  const fetchFn = fetchFalso({ "me/messages": OK });
  const app = criarApp(fluxos, { fetchFn, log: (m) => logs.push(m), sortear: primeiro });
  const env = ambiente();
  const corpo = JSON.stringify({
    object: "instagram",
    entry: [{ id: CONTA, messaging: [{ sender: { id: "u1" }, message: { mid: "m1", text: "tem cupom?" } }] }],
  });
  const pedido = (assinatura) =>
    new Request("https://dm.example/webhook", {
      method: "POST", body: corpo, headers: { "X-Hub-Signature-256": assinatura },
    });

  const ctxRuim = contexto();
  assert.equal((await app.fetch(pedido("sha256=errada"), env, ctxRuim)).status, 401);
  assert.equal(ctxRuim.pendentes.length, 0);

  const ctx = contexto();
  assert.equal((await app.fetch(pedido(assinar(corpo)), env, ctx)).status, 200);
  await Promise.all(ctx.pendentes);
  assert.equal(fetchFn.chamadas.length, 1);
  assert.match(fetchFn.chamadas[0].params.message, /Use LINE10/);

  const saude = await app.fetch(new Request("https://dm.example/saude"), env, contexto());
  assert.equal(await saude.text(), "ok");
  assert.equal((await app.fetch(new Request("https://dm.example/x"), env, contexto())).status, 404);
});

test("limpeza agendada", async () => {
  const env = ambiente();
  const estado = new EstadoD1(env.DB);
  await estado.marcarVisto("velho");
  await env.DB.prepare("UPDATE vistos SET em = 0").bind().run();
  await estado.marcarVisto("novo");
  await criarApp(fluxos, { log: (m) => logs.push(m) }).scheduled({}, env);
  assert.deepEqual(logs, ["limpeza: 1 eventos e 0 entregas antigas removidos"]);
});

test("apagar meus dados: apaga as entregas e confirma, antes de qualquer fluxo", async () => {
  const estado = new EstadoD1(d1Falso());
  await estado.registrarEntrega("u1", "cupom");
  await estado.registrarEntrega("u2", "cupom");
  const { e, fetchFn } = enviador({ "me/messages": OK });
  // "cupom" também casaria com o fluxo — a exclusão tem que vencer
  await processar(
    { tipo: "dm", id: "x1", usuario: "u1", texto: "Quero APAGAR meus dados, e o cupom" },
    fluxos, estado, e,
  );
  assert.equal(await estado.jaEntregue("u1", "cupom"), false);
  assert.equal(await estado.jaEntregue("u2", "cupom"), true);
  assert.equal(fetchFn.chamadas.length, 1);
  assert.match(JSON.parse(fetchFn.chamadas[0].params.message).text, /apagamos os dados/);
});

test("exclusão só vale no direct, não em comentário público", async () => {
  const estado = new EstadoD1(d1Falso());
  await estado.registrarEntrega("u1", "cupom");
  const { e } = enviador({ "me/messages": OK, "c1/replies": [200, {}] });
  await processar(
    { tipo: "comentario", id: "c1", usuario: "u1", texto: "apagar meus dados", comentario_id: "c1" },
    fluxos, estado, e, primeiro,
  );
  assert.equal(await estado.jaEntregue("u1", "cupom"), true);
});

test("limpeza remove entregas com mais de um ano", async () => {
  const env = ambiente();
  const estado = new EstadoD1(env.DB);
  await estado.registrarEntrega("velho", "cupom");
  await env.DB.prepare("UPDATE entregues SET em = 0").bind().run();
  await estado.registrarEntrega("novo", "cupom");
  await criarApp(fluxos, { log: (m) => logs.push(m) }).scheduled({}, env);
  assert.equal(await estado.jaEntregue("velho", "cupom"), false);
  assert.equal(await estado.jaEntregue("novo", "cupom"), true);
});
