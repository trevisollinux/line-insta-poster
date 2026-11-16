// Ponto de entrada do Cloudflare Worker.
//
// fluxos.json NÃO é versionado: o deploy gera com
// `python -m poster.cli dm-exportar` a partir de dm/fluxos.yaml, que é a
// fonte. Editar o JSON à mão seria apagado no próximo deploy.

import fluxos from "./fluxos.json";
import { criarApp } from "./app.js";

const app = criarApp(fluxos);

export default {
  fetch: (request, env, ctx) => app.fetch(request, env, ctx),
  scheduled: (evento, env) => app.scheduled(evento, env),
};
