// Dublês dos testes: D1 em cima do node:sqlite (o mesmo schema.sql de
// produção) e fetch programável. Nenhum teste toca a rede.
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { DatabaseSync } from "node:sqlite";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

export const RAIZ = join(dirname(fileURLToPath(import.meta.url)), "..", "..");

export function d1Falso() {
  const db = new DatabaseSync(":memory:");
  db.exec(readFileSync(join(RAIZ, "worker", "schema.sql"), "utf8"));
  return {
    prepare(sql) {
      const stmt = db.prepare(sql);
      let args = [];
      const api = {
        bind(...a) {
          args = a;
          return api;
        },
        async run() {
          const r = stmt.run(...args);
          return { success: true, meta: { changes: Number(r.changes) } };
        },
        async first() {
          return stmt.get(...args) ?? null;
        },
      };
      return api;
    },
  };
}

// Exporta um arquivo de fluxos pelo próprio Python: o Worker lê exatamente o
// que o deploy vai gerar.
export function exportar(fluxosBrutos) {
  const pasta = mkdtempSync(join(tmpdir(), "dm-"));
  const caminhoFluxos = join(pasta, "fluxos.json"); // JSON é YAML válido
  writeFileSync(caminhoFluxos, JSON.stringify(fluxosBrutos));
  const saida = join(pasta, "exportado.json");
  execFileSync(
    "python3",
    ["-m", "poster.cli", "dm-exportar", "--fluxos", caminhoFluxos, "--saida", saida,
      "--permitir-pendente"],
    { cwd: RAIZ, stdio: "pipe" },
  );
  return JSON.parse(readFileSync(saida, "utf8"));
}

export const CASOS = join(RAIZ, "tests", "dm_casos.json");

export function casos() {
  return JSON.parse(readFileSync(CASOS, "utf8"));
}

// fetch falso: respostas por URL (sufixo), em fila.
export function fetchFalso(respostas = {}) {
  const chamadas = [];
  async function f(url, init = {}) {
    chamadas.push({ url, init, params: init.body ? Object.fromEntries(new URLSearchParams(init.body)) : {} });
    const chave = Object.keys(respostas).find((k) => url.endsWith(k));
    if (!chave) throw new Error(`fetch inesperado: ${url}`);
    const fila = respostas[chave];
    const [status, corpo] = Array.isArray(fila[0]) ? (fila.length > 1 ? fila.shift() : fila[0]) : fila;
    return new Response(JSON.stringify(corpo), { status });
  }
  f.chamadas = chamadas;
  return f;
}

export const primeiro = (opcoes) => opcoes[0];
