"""
HERMES OS — Google Drive Integration
Interfaccia con Google Drive per la Knowledge Base.
Usa service account per accesso diretto.
"""

import io
import logging
from typing import Optional

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload, MediaIoBaseDownload

import config

logger = logging.getLogger("hermes.drive")

SCOPES = ["https://www.googleapis.com/auth/drive"]

_service = None


def _get_service():
    """Lazy init del servizio Google Drive."""
    global _service
    if _service is not None:
        return _service

    creds_dict = config.get_drive_credentials()
    if not creds_dict:
        raise RuntimeError("GOOGLE_DRIVE_CREDENTIALS non configurato o invalido")

    credentials = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    _service = build("drive", "v3", credentials=credentials)
    logger.info("Google Drive service inizializzato")
    return _service


def list_files(
    folder_id: str | None = None,
    mime_type: str | None = None,
    name_contains: str | None = None,
) -> list[dict]:
    """
    Lista file in una cartella Drive.

    Returns:
        Lista di {"id", "name", "mimeType", "modifiedTime"}
    """
    service = _get_service()
    parent = folder_id or config.HERMES_DRIVE_FOLDER_ID

    query_parts = [f"'{parent}' in parents", "trashed = false"]
    if mime_type:
        query_parts.append(f"mimeType = '{mime_type}'")
    if name_contains:
        query_parts.append(f"name contains '{name_contains}'")

    query = " and ".join(query_parts)
    logger.debug(f"Drive query: {query}")

    results = service.files().list(
        q=query,
        fields="files(id, name, mimeType, modifiedTime)",
        orderBy="modifiedTime desc",
        pageSize=100,
    ).execute()

    return results.get("files", [])


def find_folder(name: str, parent_id: str | None = None) -> Optional[str]:
    """Trova una cartella per nome. Ritorna l'ID o None."""
    parent = parent_id or config.HERMES_DRIVE_FOLDER_ID
    files = list_files(
        folder_id=parent,
        mime_type="application/vnd.google-apps.folder",
        name_contains=name,
    )
    for f in files:
        if f["name"].lower() == name.lower():
            return f["id"]
    return None


def create_folder(name: str, parent_id: str | None = None) -> str:
    """Crea una cartella su Drive. Ritorna l'ID."""
    service = _get_service()
    parent = parent_id or config.HERMES_DRIVE_FOLDER_ID

    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent],
    }
    folder = service.files().create(body=metadata, fields="id").execute()
    folder_id = folder["id"]
    logger.info(f"Cartella creata: {name} ({folder_id})")
    return folder_id


def read_file(file_id: str) -> str:
    """Legge il contenuto testuale di un file Drive."""
    service = _get_service()

    # Prova export come text (per Google Docs)
    try:
        content = service.files().export(
            fileId=file_id, mimeType="text/plain"
        ).execute()
        if isinstance(content, bytes):
            return content.decode("utf-8")
        return str(content)
    except Exception:
        pass

    # Fallback: download diretto (per file .md, .txt, etc.)
    request = service.files().get_media(fileId=file_id)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buffer.getvalue().decode("utf-8")


def write_file(
    name: str,
    content: str,
    folder_id: str | None = None,
    file_id: str | None = None,
    mime_type: str = "text/markdown",
) -> str:
    """
    Crea o aggiorna un file su Drive.

    Args:
        name: Nome file (es. "DentalTeam.md")
        content: Contenuto testuale
        folder_id: Cartella destinazione
        file_id: Se fornito, aggiorna il file esistente
        mime_type: MIME type del contenuto

    Returns:
        ID del file creato/aggiornato
    """
    service = _get_service()
    media = MediaIoBaseUpload(
        io.BytesIO(content.encode("utf-8")),
        mimetype=mime_type,
        resumable=True,
    )

    if file_id:
        # Aggiorna file esistente
        result = service.files().update(
            fileId=file_id,
            media_body=media,
        ).execute()
        logger.info(f"File aggiornato: {name} ({file_id})")
    else:
        # Crea nuovo file
        parent = folder_id or config.HERMES_DRIVE_FOLDER_ID
        metadata = {"name": name, "parents": [parent]}
        result = service.files().create(
            body=metadata,
            media_body=media,
            fields="id",
        ).execute()
        file_id = result["id"]
        logger.info(f"File creato: {name} ({file_id})")

    return file_id


def find_file(name: str, folder_id: str | None = None) -> Optional[dict]:
    """Cerca un file per nome esatto. Ritorna {"id", "name"} o None."""
    files = list_files(folder_id=folder_id, name_contains=name)
    for f in files:
        if f["name"].lower() == name.lower():
            return f
    return None


def ensure_kb_structure():
    """
    Assicura che la struttura della Knowledge Base esista su Drive.
    Crea le cartelle mancanti.
    """
    root = config.HERMES_DRIVE_FOLDER_ID
    if not root:
        logger.error("HERMES_DRIVE_FOLDER_ID non configurato")
        return

    required_folders = [
        "clients",
        "contacts",
        "preferences",
        "history",
        "resources",
    ]

    for folder_name in required_folders:
        existing = find_folder(folder_name, root)
        if not existing:
            create_folder(folder_name, root)
            logger.info(f"Cartella KB creata: {folder_name}")
        else:
            logger.debug(f"Cartella KB presente: {folder_name}")

    logger.info("Struttura Knowledge Base verificata")
