-- Aplicado a cada deploy (idempotente). Ver worker/src/estado.js.
CREATE TABLE IF NOT EXISTS vistos (id TEXT PRIMARY KEY, em REAL NOT NULL);
CREATE TABLE IF NOT EXISTS entregues (
  usuario TEXT NOT NULL,
  passo TEXT NOT NULL,
  em REAL NOT NULL,
  PRIMARY KEY (usuario, passo)
);
CREATE TABLE IF NOT EXISTS alertas (chave TEXT PRIMARY KEY, em REAL NOT NULL);
