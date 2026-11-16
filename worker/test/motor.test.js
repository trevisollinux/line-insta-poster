import assert from "node:assert/strict";
import { test } from "node:test";

import { extrair, normalizar, decidir } from "../src/motor.js";
import { casos, exportar, primeiro } from "./apoio.js";

const CONTA = "17841-loja";
const dados = casos();
const fluxos = exportar(dados.fluxos);

class EstadoMemoria {
  constructor(entregues = []) {
    this.entregues = new Set(entregues.map(([u, p]) => `${u}|${p}`));
  }
  async jaEntregue(u, p) {
    return this.entregues.has(`${u}|${p}`);
  }
}

// Os mesmos casos de tests/test_dm.py: Python e Worker não podem discordar.
for (const caso of dados.decisoes) {
  test(`caso compartilhado: ${caso.nome}`, async () => {
    const acoes = await decidir(caso.evento, fluxos, new EstadoMemoria(caso.entregues), primeiro);
    assert.deepEqual(acoes, caso.esperado);
  });
}

test("normaliza como o Python", () => {
  assert.equal(normalizar("  CÚPOM  Já "), "cupom ja");
  assert.equal(normalizar(""), "");
});

const corpo = ({ messaging, changes }) => ({
  object: "instagram",
  entry: [{ id: CONTA, ...(messaging && { messaging }), ...(changes && { changes }) }],
});

test("comentário vira evento", () => {
  const [ev] = extrair(
    corpo({
      changes: [{
        field: "comments",
        value: { id: "c9", text: "cupom", from: { id: "u1" }, media: { id: "m1" } },
      }],
    }),
    CONTA,
  );
  assert.deepEqual(ev, {
    tipo: "comentario", id: "c9", usuario: "u1", texto: "cupom", comentario_id: "c9", media_id: "m1",
  });
});

test("ignora comentário da própria loja e eco das nossas mensagens", () => {
  assert.deepEqual(
    extrair(corpo({ changes: [{ field: "comments", value: { id: "c", from: { id: CONTA } } }] }), CONTA),
    [],
  );
  assert.deepEqual(
    extrair(corpo({ messaging: [{ sender: { id: "u1" }, message: { mid: "m", text: "x", is_echo: true } }] }), CONTA),
    [],
  );
  assert.deepEqual(extrair(corpo({ messaging: [{ sender: { id: CONTA }, message: { mid: "m" } }] }), CONTA), []);
});

test("postback e resposta rápida viram botão; payload alheio é ignorado", () => {
  const eventos = extrair(
    corpo({
      messaging: [
        { sender: { id: "u1" }, postback: { mid: "p1", payload: "passo:cupom" } },
        { sender: { id: "u1" }, message: { mid: "q1", text: "ok", quick_reply: { payload: "passo:cupom" } } },
        { sender: { id: "u1" }, postback: { mid: "p2", payload: "OUTRO" } },
      ],
    }),
    CONTA,
  );
  assert.deepEqual(eventos.map((e) => [e.tipo, e.passo]), [["botao", "cupom"], ["botao", "cupom"]]);
});

test("story, dm e anexo sem texto", () => {
  const eventos = extrair(
    corpo({
      messaging: [
        { sender: { id: "u1" }, message: { mid: "s1", text: "cupom", reply_to: { story: { id: "9" } } } },
        { sender: { id: "u2" }, message: { mid: "d1", text: "oi" } },
        { sender: { id: "u3" }, message: { mid: "a1", attachments: [{}] } },
      ],
    }),
    CONTA,
  );
  assert.deepEqual(eventos.map((e) => e.tipo), ["story", "dm"]);
});

test("objeto que não é instagram", () => {
  assert.deepEqual(extrair({ object: "page", entry: [] }), []);
  assert.deepEqual(extrair(null), []);
});
