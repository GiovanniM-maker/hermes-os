"""
HERMES OS — Knowledge Base
Memoria permanente di HERMES. Vive su Google Drive.
Ogni agente la legge prima di eseguire.
Ogni nuova informazione appresa viene scritta immediatamente.
"""

import logging
from typing import Optional

from integrations import google_drive as drive

logger = logging.getLogger("hermes.kb")

# Cache in-memory delle cartelle KB (evita fetch ripetuti)
_folder_cache: dict[str, str] = {}


async def _get_folder_id(folder_name: str) -> str:
    """Ottiene l'ID di una cartella KB, con cache."""
    if folder_name in _folder_cache:
        return _folder_cache[folder_name]

    folder_id = drive.find_folder(folder_name)
    if folder_id:
        _folder_cache[folder_name] = folder_id
        return folder_id

    # Crea se non esiste
    folder_id = drive.create_folder(folder_name)
    _folder_cache[folder_name] = folder_id
    return folder_id


# ─── Clienti ─────────────────────────────────────────────

async def get_client_info(client_name: str) -> Optional[str]:
    """Legge le info di un cliente dalla KB."""
    folder_id = await _get_folder_id("clients")
    file_info = drive.find_file(f"{client_name}.md", folder_id)
    if file_info:
        return drive.read_file(file_info["id"])
    return None


async def save_client_info(client_name: str, content: str) -> str:
    """Salva/aggiorna info cliente nella KB."""
    folder_id = await _get_folder_id("clients")
    existing = drive.find_file(f"{client_name}.md", folder_id)
    file_id = existing["id"] if existing else None
    return drive.write_file(
        f"{client_name}.md", content,
        folder_id=folder_id, file_id=file_id,
    )


# ─── Contatti ────────────────────────────────────────────

async def get_contacts() -> Optional[str]:
    """Legge il file contatti dalla KB."""
    folder_id = await _get_folder_id("contacts")
    file_info = drive.find_file("people.md", folder_id)
    if file_info:
        return drive.read_file(file_info["id"])
    return None


async def update_contacts(content: str) -> str:
    """Aggiorna il file contatti."""
    folder_id = await _get_folder_id("contacts")
    existing = drive.find_file("people.md", folder_id)
    file_id = existing["id"] if existing else None
    return drive.write_file(
        "people.md", content,
        folder_id=folder_id, file_id=file_id,
    )


# ─── Preferenze ──────────────────────────────────────────

async def get_preference(name: str) -> Optional[str]:
    """Legge un file preferenze (frameworks.md, tools.md, communication.md)."""
    folder_id = await _get_folder_id("preferences")
    file_info = drive.find_file(f"{name}.md", folder_id)
    if file_info:
        return drive.read_file(file_info["id"])
    return None


async def save_preference(name: str, content: str) -> str:
    """Salva/aggiorna un file preferenze."""
    folder_id = await _get_folder_id("preferences")
    existing = drive.find_file(f"{name}.md", folder_id)
    file_id = existing["id"] if existing else None
    return drive.write_file(
        f"{name}.md", content,
        folder_id=folder_id, file_id=file_id,
    )


# ─── History ─────────────────────────────────────────────

async def log_history(log_type: str, entry: str) -> str:
    """
    Appende una entry a un log storico.

    Args:
        log_type: "ads_changes_log" | "tasks_done" | "decisions"
        entry: Testo da appendere (con timestamp)
    """
    folder_id = await _get_folder_id("history")
    filename = f"{log_type}.md"
    existing = drive.find_file(filename, folder_id)

    if existing:
        current = drive.read_file(existing["id"])
        updated = current.rstrip() + "\n\n" + entry
        return drive.write_file(filename, updated, file_id=existing["id"])
    else:
        return drive.write_file(filename, entry, folder_id=folder_id)


# ─── Resources ───────────────────────────────────────────

async def get_resource(name: str) -> Optional[str]:
    """Legge un file risorse (apis.md, templates.md)."""
    folder_id = await _get_folder_id("resources")
    file_info = drive.find_file(f"{name}.md", folder_id)
    if file_info:
        return drive.read_file(file_info["id"])
    return None


async def save_resource(name: str, content: str) -> str:
    """Salva/aggiorna un file risorse."""
    folder_id = await _get_folder_id("resources")
    existing = drive.find_file(f"{name}.md", folder_id)
    file_id = existing["id"] if existing else None
    return drive.write_file(
        f"{name}.md", content,
        folder_id=folder_id, file_id=file_id,
    )


# ─── Ricerca Entita' ────────────────────────────────────

async def search_entity(entity_name: str) -> Optional[str]:
    """
    Cerca un'entita' (persona, azienda, contesto) in tutta la KB.
    Usato dal Question Engine per la regola 'entita' sconosciuta'.

    Returns:
        Contenuto trovato o None
    """
    # Cerca nei clienti
    client = await get_client_info(entity_name)
    if client:
        return f"[Cliente] {client}"

    # Cerca nei contatti
    contacts = await get_contacts()
    if contacts and entity_name.lower() in contacts.lower():
        return f"[Contatto] Trovato in people.md"

    # Cerca nelle risorse
    for resource_name in ["apis", "templates"]:
        resource = await get_resource(resource_name)
        if resource and entity_name.lower() in resource.lower():
            return f"[Risorsa] Trovato in {resource_name}.md"

    return None


async def learn_entity(entity_name: str, entity_info: str, category: str = "contacts"):
    """
    Salva una nuova entita' appresa nella KB.
    Regola: ogni entita' sconosciuta viene appresa e non viene mai chiesta due volte.

    Args:
        entity_name: Nome entita'
        entity_info: Informazioni fornite da Juan
        category: "clients" | "contacts" | "resources"
    """
    if category == "clients":
        await save_client_info(entity_name, entity_info)
    elif category == "contacts":
        contacts = await get_contacts() or "# Contatti\n"
        entry = f"\n## {entity_name}\n{entity_info}\n"
        await update_contacts(contacts + entry)
    else:
        await save_resource(entity_name, entity_info)

    logger.info(f"Entita' appresa: {entity_name} → {category}")
