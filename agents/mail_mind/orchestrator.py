"""
HERMES OS — MailMind Orchestrator
Gestione email via n8n webhooks.

Architettura:
- n8n gestisce Gmail internamente (auth, lettura, invio)
- HERMES chiama webhook n8n per triggerare azioni
- n8n manda risultati a HERMES via webhook di ritorno

Workflow n8n necessari:
1. mail_fetch: legge email non lette → ritorna lista
2. mail_send: invia email (to, subject, body)
3. mail_archive: archivia email per ID
4. mail_delete: elimina email per ID
"""

import json
import logging
from datetime import datetime, timezone

from telegram import Bot

import config
from core.llm_router import chat, TaskComplexity
from core import memory
from agents.pipeline_forge.n8n_client import import_workflow

logger = logging.getLogger("hermes.mailmind")

# Webhook URLs di n8n (impostati dopo la creazione dei workflow)
_n8n_webhooks: dict[str, str] = {}


async def handle_request(user_text: str, bot: Bot | None = None) -> str:
    """Entry point MailMind."""
    text_lower = user_text.lower().strip()

    # "configura/setup" PRIMA del check generico "mail" (mailmind contiene "mail")
    if "setup" in text_lower or "configura" in text_lower:
        return await setup_n8n_workflows()

    elif any(w in text_lower for w in ("elimina", "cancella", "delete")):
        return await _handle_delete(user_text)

    elif any(w in text_lower for w in ("archivia", "archive")):
        return await _handle_archive(user_text)

    elif any(w in text_lower for w in ("rispondi", "reply", "rispondi con")):
        return await _handle_reply(user_text)

    elif any(w in text_lower for w in ("bozza", "draft")):
        return await _handle_draft(user_text)

    elif any(w in text_lower for w in ("chi è", "chi e'", "who is")):
        return await _handle_who_is(user_text)

    elif any(w in text_lower for w in ("digest", "email", "mail", "posta")):
        return await _generate_digest(bot)

    else:
        return await _smart_mail_handling(user_text)


async def setup_n8n_workflows() -> str:
    """
    Crea i workflow n8n necessari per MailMind.
    Va eseguito una sola volta durante il setup.
    """
    workflows_created = []

    # 1. Workflow: Fetch email non lette
    fetch_workflow = {
        "name": "HERMES - Mail Fetch",
        "nodes": [
            {
                "id": "webhook-trigger",
                "name": "Webhook Trigger",
                "type": "n8n-nodes-base.webhook",
                "position": [250, 300],
                "parameters": {
                    "path": "hermes-mail-fetch",
                    "httpMethod": "POST",
                    "responseMode": "lastNode",
                },
                "typeVersion": 2,
            },
            {
                "id": "gmail-fetch",
                "name": "Gmail - Leggi Email",
                "type": "n8n-nodes-base.gmail",
                "position": [500, 300],
                "parameters": {
                    "operation": "getAll",
                    "returnAll": False,
                    "limit": 20,
                    "filters": {
                        "labelIds": ["INBOX"],
                        "q": "is:unread",
                    },
                    "options": {
                        "dataPropertyAttachmentsPrefixName": "attachment_",
                    },
                },
                "typeVersion": 2.1,
            },
        ],
        "connections": {
            "Webhook Trigger": {
                "main": [[{"node": "Gmail - Leggi Email", "type": "main", "index": 0}]]
            }
        },
        "settings": {"executionOrder": "v1"},
    }

    # 2. Workflow: Invia email
    send_workflow = {
        "name": "HERMES - Mail Send",
        "nodes": [
            {
                "id": "webhook-trigger",
                "name": "Webhook Trigger",
                "type": "n8n-nodes-base.webhook",
                "position": [250, 300],
                "parameters": {
                    "path": "hermes-mail-send",
                    "httpMethod": "POST",
                    "responseMode": "lastNode",
                },
                "typeVersion": 2,
            },
            {
                "id": "gmail-send",
                "name": "Gmail - Invia",
                "type": "n8n-nodes-base.gmail",
                "position": [500, 300],
                "parameters": {
                    "operation": "send",
                    "sendTo": "={{ $json.to }}",
                    "subject": "={{ $json.subject }}",
                    "message": "={{ $json.body }}",
                },
                "typeVersion": 2.1,
            },
        ],
        "connections": {
            "Webhook Trigger": {
                "main": [[{"node": "Gmail - Invia", "type": "main", "index": 0}]]
            }
        },
        "settings": {"executionOrder": "v1"},
    }

    # 3. Workflow: Archivia email
    archive_workflow = {
        "name": "HERMES - Mail Archive",
        "nodes": [
            {
                "id": "webhook-trigger",
                "name": "Webhook Trigger",
                "type": "n8n-nodes-base.webhook",
                "position": [250, 300],
                "parameters": {
                    "path": "hermes-mail-archive",
                    "httpMethod": "POST",
                    "responseMode": "lastNode",
                },
                "typeVersion": 2,
            },
            {
                "id": "gmail-archive",
                "name": "Gmail - Archivia",
                "type": "n8n-nodes-base.gmail",
                "position": [500, 300],
                "parameters": {
                    "operation": "markAsRead",
                    "messageId": "={{ $json.message_id }}",
                },
                "typeVersion": 2.1,
            },
        ],
        "connections": {
            "Webhook Trigger": {
                "main": [[{"node": "Gmail - Archivia", "type": "main", "index": 0}]]
            }
        },
        "settings": {"executionOrder": "v1"},
    }

    try:
        for wf in [fetch_workflow, send_workflow, archive_workflow]:
            result = await import_workflow(wf)
            workflows_created.append(f"  \u2705 {wf['name']} (ID: {result.get('id', 'N/A')})")
            logger.info(f"MailMind workflow creato: {wf['name']}")
    except Exception as e:
        return f"\u26a0\ufe0f Errore creazione workflow MailMind: {e}"

    return (
        "\U0001f4e7 MailMind \u2014 Setup Completato!\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        "Workflow n8n creati:\n"
        + "\n".join(workflows_created) + "\n\n"
        "\u26a0\ufe0f IMPORTANTE: vai su n8n e:\n"
        "1. Collega le credenziali Gmail a ogni workflow\n"
        "2. Attiva i workflow\n"
        "3. Copia i webhook URL e comunicali a HERMES"
    )


async def _generate_digest(bot: Bot | None = None) -> str:
    """Genera digest email (quando i webhook saranno configurati)."""
    return (
        "\U0001f4e7 MailMind \u2014 Digest\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        "Per attivare il digest automatico:\n"
        "1. Scrivi 'configura mailmind' per creare i workflow n8n\n"
        "2. Configura le credenziali Gmail su n8n\n"
        "3. Attiva i workflow\n\n"
        "Una volta attivo, il digest arriver\u00e0 ogni sera alle 19:00"
    )


async def _handle_delete(user_text: str) -> str:
    """Elimina email via n8n."""
    return "\U0001f4e7 Per eliminare email, prima configura MailMind con: 'configura mailmind'"


async def _handle_archive(user_text: str) -> str:
    """Archivia email via n8n."""
    return "\U0001f4e7 Per archiviare email, prima configura MailMind con: 'configura mailmind'"


async def _handle_reply(user_text: str) -> str:
    """Rispondi a email via n8n."""
    return "\U0001f4e7 Per rispondere, prima configura MailMind con: 'configura mailmind'"


async def _handle_draft(user_text: str) -> str:
    """Genera bozza risposta."""
    return "\U0001f4e7 Per generare bozze, prima configura MailMind con: 'configura mailmind'"


async def _handle_who_is(user_text: str) -> str:
    """Cerca info su mittente nella KB."""
    from core import knowledge_base as kb
    # Estrai nome dal messaggio
    name = user_text.lower().replace("chi è", "").replace("chi e'", "").replace("who is", "").strip()
    result = await kb.search_entity(name)
    if result:
        return f"\U0001f464 {name}:\n{result}"
    return f"\U0001f464 {name}: non trovato nella Knowledge Base. Dimmi chi \u00e8 e lo salvo!"


async def _smart_mail_handling(user_text: str) -> str:
    """Gestione intelligente richieste email ambigue."""
    response = await chat(
        messages=[
            {"role": "system", "content": (
                "Sei MailMind di HERMES. L'utente chiede qualcosa relativo alle email. "
                "Il sistema funziona tramite n8n webhooks per Gmail. "
                "Se il sistema non \u00e8 ancora configurato, guidalo a farlo. "
                "Rispondi in italiano, breve e operativo."
            )},
            {"role": "user", "content": user_text},
        ],
        complexity=TaskComplexity.LIGHT,
        temperature=0.3,
        max_tokens=512,
    )
    return response
