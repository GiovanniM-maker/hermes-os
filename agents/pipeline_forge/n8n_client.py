"""
HERMES OS — n8n API Client
Interfaccia con l'istanza n8n cloud per PipelineForge.
"""

import logging

import httpx

import config

logger = logging.getLogger("hermes.n8n")


def _get_headers() -> dict:
    """Headers per le chiamate n8n API."""
    return {
        "X-N8N-API-KEY": config.N8N_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _base_url() -> str:
    """URL base n8n senza trailing slash."""
    return config.N8N_BASE_URL.rstrip("/")


async def import_workflow(workflow_json: dict) -> dict:
    """
    Importa un workflow su n8n.
    POST /api/v1/workflows

    Returns:
        {"id": str, "name": str, ...}
    """
    url = f"{_base_url()}/api/v1/workflows"
    logger.info(f"Importing workflow to n8n: {url}")

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            url,
            json=workflow_json,
            headers=_get_headers(),
        )
        response.raise_for_status()
        data = response.json()
        logger.info(f"Workflow imported: id={data.get('id')}, name={data.get('name')}")
        return data


async def execute_workflow(workflow_id: str) -> dict:
    """
    Esegue un workflow di test.
    POST /api/v1/workflows/{id}/execute

    Returns:
        {"id": execution_id, ...}
    """
    url = f"{_base_url()}/api/v1/workflows/{workflow_id}/execute"
    logger.info(f"Executing workflow {workflow_id}")

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            url,
            json={},
            headers=_get_headers(),
        )
        response.raise_for_status()
        return response.json()


async def get_execution_result(execution_id: str) -> dict:
    """
    Recupera il risultato di un'esecuzione.
    GET /api/v1/executions/{id}

    Returns:
        {"finished": bool, "data": {...}, "stoppedAt": str|None, ...}
    """
    url = f"{_base_url()}/api/v1/executions/{execution_id}"
    logger.info(f"Getting execution result: {execution_id}")

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            url,
            headers=_get_headers(),
        )
        response.raise_for_status()
        return response.json()


async def list_workflows() -> list[dict]:
    """Lista tutti i workflow su n8n."""
    url = f"{_base_url()}/api/v1/workflows"

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(url, headers=_get_headers())
        response.raise_for_status()
        data = response.json()
        return data.get("data", [])


async def activate_workflow(workflow_id: str, active: bool = True) -> dict:
    """Attiva/disattiva un workflow."""
    url = f"{_base_url()}/api/v1/workflows/{workflow_id}"

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.patch(
            url,
            json={"active": active},
            headers=_get_headers(),
        )
        response.raise_for_status()
        return response.json()
