"""Cliente mínimo da Graph API — sem dependência externa.

Usa `urllib` da stdlib em vez de `httpx`/`requests` para que a automação rode em
qualquer runner sem instalar nada além do PyYAML da fila. O transporte é um
parâmetro (`transport`), o que permite testar o fluxo inteiro sem rede.

O token vai no header `Authorization: Bearer`, nunca na query string — assim ele
não aparece em log de Actions nem em mensagem de erro. Os endpoints de OAuth são
a exceção (exigem `client_secret` no corpo) e ficam em `poster/token.py`.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

GRAPH_HOST = "https://graph.facebook.com"
GRAPH_VERSION = "v21.0"

# Códigos da Graph API que significam "tente de novo": limite de chamadas e
# falhas temporárias da plataforma. Qualquer outro erro 4xx é definitivo.
TRANSIENT_ERROR_CODES = {1, 2, 4, 17, 32, 341, 613}
TRANSIENT_STATUSES = {429, 500, 502, 503, 504}

SECRET_PARAMS = ("access_token", "client_secret", "fb_exchange_token", "appsecret_proof")

Transport = Callable[[str, str, bytes | None, dict[str, str]], tuple[int, str]]


class GraphError(RuntimeError):
    """Falha de chamada à Graph API, já com o token removido da mensagem."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        payload: dict[str, Any] | None = None,
        transient: bool = False,
    ) -> None:
        super().__init__(redact(message))
        self.status = status
        self.payload = payload or {}
        self.transient = transient

    @property
    def code(self) -> int | None:
        error = self.payload.get("error") or {}
        value = error.get("code")
        return value if isinstance(value, int) else None


def redact(text: str) -> str:
    """Troca valores de parâmetros sensíveis por `***` antes de logar."""
    for param in SECRET_PARAMS:
        text = _redact_param(text, param)
    return text


def _redact_param(text: str, param: str) -> str:
    marker = f"{param}="
    out: list[str] = []
    rest = text
    while True:
        idx = rest.find(marker)
        if idx < 0:
            out.append(rest)
            return "".join(out)
        start = idx + len(marker)
        end = start
        while end < len(rest) and rest[end] not in "&\"' \n\t":
            end += 1
        out.append(rest[:start])
        out.append("***")
        rest = rest[end:]


def urlopen_transport(
    method: str, url: str, body: bytes | None, headers: dict[str, str]
) -> tuple[int, str]:
    """Transporte padrão: `urllib`. Devolve (status, corpo) mesmo em erro HTTP."""
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:  # erro da API vem com corpo JSON útil
        return exc.code, exc.read().decode("utf-8", "replace")
    except urllib.error.URLError as exc:
        raise GraphError(f"falha de rede: {exc.reason}", transient=True) from exc


class GraphClient:
    """Chamadas GET/POST com retry exponencial nos erros transitórios."""

    def __init__(
        self,
        access_token: str,
        *,
        host: str = GRAPH_HOST,
        version: str = GRAPH_VERSION,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        max_attempts: int = 3,
    ) -> None:
        if not access_token.strip():
            raise ValueError("access_token é obrigatório")
        self.access_token = access_token.strip()
        self.host = host.rstrip("/")
        self.version = version.strip("/")
        self.transport = transport or urlopen_transport
        self.sleep = sleep
        self.max_attempts = max(1, max_attempts)

    def url(self, path: str) -> str:
        return f"{self.host}/{self.version}/{path.strip('/')}"

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.request("GET", path, params)

    def post(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.request("POST", path, params)

    def request(
        self, method: str, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        query = {k: str(v) for k, v in (params or {}).items() if v is not None}
        url = self.url(path)
        body: bytes | None = None
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
        }
        if method == "GET":
            if query:
                url = f"{url}?{urllib.parse.urlencode(query)}"
        else:
            body = urllib.parse.urlencode(query).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        last_error: GraphError | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                status, raw = self.transport(method, url, body, headers)
                payload = _parse_json(raw)
                if 200 <= status < 300:
                    return payload
                last_error = _error_from_response(status, payload, method, path)
            except GraphError as exc:
                last_error = exc
            if not last_error.transient or attempt == self.max_attempts:
                raise last_error
            self.sleep(2**attempt)
        raise last_error  # pragma: no cover - laço sempre sai pelo raise acima


def _parse_json(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"error": {"message": raw[:500], "type": "NonJsonResponse"}}
    return parsed if isinstance(parsed, dict) else {"data": parsed}


def _error_from_response(
    status: int, payload: dict[str, Any], method: str, path: str
) -> GraphError:
    error = payload.get("error") or {}
    message = error.get("message") or f"HTTP {status}"
    code = error.get("code")
    subcode = error.get("error_subcode")
    transient = status in TRANSIENT_STATUSES or code in TRANSIENT_ERROR_CODES
    detail = f"{method} /{path.strip('/')} → HTTP {status}: {message}"
    if code is not None:
        detail += f" (code={code}"
        detail += f", subcode={subcode})" if subcode is not None else ")"
    return GraphError(detail, status=status, payload=payload, transient=transient)
