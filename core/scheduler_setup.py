"""
HERMES OS — n8n Scheduler Setup
Crea e attiva workflow n8n che fungono da scheduler esterno.
n8n e sempre attivo (cloud separato) e sveglia Render ai tempi giusti.
Nessuna credenziale Gmail/Calendar in n8n — solo HTTP request verso HERMES.
"""

import logging
import os

import config
from agents.pipeline_forge.n8n_client import (
    import_workflow,
    activate_workflow,
    list_workflows,
)

logger = logging.getLogger("hermes.scheduler_setup")


def _render_url() -> str:
    """URL pubblico di HERMES su Render."""
    url = os.environ.get("RENDER_EXTERNAL_URL", "")
    if not url:
        raise ValueError(
            "RENDER_EXTERNAL_URL non configurato. "
            "Serve l'URL pubblico del servizio Render."
        )
    return url.rstrip("/")


def _build_schedule_workflow(
    name: str,
    cron_hour: int,
    cron_minute: int,
    http_method: str,
    endpoint: str,
    interval_minutes: int | None = None,
) -> dict:
    """
    Genera un workflow n8n con Schedule Trigger → HTTP Request.
    Se interval_minutes e dato, usa intervallo invece di cron.
    """
    render = _render_url()
    url = f"{render}{endpoint}"

    # Schedule trigger node
    if interval_minutes:
        # Intervallo (per keepalive)
        schedule_params = {
            "rule": {
                "interval": [{"field": "minutes", "minutesInterval": interval_minutes}]
            }
        }
    else:
        # Cron (per job schedulati)
        schedule_params = {
            "rule": {
                "interval": [
                    {
                        "field": "cronExpression",
                        "expression": f"{cron_minute} {cron_hour} * * *",
                    }
                ]
            }
        }

    return {
        "name": name,
        "nodes": [
            {
                "id": "schedule-trigger",
                "name": "Schedule Trigger",
                "type": "n8n-nodes-base.scheduleTrigger",
                "position": [250, 300],
                "parameters": schedule_params,
                "typeVersion": 1.2,
            },
            {
                "id": "http-request",
                "name": "Call HERMES",
                "type": "n8n-nodes-base.httpRequest",
                "position": [500, 300],
                "parameters": {
                    "url": url,
                    "method": http_method,
                    "options": {
                        "timeout": 120000,  # 120s per cold start Render
                    },
                },
                "typeVersion": 4.2,
            },
        ],
        "connections": {
            "Schedule Trigger": {
                "main": [[{"node": "Call HERMES", "type": "main", "index": 0}]]
            }
        },
        "settings": {
            "executionOrder": "v1",
            "timezone": "Europe/Rome",
        },
    }


# ─── Definizioni dei 4 workflow ──────────────────────────

SCHEDULER_WORKFLOWS = [
    {
        "name": "HERMES - Keepalive",
        "cron_hour": 0,
        "cron_minute": 0,
        "http_method": "GET",
        "endpoint": "/keepalive",
        "interval_minutes": 14,
    },
    {
        "name": "HERMES - Morning Brief",
        "cron_hour": 8,
        "cron_minute": 30,
        "http_method": "POST",
        "endpoint": "/trigger/brief",
        "interval_minutes": None,
    },
    {
        "name": "HERMES - Mail Digest",
        "cron_hour": 9,
        "cron_minute": 0,
        "http_method": "POST",
        "endpoint": "/trigger/digest",
        "interval_minutes": None,
    },
    {
        "name": "HERMES - Evening Program",
        "cron_hour": 21,
        "cron_minute": 0,
        "http_method": "POST",
        "endpoint": "/trigger/evening",
        "interval_minutes": None,
    },
]


async def setup_n8n_schedulers() -> str:
    """
    Crea e attiva i 4 workflow scheduler su n8n.
    Ritorna messaggio di conferma per Telegram.
    """
    if not config.N8N_BASE_URL or not config.N8N_API_KEY:
        return (
            "\u26a0\ufe0f N8N_BASE_URL o N8N_API_KEY non configurati.\n"
            "Servono per creare i workflow scheduler su n8n."
        )

    try:
        _render_url()
    except ValueError as e:
        return f"\u26a0\ufe0f {e}"

    # Check se esistono gia workflow con gli stessi nomi
    try:
        existing = await list_workflows()
        existing_names = {wf.get("name", "") for wf in existing}
    except Exception as e:
        logger.warning(f"Impossibile listare workflow n8n: {e}")
        existing_names = set()

    results = []
    for wf_def in SCHEDULER_WORKFLOWS:
        name = wf_def["name"]

        # Skip se esiste gia
        if name in existing_names:
            results.append(f"  \u2139\ufe0f {name} — gia esistente, skip")
            logger.info(f"Scheduler workflow '{name}' gia esistente, skip")
            continue

        try:
            # Genera JSON workflow
            workflow_json = _build_schedule_workflow(
                name=name,
                cron_hour=wf_def["cron_hour"],
                cron_minute=wf_def["cron_minute"],
                http_method=wf_def["http_method"],
                endpoint=wf_def["endpoint"],
                interval_minutes=wf_def.get("interval_minutes"),
            )

            # Importa su n8n
            result = await import_workflow(workflow_json)
            wf_id = result.get("id", "?")

            # Attiva
            await activate_workflow(wf_id, active=True)

            results.append(f"  \u2705 {name} (ID: {wf_id}) — creato e attivato")
            logger.info(f"Scheduler workflow '{name}' creato e attivato: {wf_id}")

        except Exception as e:
            results.append(f"  \u274c {name} — errore: {str(e)[:100]}")
            logger.error(f"Errore creazione scheduler '{name}': {e}")

    render = _render_url()

    return (
        "\u2699\ufe0f HERMES — Setup Scheduler n8n\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        + "\n".join(results) + "\n\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"Target: {render}\n"
        "Keepalive: ogni 14 min\n"
        "Brief: 08:30 | Digest: 09:00 | Serale: 21:00\n"
        "Timezone: Europe/Rome"
    )
