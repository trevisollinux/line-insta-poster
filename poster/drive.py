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
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
}
PUBLICAVEL = {"image/jpeg", "video/mp4", "video/quicktime"}
# A API só aceita JPEG para imagem, mas exigir isso de quem sobe a foto é
# fricção recorrente por um problema de uma linha: PNG e WebP são convertidos na
# importação. WebP aparece bastante disfarçado de .jpg — imagem salva da web ou
# do WhatsApp —, e é por isso que o tipo vem do mime, nunca do nome.
CONVERSIVEIS = {"image/png", "image/webp"}


class DriveError(RuntimeError):
    """Falha ao falar com o Drive — nada foi importado."""


# Story aceita vídeo de até 60s. Acima disso a Meta recusa, e é melhor barrar
# aqui do que descobrir no container.
STORY_MAX_SECONDS = 60


@dataclass(frozen=True)
class DriveFile:
    id: str
    name: str
    mime_type: str
    size: int = 0
    modified: str = ""
    duration_ms: int = 0

    @property
    def precisa_converter(self) -> bool:
        return self.mime_type in CONVERSIVEIS

    @property
    def extension(self) -> str:
        if self.precisa_converter:
            return ".jpg"
        return EXTENSIONS.get(self.mime_type, os.path.splitext(self.name)[1].lower())

    @property
    def publicavel(self) -> bool:
        return self.mime_type in PUBLICAVEL or self.precisa_converter

    @property
    def duration_s(self) -> float:
        return self.duration_ms / 1000 if self.duration_ms else 0.0

    @property
    def cabe_em_story(self) -> bool:
        return not self.duration_ms or self.duration_s <= STORY_MAX_SECONDS

    @property
    def motivo_recusa(self) -> str:
        if not self.publicavel:
            return f"tipo {self.mime_type} não publicável no Instagram"
        if not self.cabe_em_story:
            return (
                f"vídeo de {self.duration_s:.0f}s — story aceita até "
                f"{STORY_MAX_SECONDS}s; corte antes de subir"
            )
        return ""


def access_token(service_account_json: str, *, scope: str = SCOPE_READONLY) -> str:
    """Troca a chave da conta de serviço por um token de acesso.

    É o único ponto que depende de `google-auth`: assinar o JWT exige RSA, que a
    biblioteca padrão não faz. Import tardio para o resto do pacote seguir
    funcionando (e testável) sem o SDK instalado.
    """
    try:
        from google.oauth2 import service_account
    except ImportError as exc:  # pragma: no cover - ambiente sem o SDK
        raise DriveError(
            "google-auth não instalado — necessário para ler o Drive "
            "(pip install -r requirements.txt)"
        ) from exc
    try:
        # Transporte separado de propósito na mensagem: `requests` não é
        # dependência automática do google-auth, e confundir os dois manda quem
        # está depurando para o lugar errado.
        from google.auth.transport.requests import Request
    except ImportError as exc:  # pragma: no cover - ambiente sem o transporte
        raise DriveError(
            "requests não instalado — o google-auth usa ele como transporte "
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


def folder_name(
    token: str, folder_id: str, *, opener=urllib.request.urlopen
) -> str:
    """Confirma que a conta de serviço enxerga a pasta, e devolve o nome dela.

    Existe porque `files.list` **não** dá erro em pasta sem acesso: devolve lista
    vazia, idêntica a uma pasta realmente vazia. Sem esta checagem, esquecer de
    compartilhar com o robô ficaria indistinguível de "ninguém subiu foto" — e
    ninguém iria investigar um job verde.
    """
    params = {"fields": "id,name,mimeType", "supportsAllDrives": "true"}
    payload = _get(
        f"{DRIVE_API}/files/{folder_id}?{urllib.parse.urlencode(params)}",
        token,
        opener=opener,
    )
    return str(payload.get("name") or "")


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
            "fields": (
                "nextPageToken,files(id,name,mimeType,size,modifiedTime,"
                "videoMediaMetadata(durationMillis))"
            ),
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
                    duration_ms=int(
                        (linha.get("videoMediaMetadata") or {}).get("durationMillis") or 0
                    ),
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


def converter_para_jpeg(caminho: str) -> None:
    """Converte PNG/WebP para JPEG no lugar, porque a API não aceita os outros.

    Transparência vira fundo branco: JPEG não tem canal alfa, e branco é o padrão
    sensato para foto de produto — o alternativo seria preto.
    """
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - ambiente sem Pillow
        raise DriveError(
            "Pillow não instalado — necessário para converter PNG/WebP em JPEG "
            "(pip install -r requirements.txt)"
        ) from exc

    try:
        with Image.open(caminho) as imagem:
            if imagem.mode in ("RGBA", "LA", "P"):
                com_alfa = imagem.convert("RGBA")
                fundo = Image.new("RGB", com_alfa.size, (255, 255, 255))
                fundo.paste(com_alfa, mask=com_alfa.split()[-1])
                final = fundo
            else:
                final = imagem.convert("RGB")
            final.save(caminho, "JPEG", quality=90, optimize=True)
    except OSError as exc:
        raise DriveError(f"não consegui converter '{os.path.basename(caminho)}': {exc}") from exc
