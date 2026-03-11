"""
HERMES OS — Memory
Log conversazioni e contesto storico per gli agenti.
Mantiene contesto in-memory per la sessione + persistenza su Drive.
"""

import logging
from datetime import datetime, timezone
from collections import deque
from typing import Optional

from core import knowledge_base as kb

logger = logging.getLogger("hermes.memory")

# Contesto conversazione in-memory (ultimi N messaggi)
MAX_CONTEXT_MESSAGES = 50
_conversation_history: deque[dict] = deque(maxlen=MAX_CONTEXT_MESSAGES)


def add_message(role: str, content: str, metadata: dict | None = None):
    """Aggiunge un messaggio al contesto conversazione."""
    entry = {
        "role": role,
        "content": content,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "metadata": metadata or {},
    }
    _conversation_history.append(entry)


def get_context(last_n: int = 10) -> list[dict]:
    """
    Ritorna gli ultimi N messaggi come contesto per LLM.
    Formato: [{"role": "user"|"assistant", "content": "..."}]
    """
    messages = list(_conversation_history)[-last_n:]
    return [{"role": m["role"], "content": m["content"]} for m in messages]


def get_full_history() -> list[dict]:
    """Ritorna tutta la cronologia in-memory."""
    return list(_conversation_history)


async def log_task_completion(
    task_description: str,
    agent: str,
    outcome: str,
    client: str | None = None,
):
    """
    Logga il completamento di un task su Drive.
    Viene scritto in history/tasks_done.md
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    entry = f"### [{now}] {agent}\n"
    if client:
        entry += f"**Cliente**: {client}\n"
    entry += f"**Task**: {task_description}\n"
    entry += f"**Esito**: {outcome}\n"

    await kb.log_history("tasks_done", entry)
    logger.info(f"Task logged: {task_description} → {outcome}")


async def log_decision(
    decision: str,
    reasoning: str,
    agent: str,
    client: str | None = None,
):
    """
    Logga una decisione strategica su Drive.
    Viene scritto in history/decisions.md
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    entry = f"### [{now}] {agent}\n"
    if client:
        entry += f"**Cliente**: {client}\n"
    entry += f"**Decisione**: {decision}\n"
    entry += f"**Ragionamento**: {reasoning}\n"

    await kb.log_history("decisions", entry)
    logger.info(f"Decision logged: {decision}")
