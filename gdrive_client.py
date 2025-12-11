import os
import io
import json

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# Alcance mínimo necesario: solo lectura de Drive
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def _get_credentials():
    """
    Construye credenciales a partir del JSON almacenado en la variable
    de entorno GOOGLE_SERVICE_ACCOUNT_JSON.
    """
    json_str = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not json_str:
        raise RuntimeError(
            "Falta la variable de entorno GOOGLE_SERVICE_ACCOUNT_JSON con las credenciales de la service account."
        )

    info = json.loads(json_str)
    creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return creds


def get_drive_service():
    """
    Construye y devuelve un cliente de la API de Google Drive.
    Se puede reutilizar en varias funciones.
    """
    creds = _get_credentials()
    service = build("drive", "v3", credentials=creds)
    return service


def download_file_from_drive(file_id: str) -> io.BytesIO:
    """
    Descarga un archivo de Drive (binario) y lo devuelve como BytesIO.
    Sirve para Excel (.xlsx), PDFs y cualquier archivo clásico.
    Para Google Sheets / Docs, usaremos export (ver función especializada).
    """
    service = get_drive_service()

    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)

    done = False
    while not done:
        status, done = downloader.next_chunk()

    fh.seek(0)
    return fh


def download_spreadsheet_as_excel(file_id: str) -> io.BytesIO:
    """
    Descarga un Google Sheet o Excel de Drive y lo devuelve como Excel (.xlsx) en BytesIO.

    - Si el archivo es un Google Sheet (tipo 'application/vnd.google-apps.spreadsheet'),
      se usa export_media para convertirlo a Excel.
    - Si ya es un archivo Excel (.xlsx) clásico, se descarga binario.
    """
    service = get_drive_service()

    # Primero obtenemos el mimeType del archivo
    file_metadata = service.files().get(fileId=file_id, fields="mimeType").execute()
    mime_type = file_metadata.get("mimeType")

    # Google Sheets -> exportar como Excel
    if mime_type == "application/vnd.google-apps.spreadsheet":
        request = service.files().export_media(
            fileId=file_id,
            mimeType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    else:
        # Asumimos que es un Excel ya binario
        request = service.files().get_media(fileId=file_id)

    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)

    done = False
    while not done:
        status, done = downloader.next_chunk()

    fh.seek(0)
    return fh

