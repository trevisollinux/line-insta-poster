"""Ciclo de vida do token — o ponto que mais quebra.

O long-lived token dura ~60 dias. Sem renovação a automação morre em silêncio e
ninguém percebe até abrir o perfil. Por isso:

- `token_info()` diz quantos dias faltam (logado em toda publicação);
- `refresh_long_lived_token()` troca o token por um novo de ~60 dias;
- `update_repo_secret()` grava o token novo no secret do repositório.

O secret precisa de um PAT com permissão `Secrets: write` (`GH_SECRETS_TOKEN`):
o `GITHUB_TOKEN` padrão do Actions não escreve secrets.
"""
from __future__ import annotations

import base64
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .graph import GRAPH_HOST, GRAPH_VERSION, GraphError, urlopen_transport

GITHUB_API = "https://api.github.com"


@dataclass(frozen=True)
class TokenInfo:
    is_valid: bool
    expires_at: datetime | None
    scopes: tuple[str, ...] = ()
    type: str = ""

    @property
    def never_expires(self) -> bool:
        return self.expires_at is None

    def days_left(self, now: datetime | None = None) -> int | None:
        if self.expires_at is None:
            return None
        now = now or datetime.now(timezone.utc)
        return max(0, (self.expires_at - now).days)

    def describe(self, now: datetime | None = None) -> str:
        if not self.is_valid:
            return "token INVÁLIDO — a publicação vai falhar"
        if self.never_expires:
            return "token válido, sem data de expiração"
        return (
            f"token válido por mais {self.days_left(now)} dias "
            f"(expira em {self.expires_at.date().isoformat()})"
        )


def parse_token_info(payload: dict) -> TokenInfo:
    data = payload.get("data") or {}
    expires_at = data.get("expires_at") or 0
    return TokenInfo(
        is_valid=bool(data.get("is_valid")),
        expires_at=(
            datetime.fromtimestamp(int(expires_at), tz=timezone.utc)
            if int(expires_at) > 0
            else None
        ),
        scopes=tuple(data.get("scopes") or ()),
        type=str(data.get("type") or ""),
    )


def token_info(
    access_token: str,
    app_id: str,
    app_secret: str,
    *,
    host: str = GRAPH_HOST,
    version: str = GRAPH_VERSION,
    transport=urlopen_transport,
) -> TokenInfo:
    payload = _graph_oauth_get(
        f"{host}/{version}/debug_token",
        {"input_token": access_token, "access_token": f"{app_id}|{app_secret}"},
        transport,
    )
    return parse_token_info(payload)


def refresh_long_lived_token(
    access_token: str,
    app_id: str,
    app_secret: str,
    *,
    host: str = GRAPH_HOST,
    version: str = GRAPH_VERSION,
    transport=urlopen_transport,
) -> tuple[str, datetime | None]:
    """Troca o token atual por um novo long-lived. Devolve (token, expiração)."""
    payload = _graph_oauth_get(
        f"{host}/{version}/oauth/access_token",
        {
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": access_token,
        },
        transport,
    )
    novo = str(payload.get("access_token") or "").strip()
    if not novo:
        raise GraphError(f"renovação não devolveu access_token: {payload}")
    expires_in = payload.get("expires_in")
    expira = (
        datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
        if isinstance(expires_in, (int, float, str)) and str(expires_in).isdigit()
        else None
    )
    return novo, expira


def _graph_oauth_get(url: str, params: dict[str, str], transport) -> dict:
    status, raw = transport("GET", f"{url}?{urllib.parse.urlencode(params)}", None, {})
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        payload = {}
    if not 200 <= status < 300:
        mensagem = (payload.get("error") or {}).get("message") or raw[:300]
        raise GraphError(f"HTTP {status}: {mensagem}", status=status, payload=payload)
    return payload


def update_repo_secret(
    repo: str,
    name: str,
    value: str,
    github_token: str,
    *,
    api: str = GITHUB_API,
    transport=urlopen_transport,
) -> None:
    """Grava `value` no secret `name` de `owner/repo` (criptografia sealed box)."""
    if not github_token.strip():
        raise RuntimeError("GH_SECRETS_TOKEN é obrigatório para atualizar o secret")
    headers = {
        "Authorization": f"Bearer {github_token.strip()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "lombada-instagram-publisher",
    }
    status, raw = transport(
        "GET", f"{api}/repos/{repo}/actions/secrets/public-key", None, headers
    )
    if not 200 <= status < 300:
        raise RuntimeError(f"chave pública do repo não obtida: HTTP {status} {raw[:200]}")
    chave = json.loads(raw)

    body = json.dumps(
        {
            "encrypted_value": seal_secret(chave["key"], value),
            "key_id": chave["key_id"],
        }
    ).encode("utf-8")
    status, raw = transport(
        "PUT",
        f"{api}/repos/{repo}/actions/secrets/{name}",
        body,
        {**headers, "Content-Type": "application/json"},
    )
    if not 200 <= status < 300:
        raise RuntimeError(f"secret {name} não atualizado: HTTP {status} {raw[:200]}")


def seal_secret(public_key_b64: str, value: str) -> str:
    """Sealed box libsodium, como a API de secrets do GitHub exige."""
    try:
        from nacl import encoding, public  # import tardio: só o refresh precisa
    except ImportError as exc:  # pragma: no cover - ambiente sem pynacl
        raise RuntimeError(
            "pynacl não instalado — necessário para atualizar o secret "
            "(pip install -r requirements.txt)"
        ) from exc
    chave = public.PublicKey(public_key_b64.encode("utf-8"), encoding.Base64Encoder())
    selado = public.SealedBox(chave).encrypt(value.encode("utf-8"))
    return base64.b64encode(selado).decode("utf-8")
