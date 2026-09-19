"""Caixa de entrada no Google Drive: onde a curadoria humana larga foto nova.

Separação que vale explicitar: a pasta do Drive é **caixa de entrada**, não host.
A Meta nunca busca nada aqui — ela não tem credencial. O job lê a pasta, copia o
arquivo para o repositório de mídia, e é de lá que a publicação acontece. Por
isso a pasta pode (e deve) ficar privada.

Autenticação é por conta de serviço: um robô com e-mail próprio, com quem a pasta
é compartilhada como se compartilha com uma pessoa. Só a obtenção do token usa
`google-auth` — listar e baixar é REST puro com urllib, e por isso testável sem
rede nem SDK.
"""
from __future__ import annotations

import json
import os
import shutil
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

DRIVE_API = "https://www.googleapis.com/drive/v3"
SCOPE_READONLY = "https://www.googleapis.com/auth/drive.readonly"

# A Meta só aceita JPEG para imagem e MP4/MOV para vídeo. O que não casa com
# isso é ignorado aqui em vez de falhar lá na publicação.
EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",  # avisado na listagem: precisa virar JPEG antes
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
}
PUBLICAVEL = {"image/jpeg", "video/mp4", "video/quicktime"}


class DriveError(RuntimeError):
    """Falha ao falar com o Drive — nada foi importado."""


@dataclass(frozen=True)
class DriveFile:
    id: str
    name: str
    mime_type: str
    size: int = 0
    modified: str = ""

    @property
    def extension(self) -> str:
        return EXTENSIONS.get(self.mime_type, os.path.splitext(self.name)[1].lower())

    @property
    def publicavel(self) -> bool:
        return self.mime_type in PUBLICAVEL

    @property
    def motivo_recusa(self) -> str:
        if self.publicavel:
            return ""
        if self.mime_type == "image/png":
            return "PNG — a API do Instagram só aceita JPEG; exporte como JPEG"
        return f"tipo {self.mime_type} não publicável no Instagram"


def access_token(service_account_json: str, *, scope: str = SCOPE_READONLY) -> str:
    """Troca a chave da conta de serviço por um token de acesso.

    É o único ponto que depende de `google-auth`: assinar o JWT exige RSA, que a
    biblioteca padrão não faz. Import tardio para o resto do pacote seguir
    funcionando (e testável) sem o SDK instalado.
    """
    try:
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account
    except ImportError as exc:  # pragma: no cover - ambiente sem o SDK
        raise DriveError(
            "google-auth não instalado — necessário para ler o Drive "
            "(pip install -r requirements.txt)"
        ) from exc

    try:
        info = json.loads(service_account_json)
    except json.JSONDecodeError as exc:
        raise DriveError(
            "GDRIVE_SERVICE_ACCOUNT não é um JSON válido — cole o arquivo inteiro, "
            "incluindo as chaves { }"
        ) from exc

    try:
        credenciais = service_account.Credentials.from_service_account_info(
            info, scopes=[scope]
        )
        credenciais.refresh(Request())
    except Exception as exc:  # o SDK levanta tipos variados
        raise DriveError(f"conta de serviço recusada pelo Google: {exc}") from exc
    return str(credenciais.token)


def _get(url: str, token: str, *, opener=urllib.request.urlopen) -> dict:
    requisicao = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {token}"}, method="GET"
    )
    try:
        with opener(requisicao, timeout=60) as resposta:
            return json.loads(resposta.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detalhe = exc.read().decode("utf-8", "replace")[:300]
        if exc.code in (403, 404):
            raise DriveError(
                f"Drive respondeu {exc.code}. A pasta está compartilhada com o "
                f"e-mail da conta de serviço como Leitor? Detalhe: {detalhe}"
            ) from exc
        raise DriveError(f"Drive respondeu {exc.code}: {detalhe}") from exc
    except OSError as exc:
        raise DriveError(f"falha de rede ao falar com o Drive: {exc}") from exc


def list_files(
    token: str,
    folder_id: str,
    *,
    page_size: int = 100,
    opener=urllib.request.urlopen,
) -> list[DriveFile]:
    """Lista o conteúdo da pasta, do mais recente para o mais antigo."""
    arquivos: list[DriveFile] = []
    pagina: str | None = None
    while True:
        params = {
            "q": f"'{folder_id}' in parents and trashed = false",
            "fields": "nextPageToken,files(id,name,mimeType,size,modifiedTime)",
            "orderBy": "modifiedTime desc",
            "pageSize": str(page_size),
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if pagina:
            params["pageToken"] = pagina
        payload = _get(
            f"{DRIVE_API}/files?{urllib.parse.urlencode(params)}", token, opener=opener
        )
        for linha in payload.get("files") or []:
            arquivos.append(
                DriveFile(
                    id=str(linha.get("id") or ""),
                    name=str(linha.get("name") or ""),
                    mime_type=str(linha.get("mimeType") or ""),
                    size=int(linha.get("size") or 0),
                    modified=str(linha.get("modifiedTime") or ""),
                )
            )
        pagina = payload.get("nextPageToken")
        if not pagina:
            return arquivos


def download(
    token: str,
    arquivo: DriveFile,
    destino: str,
    *,
    opener=urllib.request.urlopen,
    max_bytes: int = 90 * 1024 * 1024,
) -> int:
    """Baixa para `.parcial` e só promove no fim — igual ao rehost."""
    os.makedirs(os.path.dirname(destino) or ".", exist_ok=True)
    parcial = f"{destino}.parcial"
    url = f"{DRIVE_API}/files/{arquivo.id}?alt=media&supportsAllDrives=true"
    requisicao = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {token}"}, method="GET"
    )
    try:
        with opener(requisicao, timeout=180) as resposta, open(parcial, "wb") as saida:
            shutil.copyfileobj(resposta, saida)
        tamanho = os.path.getsize(parcial)
        if tamanho == 0:
            raise DriveError(f"'{arquivo.name}' veio vazio")
        if tamanho > max_bytes:
            raise DriveError(
                f"'{arquivo.name}' tem {tamanho // (1024 * 1024)} MB — grande demais "
                "para o repositório de mídia"
            )
        os.replace(parcial, destino)
        return tamanho
    except urllib.error.HTTPError as exc:
        raise DriveError(f"download de '{arquivo.name}' falhou: HTTP {exc.code}") from exc
    except OSError as exc:
        raise DriveError(f"download de '{arquivo.name}' falhou: {exc}") from exc
    finally:
        if os.path.exists(parcial):
            os.remove(parcial)
