"""
HERMES OS — TaskBot Orchestrator
Aggrega task da tutte le fonti e presenta brief prioritizzato.
Comandi: aggiungi task, fatto, sposta, task [cliente]
"""

import json
import logging
from datetime import datetime, timezone

from telegram import Bot

import config
from core.llm_router import chat, TaskComplexity
from core import knowledge_base as kb
from core import memory

logger = logging.getLogger("hermes.taskbot")

# Task in-memory (in futuro: persistenza su Drive/Sheets)
_tasks: list[dict] = []
_task_counter: int = 0


async def handle_request(user_text: str, bot: Bot | None = None) -> str:
    """Entry point TaskBot. Gestisce comandi task."""
    text_lower = user_text.lower().strip()

    # Parsing comandi
    if text_lower.startswith("aggiungi task:") or text_lower.startswith("aggiungi task "):
        description = user_text.split(":", 1)[-1].strip() if ":" in user_text else user_text[14:].strip()
        return await _add_task(description)

    elif text_lower.startswith("fatto "):
        try:
            task_num = int(text_lower.replace("fatto ", "").strip())
            return await _complete_task(task_num)
        except ValueError:
            return "\u26a0\ufe0f Formato: 'fatto [numero]' — es. 'fatto 3'"

    elif text_lower.startswith("sposta ") and "domani" in text_lower:
        try:
            parts = text_lower.replace("sposta ", "").replace(" a domani", "").strip()
            task_num = int(parts)
            return await _postpone_task(task_num)
        except ValueError:
            return "\u26a0\ufe0f Formato: 'sposta [numero] a domani'"

    elif text_lower.startswith("task "):
        # Filtra per cliente
        client_name = user_text[5:].strip()
        return await _filter_tasks(client_name)

    elif text_lower in ("tasks", "task", "lista task", "le mie task"):
        return await _list_tasks()

    elif text_lower in ("brief", "briefing", "buongiorno"):
        return await _morning_brief()

    else:
        # Usa LLM per capire cosa vuole
        return await _smart_task_handling(user_text)


async def _add_task(description: str, client: str | None = None) -> str:
    """Aggiunge una task manualmente."""
    global _task_counter
    _task_counter += 1

    # Stima tempo con LLM
    estimate = await _estimate_time(description)

    task = {
        "id": _task_counter,
        "description": description,
        "client": client,
        "created": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
        "estimate_minutes": estimate,
        "priority": "normal",
    }
    _tasks.append(task)

    logger.info(f"Task aggiunta: #{_task_counter} — {description}")

    return (
        f"\u2705 Task #{_task_counter} aggiunta\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"\U0001f4cb {description}\n"
        f"\u23f1\ufe0f Stima: ~{estimate} min\n"
        f"{f'\U0001f465 Cliente: {client}' if client else ''}"
    )


async def _complete_task(task_num: int) -> str:
    """Marca una task come completata."""
    for task in _tasks:
        if task["id"] == task_num and task["status"] == "pending":
            task["status"] = "done"
            task["completed_at"] = datetime.now(timezone.utc).isoformat()

            # Log su Drive
            await memory.log_task_completion(
                task_description=task["description"],
                agent="TaskBot",
                outcome="Completata",
                client=task.get("client"),
            )

            return f"\u2705 Task #{task_num} completata: {task['description']}"

    return f"\u26a0\ufe0f Task #{task_num} non trovata o gia\u0300 completata"


async def _postpone_task(task_num: int) -> str:
    """Posticipa una task a domani."""
    for task in _tasks:
        if task["id"] == task_num and task["status"] == "pending":
            task["postponed"] = True
            return f"\u23f0 Task #{task_num} posticipata a domani: {task['description']}"

    return f"\u26a0\ufe0f Task #{task_num} non trovata"


async def _filter_tasks(client_name: str) -> str:
    """Filtra task per cliente."""
    filtered = [t for t in _tasks
                if t["status"] == "pending"
                and t.get("client", "").lower() == client_name.lower()]

    if not filtered:
        return f"\U0001f4cb Nessuna task attiva per {client_name}"

    lines = [f"\U0001f4cb Task per {client_name}\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"]
    for t in filtered:
        lines.append(f"  {t['id']}. {t['description']} (~{t['estimate_minutes']} min)")
    return "\n".join(lines)


async def _list_tasks() -> str:
    """Lista tutte le task attive."""
    pending = [t for t in _tasks if t["status"] == "pending"]

    if not pending:
        return "\U0001f4cb Nessuna task attiva. Tutto fatto! \U0001f389"

    lines = ["\U0001f4cb Task Attive\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501"]
    total_time = 0
    for t in pending:
        prefix = "\U0001f534" if t.get("priority") == "urgent" else "\u26a1" if t["estimate_minutes"] <= 15 else "\U0001f4cb"
        client = f" \u2014 {t['client']}" if t.get("client") else ""
        lines.append(f"  {prefix} {t['id']}. {t['description']}{client} (~{t['estimate_minutes']} min)")
        total_time += t["estimate_minutes"]

    lines.append(f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501")
    lines.append(f"Totale: {len(pending)} task \u2014 ~{total_time} min stimati")

    return "\n".join(lines)


async def _morning_brief() -> str:
    """Genera il brief mattutino."""
    pending = [t for t in _tasks if t["status"] == "pending"]

    if not pending:
        return (
            "\u2600\ufe0f HERMES TASKBOT \u2014 Buongiorno Juan\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            "\u2705 Nessuna task in coda. Giornata libera!\n"
            "Fammi sapere se devo aggiungere qualcosa."
        )

    quick_wins = [t for t in pending if t["estimate_minutes"] <= 15]
    main_tasks = [t for t in pending if 15 < t["estimate_minutes"] <= 120]
    heavy = [t for t in pending if t["estimate_minutes"] > 120]

    lines = [
        "\u2600\ufe0f HERMES TASKBOT \u2014 Buongiorno Juan",
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501",
    ]

    if quick_wins:
        lines.append("\u26a1 QUICK WINS (< 15 min):")
        for t in quick_wins:
            client = f" \u2014 {t['client']}" if t.get("client") else ""
            lines.append(f"  {t['id']}. {t['description']}{client} \u2014 ~{t['estimate_minutes']} min")
        lines.append("")

    if main_tasks:
        lines.append("\U0001f4cb TASK PRINCIPALI:")
        for t in main_tasks:
            client = f" \u2014 {t['client']}" if t.get("client") else ""
            lines.append(f"  {t['id']}. {t['description']}{client} \u2014 ~{t['estimate_minutes']} min")
        lines.append("")

    if heavy:
        lines.append("\U0001f534 IMPEGNATIVE (> 2h):")
        for t in heavy:
            client = f" \u2014 {t['client']}" if t.get("client") else ""
            lines.append(f"  {t['id']}. {t['description']}{client} \u2014 ~{t['estimate_minutes']} min")
        lines.append("")

    total = sum(t["estimate_minutes"] for t in pending)
    hours = total // 60
    mins = total % 60
    lines.append("\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501")
    lines.append(f"Totale: {len(pending)} task \u2014 ~{hours}h {mins}m")

    return "\n".join(lines)


async def _estimate_time(description: str) -> int:
    """Stima tempo in minuti per una task usando LLM."""
    try:
        response = await chat(
            messages=[
                {"role": "system", "content": (
                    "Stima il tempo in minuti per completare questa task. "
                    "Rispondi SOLO con un numero intero (minuti). "
                    "Considera: task semplice 5-15 min, media 30-60 min, complessa 120+ min."
                )},
                {"role": "user", "content": description},
            ],
            complexity=TaskComplexity.LIGHT,
            temperature=0.1,
            max_tokens=16,
        )
        return int(response.strip())
    except (ValueError, Exception):
        return 30  # Default 30 minuti


async def _smart_task_handling(user_text: str) -> str:
    """Usa LLM per interpretare richieste task ambigue."""
    response = await chat(
        messages=[
            {"role": "system", "content": (
                "Sei TaskBot di HERMES. L'utente sta facendo una richiesta relativa alle task. "
                "Interpreta cosa vuole e rispondi con l'azione da fare. "
                "Se vuole aggiungere una task, estraila. "
                "Se chiede info, rispondi. "
                "Rispondi in italiano, breve e operativo."
            )},
            {"role": "user", "content": user_text},
        ],
        complexity=TaskComplexity.LIGHT,
        temperature=0.3,
        max_tokens=512,
    )

    # Se l'LLM suggerisce di aggiungere una task, fallo
    if "aggiungi" in response.lower() or "aggiunta" in response.lower():
        return await _add_task(user_text)

    return response


# ─── Task da fonti esterne (usato da MailMind, ecc.) ─────

# ─── Scheduled Brief (chiamato da APScheduler) ──────────

async def scheduled_morning_brief():
    """Chiamato ogni mattina alle 08:30 da APScheduler."""
    from telegram import Bot as TgBot

    if not config.TELEGRAM_TASKS_TOKEN and not config.TELEGRAM_MASTER_TOKEN:
        logger.warning("TaskBot scheduled: nessun token bot configurato")
        return

    # Usa il tasks bot se disponibile, altrimenti master
    token = config.TELEGRAM_TASKS_TOKEN or config.TELEGRAM_MASTER_TOKEN
    bot = TgBot(token=token)

    try:
        brief = await _morning_brief()
        await bot.send_message(chat_id=config.TELEGRAM_CHAT_ID, text=brief)
        logger.info("TaskBot: brief mattutino inviato")
    except Exception as e:
        logger.error(f"TaskBot scheduled brief error: {e}")


async def add_external_task(
    description: str,
    source: str,
    client: str | None = None,
    priority: str = "normal",
) -> int:
    """
    Aggiunge una task da una fonte esterna (MailMind, AdsWatch, ecc.).
    Ritorna l'ID della task.
    """
    global _task_counter
    _task_counter += 1

    estimate = await _estimate_time(description)

    task = {
        "id": _task_counter,
        "description": description,
        "client": client,
        "source": source,
        "created": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
        "estimate_minutes": estimate,
        "priority": priority,
    }
    _tasks.append(task)

    logger.info(f"External task #{_task_counter} da {source}: {description}")
    return _task_counter
