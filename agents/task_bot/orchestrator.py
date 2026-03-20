"""
HERMES OS — TaskBot Orchestrator
Gestione task + calendario Google Calendar.
Comandi task: aggiungi task, fatto, sposta, task [cliente]
Calendario: linguaggio naturale → azioni Google Calendar
Digest serale: programma domani + reminder settimana
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from telegram import Bot

import config
from core.llm_router import chat, TaskComplexity
from core import knowledge_base as kb
from core import memory
from core import gcal_client
from core.question_engine import ask_questions

logger = logging.getLogger("hermes.taskbot")

_TZ = ZoneInfo("Europe/Rome")

# ─── Meta Keywords ────────────────────────────────────────
_META_KEYWORDS = (
    "cosa fai", "chi sei", "come funzioni", "help", "aiuto",
    "cosa puoi fare", "che sai fare", "presentati", "info",
    "cosa sai", "come ti uso", "istruzioni",
    "potresti", "puoi fare", "sei capace", "sai fare",
    "riesci a", "funzionalità", "capacità",
)

# Verbi che indicano una richiesta concreta (NON meta)
_ACTION_VERBS = (
    "aggiungi", "fatto", "sposta", "completa", "crea task",
    "task:", "brief", "briefing",
    "metti", "fissa", "segna", "prenota", "cancella",
    "sposta", "agenda", "calendario", "domani", "settimana",
    "programma", "impegni", "impegno", "appuntamento",
)

# Calendar keywords per routing
_CALENDAR_KEYWORDS = (
    "calendario", "agenda", "impegn", "appuntament",
    "riunione", "call", "meeting", "evento",
    "domani ho", "cosa ho domani", "cosa ho oggi",
    "cosa c'è domani", "programma domani", "programma settimana",
    "sono libero", "slot liberi", "quando sono libero",
    "metti un", "fissa un", "segna un", "prenota",
    "sposta la", "cancella la", "cancella l'",
    "questa settimana", "prossima settimana",
)

# Task in-memory (in futuro: persistenza su Drive/Sheets)
_tasks: list[dict] = []
_task_counter: int = 0


async def handle_request(user_text: str, bot: Bot | None = None) -> str:
    """Entry point TaskBot. Gestisce comandi task e calendario."""
    text_lower = user_text.lower().strip()

    # ─── Pre-check: domande informative/meta ──────────────
    if _is_meta_query(text_lower):
        return await _handle_meta(user_text)

    # ─── Calendario (priorità alta — check keyword) ───────
    if _is_calendar_request(text_lower):
        if not gcal_client.is_configured():
            return (
                "\u26a0\ufe0f Calendario non configurato.\n"
                "Servono le env vars su Render:\n"
                "- GMAIL_CLIENT_ID\n"
                "- GMAIL_CLIENT_SECRET\n"
                "- GMAIL_REFRESH_TOKEN\n\n"
                "Configurale e riprova."
            )
        return await _handle_calendar(user_text)

    # ─── Comandi task espliciti ───────────────────────────
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
        client_name = user_text[5:].strip()
        return await _filter_tasks(client_name)

    elif text_lower in ("tasks", "task", "lista task", "le mie task"):
        return await _list_tasks()

    elif text_lower in ("brief", "briefing", "buongiorno"):
        return await _morning_brief()

    elif text_lower in ("programma", "stasera", "programma domani"):
        return await _evening_program()

    else:
        return await _smart_handling(user_text, bot=bot)


# ─── Meta / Info Queries ──────────────────────────────────

def _is_meta_query(text_lower: str) -> bool:
    """Rileva domande informative/meta su TaskBot."""
    if any(v in text_lower for v in _ACTION_VERBS):
        return False
    if any(kw in text_lower for kw in _META_KEYWORDS):
        return True
    if len(text_lower) < 15 and "?" in text_lower:
        return True
    return False


async def _handle_meta(user_text: str) -> str:
    """Rispondi a domande informative su TaskBot."""
    from core.identity import get_meta_system_prompt

    return await chat(
        messages=[
            {"role": "system", "content": get_meta_system_prompt("TaskBot")},
            {"role": "user", "content": user_text},
        ],
        complexity=TaskComplexity.LIGHT,
        temperature=0.5,
        max_tokens=512,
    )


# ═══════════════════════════════════════════════════════════
# CALENDARIO
# ═══════════════════════════════════════════════════════════

def _is_calendar_request(text_lower: str) -> bool:
    """Rileva se il messaggio riguarda il calendario."""
    return any(kw in text_lower for kw in _CALENDAR_KEYWORDS)


async def _handle_calendar(user_text: str) -> str:
    """
    Gestisce richieste calendario via NL.
    1. LLM parsa l'intent in JSON strutturato
    2. Esegue l'azione su Google Calendar
    3. Ritorna risposta formattata
    """
    now = datetime.now(_TZ)
    today_str = now.strftime("%A %d %B %Y")
    weekday_it = {
        "Monday": "lunedi", "Tuesday": "martedi", "Wednesday": "mercoledi",
        "Thursday": "giovedi", "Friday": "venerdi", "Saturday": "sabato",
        "Sunday": "domenica",
    }
    day_name = weekday_it.get(now.strftime("%A"), now.strftime("%A"))

    system_prompt = f"""Sei il calendario di HERMES OS. Analizza la richiesta e rispondi in JSON.

OGGI: {today_str} ({day_name})
ORA CORRENTE: {now.strftime("%H:%M")}
TIMEZONE: Europe/Rome

AZIONI POSSIBILI:
- "list_today": mostra eventi di oggi
- "list_tomorrow": mostra eventi di domani
- "list_week": mostra eventi della settimana
- "list_date": mostra eventi di una data specifica
- "create": crea un nuovo evento
- "delete": elimina un evento (per titolo/descrizione)
- "update": modifica un evento esistente
- "free_slots": trova slot liberi in una data

FORMATO RISPOSTA (JSON):
{{
  "action": "list_today"|"list_tomorrow"|"list_week"|"list_date"|"create"|"delete"|"update"|"free_slots",
  "date": "YYYY-MM-DD" (se serve una data specifica),
  "summary": "titolo evento" (per create/delete/update),
  "start_time": "HH:MM" (per create — ora inizio),
  "end_time": "HH:MM" (per create — ora fine, opzionale),
  "duration_minutes": N (per create — durata se end_time non dato, default 60),
  "location": "luogo" (opzionale),
  "description": "descrizione" (opzionale),
  "changes": {{"summary": "nuovo titolo", "start_time": "HH:MM", ...}} (per update)
}}

REGOLE:
- Per "domani" usa la data di domani
- Per "lunedi" calcola il prossimo lunedi
- Se l'utente dice "call 30 minuti", duration_minutes = 30
- Se dice "dalle 15 alle 16:30", start_time = "15:00", end_time = "16:30"
- Se l'utente non specifica end_time ne durata, default 60 minuti
- Rispondi SOLO col JSON, nient'altro."""

    analysis = await chat(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        complexity=TaskComplexity.LIGHT,
        temperature=0.1,
        max_tokens=512,
        json_mode=True,
    )

    try:
        data = json.loads(analysis.strip())
    except json.JSONDecodeError:
        logger.error(f"Calendar NL parse failed: {analysis[:200]}")
        return "\u26a0\ufe0f Non ho capito la richiesta calendario. Riprova con piu dettagli."

    action = data.get("action", "list_today")

    try:
        if action == "list_today":
            return await _cal_list_events(now)

        elif action == "list_tomorrow":
            tomorrow = now + timedelta(days=1)
            return await _cal_list_events(tomorrow)

        elif action == "list_week":
            return await _cal_list_week()

        elif action == "list_date":
            date = _parse_date(data.get("date", ""))
            return await _cal_list_events(date)

        elif action == "create":
            return await _cal_create_event(data, now)

        elif action == "delete":
            return await _cal_delete_event(data, now)

        elif action == "update":
            return await _cal_update_event(data, now)

        elif action == "free_slots":
            date = _parse_date(data.get("date", "")) if data.get("date") else now
            duration = data.get("duration_minutes", 60)
            return await _cal_free_slots(date, duration)

        else:
            return "\u26a0\ufe0f Azione calendario non riconosciuta."

    except Exception as e:
        logger.error(f"Calendar action error: {e}")
        return f"\u26a0\ufe0f Errore calendario: {str(e)[:300]}"


def _parse_date(date_str: str) -> datetime:
    """Parsa stringa data YYYY-MM-DD in datetime con timezone."""
    if not date_str:
        return datetime.now(_TZ)
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.replace(tzinfo=_TZ)
    except ValueError:
        return datetime.now(_TZ)


def _format_time(iso_str: str) -> str:
    """Formatta un ISO datetime in HH:MM."""
    try:
        dt = datetime.fromisoformat(iso_str)
        return dt.strftime("%H:%M")
    except (ValueError, TypeError):
        return iso_str[:5] if iso_str else ""


def _format_date_it(dt: datetime) -> str:
    """Formatta data in italiano: 'venerdi 20 marzo'."""
    giorni = ["lunedi", "martedi", "mercoledi", "giovedi", "venerdi", "sabato", "domenica"]
    mesi = ["", "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
            "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"]
    return f"{giorni[dt.weekday()]} {dt.day} {mesi[dt.month]}"


async def _cal_list_events(date: datetime) -> str:
    """Lista eventi di un giorno."""
    events = await gcal_client.get_events_for_date(date)
    date_label = _format_date_it(date)

    if not events:
        return (
            f"\U0001f4c5 Calendario — {date_label}\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            "\u2705 Nessun impegno. Giornata libera!"
        )

    lines = [
        f"\U0001f4c5 Calendario — {date_label}",
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501",
    ]

    for ev in events:
        if ev["all_day"]:
            lines.append(f"  \U0001f30d {ev['summary']} (tutto il giorno)")
        else:
            start = _format_time(ev["start"])
            end = _format_time(ev["end"])
            loc = f" \U0001f4cd {ev['location']}" if ev["location"] else ""
            lines.append(f"  \u23f0 {start}–{end}  {ev['summary']}{loc}")

    lines.append(f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501")
    lines.append(f"{len(events)} impegni")

    return "\n".join(lines)


async def _cal_list_week() -> str:
    """Lista eventi della settimana."""
    events = await gcal_client.get_week_events()
    now = datetime.now(_TZ)

    if not events:
        return (
            "\U0001f4c5 Settimana\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            "\u2705 Settimana libera!"
        )

    # Raggruppa per giorno
    by_day: dict[str, list[dict]] = {}
    for ev in events:
        date_str = ev["start"][:10] if ev["start"] else ""
        by_day.setdefault(date_str, []).append(ev)

    lines = [
        "\U0001f4c5 Agenda settimana",
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501",
    ]

    for date_str in sorted(by_day.keys()):
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=_TZ)
            label = _format_date_it(dt)
            is_today = dt.date() == now.date()
            marker = " (OGGI)" if is_today else ""
        except ValueError:
            label = date_str
            marker = ""

        lines.append(f"\n\U0001f4cc {label.upper()}{marker}")
        for ev in by_day[date_str]:
            if ev["all_day"]:
                lines.append(f"    \U0001f30d {ev['summary']}")
            else:
                start = _format_time(ev["start"])
                end = _format_time(ev["end"])
                lines.append(f"    {start}–{end}  {ev['summary']}")

    lines.append(f"\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501")
    lines.append(f"Totale: {len(events)} impegni questa settimana")

    return "\n".join(lines)


async def _cal_create_event(data: dict, now: datetime) -> str:
    """Crea un evento dal JSON parsato dal LLM."""
    summary = data.get("summary", "Evento")
    date_str = data.get("date", now.strftime("%Y-%m-%d"))
    start_time = data.get("start_time", "09:00")
    end_time = data.get("end_time", "")
    duration = data.get("duration_minutes", 60)
    location = data.get("location", "")
    description = data.get("description", "")

    # Componi datetime
    date = _parse_date(date_str)
    h, m = map(int, start_time.split(":"))
    start_dt = date.replace(hour=h, minute=m, second=0)

    if end_time:
        eh, em = map(int, end_time.split(":"))
        end_dt = date.replace(hour=eh, minute=em, second=0)
    else:
        end_dt = start_dt + timedelta(minutes=duration)

    result = await gcal_client.create_event(
        summary=summary,
        start=start_dt,
        end=end_dt,
        description=description,
        location=location,
    )

    date_label = _format_date_it(start_dt)
    loc_line = f"\n\U0001f4cd {location}" if location else ""

    return (
        f"\u2705 Evento creato!\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"\U0001f4c5 {summary}\n"
        f"\U0001f4cc {date_label}\n"
        f"\u23f0 {start_time} – {end_dt.strftime('%H:%M')}"
        f"{loc_line}"
    )


async def _cal_delete_event(data: dict, now: datetime) -> str:
    """Elimina un evento cercandolo per titolo."""
    search_summary = data.get("summary", "").lower()
    date_str = data.get("date", "")

    if date_str:
        date = _parse_date(date_str)
    else:
        # Cerca oggi e domani
        date = now

    events = await gcal_client.get_events_for_date(date)
    if not events and not date_str:
        events = await gcal_client.get_events_for_date(now + timedelta(days=1))

    # Trova match
    match = None
    for ev in events:
        if search_summary in ev["summary"].lower():
            match = ev
            break

    if not match:
        return f"\u26a0\ufe0f Nessun evento trovato con '{data.get('summary', '')}'"

    ok = await gcal_client.delete_event(match["id"])
    if ok:
        return f"\u2705 Evento eliminato: {match['summary']}"
    return f"\u26a0\ufe0f Errore nell'eliminazione di '{match['summary']}'"


async def _cal_update_event(data: dict, now: datetime) -> str:
    """Aggiorna un evento cercandolo per titolo."""
    search_summary = data.get("summary", "").lower()
    changes = data.get("changes", {})
    date_str = data.get("date", "")

    if date_str:
        date = _parse_date(date_str)
    else:
        date = now

    events = await gcal_client.get_events_for_date(date)
    if not events and not date_str:
        events = await gcal_client.get_week_events()

    match = None
    for ev in events:
        if search_summary in ev["summary"].lower():
            match = ev
            break

    if not match:
        return f"\u26a0\ufe0f Nessun evento trovato con '{data.get('summary', '')}'"

    # Prepara kwargs
    kwargs: dict = {}
    if "summary" in changes:
        kwargs["summary"] = changes["summary"]
    if "start_time" in changes and "date" in changes:
        d = _parse_date(changes["date"])
        h, m = map(int, changes["start_time"].split(":"))
        kwargs["start"] = d.replace(hour=h, minute=m, second=0)
    elif "start_time" in changes:
        h, m = map(int, changes["start_time"].split(":"))
        kwargs["start"] = date.replace(hour=h, minute=m, second=0)
    if "end_time" in changes:
        h, m = map(int, changes["end_time"].split(":"))
        kwargs["end"] = date.replace(hour=h, minute=m, second=0)
    if "location" in changes:
        kwargs["location"] = changes["location"]

    result = await gcal_client.update_event(match["id"], **kwargs)
    return f"\u2705 Evento aggiornato: {result.get('summary', match['summary'])}"


async def _cal_free_slots(date: datetime, duration_minutes: int) -> str:
    """Mostra slot liberi."""
    slots = await gcal_client.find_free_slots(date, duration_minutes)
    date_label = _format_date_it(date)

    if not slots:
        return f"\u26a0\ufe0f Nessuno slot libero di {duration_minutes} min trovato per {date_label}"

    lines = [
        f"\U0001f4c5 Slot liberi — {date_label}",
        f"(durata minima: {duration_minutes} min)",
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501",
    ]
    for slot in slots:
        start = _format_time(slot["start"])
        end = _format_time(slot["end"])
        lines.append(f"  \u2705 {start} – {end}")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# EVENING PROGRAM (Digest Serale)
# ═══════════════════════════════════════════════════════════

async def _evening_program() -> str:
    """
    Genera il programma serale: impegni domani + outlook settimana.
    Tono discorsivo, come un assistente personale.
    """
    now = datetime.now(_TZ)
    tomorrow = now + timedelta(days=1)

    # Fetch eventi (graceful se non configurato)
    if gcal_client.is_configured():
        tomorrow_events = await gcal_client.get_tomorrow_events()
        week_events = await gcal_client.get_week_events()
    else:
        tomorrow_events = []
        week_events = []

    # Prepara dati per LLM
    tomorrow_label = _format_date_it(tomorrow)
    tomorrow_data = ""
    if tomorrow_events:
        tomorrow_data = "\n".join(
            f"- {_format_time(ev['start'])}–{_format_time(ev['end'])}: {ev['summary']}"
            + (f" ({ev['location']})" if ev["location"] else "")
            if not ev["all_day"]
            else f"- Tutto il giorno: {ev['summary']}"
            for ev in tomorrow_events
        )
    else:
        tomorrow_data = "Nessun impegno."

    # Settimana rimanente (escludi domani)
    tomorrow_date = tomorrow.date()
    rest_of_week = [
        ev for ev in week_events
        if ev["start"][:10] != str(tomorrow_date)
    ]
    week_data = ""
    if rest_of_week:
        week_data = "\n".join(
            f"- {ev['start'][:10]} {_format_time(ev['start'])}: {ev['summary']}"
            for ev in rest_of_week[:10]
        )

    # Pending tasks
    pending = [t for t in _tasks if t["status"] == "pending"]
    tasks_data = ""
    if pending:
        tasks_data = "\n".join(
            f"- {t['description']} (~{t['estimate_minutes']} min)"
            for t in pending[:5]
        )

    # LLM genera il programma discorsivo
    prompt = f"""Sei HERMES, l'assistente personale AI di Juan.
Genera il programma serale: racconta a Juan cosa lo aspetta domani e i prossimi giorni.

DOMANI ({tomorrow_label}):
{tomorrow_data}

RESTO SETTIMANA:
{week_data or "Nessun altro impegno."}

TASK PENDENTI:
{tasks_data or "Nessuna task aperta."}

REGOLE:
- Tono discorsivo, amichevole ma operativo (come un assistente personale parlante)
- Inizia con un saluto serale
- Descrivi il programma di domani in modo naturale (non una lista fredda)
- Se ci sono buchi nell'agenda, suggerisci quando fare le task pendenti
- Se ci sono impegni importanti nei prossimi giorni, ricordali come "heads up"
- Se domani e libero, dillo in modo positivo
- Chiudi con un messaggio motivante o pratico
- In italiano, max 800 caratteri
- NON usare emoji nel testo (li aggiungo io)"""

    response = await chat(
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": "Genera il programma serale per Juan."},
        ],
        complexity=TaskComplexity.MEDIUM,
        temperature=0.6,
        max_tokens=512,
    )

    return (
        f"\U0001f319 HERMES — Programma Serale\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        f"{response}"
    )


async def scheduled_evening_program():
    """Chiamato ogni sera alle 21:00 da APScheduler o via trigger HTTP."""
    from telegram import Bot as TgBot
    from bot.telegram_utils import _split_text, TG_MAX_LENGTH

    if not config.TELEGRAM_TASKS_TOKEN and not config.TELEGRAM_MASTER_TOKEN:
        logger.warning("TaskBot evening: nessun token bot configurato")
        return

    if not config.TELEGRAM_CHAT_ID:
        logger.warning("TaskBot evening: TELEGRAM_CHAT_ID non configurato")
        return

    token = config.TELEGRAM_TASKS_TOKEN or config.TELEGRAM_MASTER_TOKEN
    bot = TgBot(token=token)

    try:
        program = await _evening_program()
        for chunk in _split_text(program, TG_MAX_LENGTH):
            await bot.send_message(chat_id=config.TELEGRAM_CHAT_ID, text=chunk)
        logger.info("TaskBot: programma serale inviato")
    except Exception as e:
        logger.error(f"TaskBot evening program error: {e}")
        try:
            await bot.send_message(
                chat_id=config.TELEGRAM_CHAT_ID,
                text=f"\u26a0\ufe0f TaskBot — Errore programma serale:\n{str(e)[:300]}",
            )
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════
# TASK MANAGEMENT
# ═══════════════════════════════════════════════════════════

async def _add_task(description: str, client: str | None = None) -> str:
    """Aggiunge una task manualmente."""
    global _task_counter
    _task_counter += 1

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

    client_line = f"\U0001f465 Cliente: {client}" if client else ""

    return (
        f"\u2705 Task #{_task_counter} aggiunta\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"\U0001f4cb {description}\n"
        f"\u23f1\ufe0f Stima: ~{estimate} min\n"
        f"{client_line}"
    )


async def _complete_task(task_num: int) -> str:
    """Marca una task come completata."""
    for task in _tasks:
        if task["id"] == task_num and task["status"] == "pending":
            task["status"] = "done"
            task["completed_at"] = datetime.now(timezone.utc).isoformat()

            await memory.log_task_completion(
                task_description=task["description"],
                agent="TaskBot",
                outcome="Completata",
                client=task.get("client"),
            )

            return f"\u2705 Task #{task_num} completata: {task['description']}"

    return f"\u26a0\ufe0f Task #{task_num} non trovata o gia completata"


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
    """Genera il brief mattutino con task + calendario di oggi."""
    pending = [t for t in _tasks if t["status"] == "pending"]

    # Fetch eventi di oggi (graceful se non configurato)
    today_events = []
    if gcal_client.is_configured():
        try:
            today_events = await gcal_client.get_events_for_date(datetime.now(_TZ))
        except Exception as e:
            logger.warning(f"Brief: errore fetch calendario: {e}")

    lines = [
        "\u2600\ufe0f HERMES — Buongiorno Juan",
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501",
    ]

    # Calendario di oggi
    if today_events:
        lines.append("\n\U0001f4c5 AGENDA OGGI:")
        for ev in today_events:
            if ev["all_day"]:
                lines.append(f"  \U0001f30d {ev['summary']}")
            else:
                start = _format_time(ev["start"])
                end = _format_time(ev["end"])
                loc = f" \U0001f4cd {ev['location']}" if ev["location"] else ""
                lines.append(f"  \u23f0 {start}–{end}  {ev['summary']}{loc}")
    else:
        lines.append("\n\U0001f4c5 Nessun impegno in calendario oggi.")

    # Task
    if pending:
        quick_wins = [t for t in pending if t["estimate_minutes"] <= 15]
        main_tasks = [t for t in pending if 15 < t["estimate_minutes"] <= 120]
        heavy = [t for t in pending if t["estimate_minutes"] > 120]

        if quick_wins:
            lines.append("\n\u26a1 QUICK WINS:")
            for t in quick_wins:
                lines.append(f"  {t['id']}. {t['description']} (~{t['estimate_minutes']} min)")

        if main_tasks:
            lines.append("\n\U0001f4cb TASK:")
            for t in main_tasks:
                lines.append(f"  {t['id']}. {t['description']} (~{t['estimate_minutes']} min)")

        if heavy:
            lines.append("\n\U0001f534 IMPEGNATIVE:")
            for t in heavy:
                lines.append(f"  {t['id']}. {t['description']} (~{t['estimate_minutes']} min)")

        total = sum(t["estimate_minutes"] for t in pending)
        lines.append(f"\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501")
        lines.append(f"{len(today_events)} impegni + {len(pending)} task (~{total} min)")
    elif not today_events:
        lines.append("\n\u2705 Giornata libera! Nessun impegno e nessuna task.")

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
        return 30


async def _smart_handling(user_text: str, bot: Bot | None = None) -> str:
    """Usa LLM per interpretare richieste ambigue (task o calendario)."""
    analysis = await chat(
        messages=[
            {"role": "system", "content": (
                "Sei TaskBot di HERMES. Analizza la richiesta dell'utente.\n"
                "Rispondi in JSON:\n"
                '{"action": "add_task"|"calendar"|"info"|"unclear", '
                '"description": "...", '
                '"client": "nome cliente o null", '
                '"questions": ["domanda1", ...] se action=unclear}\n'
                "Se riguarda calendario/impegni/appuntamenti, usa action=calendar.\n"
                "Rispondi SOLO col JSON."
            )},
            {"role": "user", "content": user_text},
        ],
        complexity=TaskComplexity.LIGHT,
        temperature=0.2,
        max_tokens=256,
    )

    try:
        data = json.loads(analysis.strip())
    except json.JSONDecodeError:
        return await _add_task(user_text)

    action = data.get("action", "info")

    if action == "add_task":
        desc = data.get("description", user_text)
        client = data.get("client")
        return await _add_task(desc, client=client)

    elif action == "calendar":
        return await _handle_calendar(user_text)

    elif action == "unclear" and data.get("questions") and bot:
        answers = await ask_questions(
            agent_name="TaskBot",
            task_description=f"Gestione richiesta: {user_text}",
            questions=data["questions"][:3],
            bot=bot,
        )
        if answers:
            context_text = f"{user_text}\n\nChiarimenti:\n"
            context_text += "\n".join(f"- {q}: {a}" for q, a in answers.items())
            return await _add_task(context_text)
        else:
            return "\u23f3 In attesa dei tuoi chiarimenti..."

    else:
        response = await chat(
            messages=[
                {"role": "system", "content": (
                    "Sei TaskBot di HERMES. Rispondi alla richiesta dell'utente "
                    "relativa a task o calendario. Italiano, breve, operativo."
                )},
                {"role": "user", "content": user_text},
            ],
            complexity=TaskComplexity.LIGHT,
            temperature=0.3,
            max_tokens=512,
        )
        return response


# ─── Scheduled Brief (chiamato da APScheduler) ──────────

async def scheduled_morning_brief():
    """Chiamato ogni mattina alle 08:30 da APScheduler o via trigger HTTP."""
    from telegram import Bot as TgBot
    from bot.telegram_utils import _split_text, TG_MAX_LENGTH

    if not config.TELEGRAM_TASKS_TOKEN and not config.TELEGRAM_MASTER_TOKEN:
        logger.warning("TaskBot scheduled: nessun token bot configurato")
        return

    if not config.TELEGRAM_CHAT_ID:
        logger.warning("TaskBot scheduled: TELEGRAM_CHAT_ID non configurato")
        return

    token = config.TELEGRAM_TASKS_TOKEN or config.TELEGRAM_MASTER_TOKEN
    bot = TgBot(token=token)

    try:
        brief = await _morning_brief()
        for chunk in _split_text(brief, TG_MAX_LENGTH):
            await bot.send_message(chat_id=config.TELEGRAM_CHAT_ID, text=chunk)
        logger.info("TaskBot: brief mattutino inviato")
    except Exception as e:
        logger.error(f"TaskBot scheduled brief error: {e}")
        try:
            await bot.send_message(
                chat_id=config.TELEGRAM_CHAT_ID,
                text=f"\u26a0\ufe0f TaskBot — Errore brief schedulato:\n{str(e)[:300]}",
            )
        except Exception:
            pass


# ─── Task da fonti esterne (usato da MailMind, ecc.) ─────

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
