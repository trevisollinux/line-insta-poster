// Memória do bot no D1 (SQLite da Cloudflare). Tabelas em worker/schema.sql.
//
// - vistos:    a Meta reentrega webhook; sem isso o cliente ganha o cupom 2x.
// - entregues: quem já recebeu qual passo; é o que faz `uma_vez` funcionar.
// - alertas:   último alerta por tipo de erro, para não inundar o canal.
//
// Perder o banco não é grave: no pior caso alguém ganha um cupom a mais.

const agora = () => Date.now() / 1000;

export class EstadoD1 {
  constructor(db) {
    this.db = db;
  }

  // true na primeira vez. Marca ANTES de enviar, de propósito: entre não
  // responder e responder duas vezes, o segundo é pior.
  async marcarVisto(id) {
    const r = await this.db
      .prepare("INSERT OR IGNORE INTO vistos (id, em) VALUES (?, ?)")
      .bind(id, agora())
      .run();
    return r.meta.changes === 1;
  }

  async jaEntregue(usuario, passo) {
    const linha = await this.db
      .prepare("SELECT 1 AS ok FROM entregues WHERE usuario = ? AND passo = ?")
      .bind(usuario, passo)
      .first();
    return linha !== null;
  }

  async registrarEntrega(usuario, passo) {
    await this.db
      .prepare("INSERT OR IGNORE INTO entregues (usuario, passo, em) VALUES (?, ?, ?)")
      .bind(usuario, passo, agora())
      .run();
  }

  // true se pode alertar agora (e já registra). Janela em segundos.
  async podeAlertar(chave, janela) {
    const limite = agora() - janela;
    const r = await this.db
      .prepare(
        "INSERT INTO alertas (chave, em) VALUES (?1, ?2) " +
          "ON CONFLICT (chave) DO UPDATE SET em = ?2 WHERE alertas.em < ?3",
      )
      .bind(chave, agora(), limite)
      .run();
    return r.meta.changes === 1;
  }

  // Pedido de exclusão (site/privacidade.html): some tudo que liga a pessoa ao bot.
  // `vistos` guarda só id de evento, sem quem mandou — não identifica ninguém.
  async apagarUsuario(usuario) {
    const r = await this.db
      .prepare("DELETE FROM entregues WHERE usuario = ?")
      .bind(usuario)
      .run();
    return r.meta.changes;
  }

  // Retenção máxima prometida na política de privacidade. Depois disso a
  // pessoa pode receber o cupom de novo — custo aceito.
  async limparEntregues(dias = 365) {
    const r = await this.db
      .prepare("DELETE FROM entregues WHERE em < ?")
      .bind(agora() - dias * 86400)
      .run();
    return r.meta.changes;
  }

  // Reentrega acontece em minutos; id de mês passado é peso morto.
  async limparVistos(dias = 30) {
    const r = await this.db
      .prepare("DELETE FROM vistos WHERE em < ?")
      .bind(agora() - dias * 86400)
      .run();
    return r.meta.changes;
  }
}
