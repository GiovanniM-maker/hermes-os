"""
HERMES OS — MailMind Orchestrator
Gestione email autonoma via n8n webhooks + analisi LLM.

Sub-Agents: Reader → EntityResolver → Classifier → TaskExtractor → Drafter → Cleaner

Flusso:
1. Reader fetcha email non lette via n8n webhook
2. Classifier categorizza con LLM (urgente/task/da leggere/da rispondere/archivio)
3. EntityResolver cerca mittenti nella KB
4. TaskExtractor estrae task → le manda a TaskBot
5. Presenta digest interattivo a Juan
6. Juan conferma/risponde conversando
"""

import json
import logging
import re
from datetime import datetime, timezone

from telegram import Bot

import config
from core.llm_router import chat, TaskComplexity
from core.question_engine import ask_questions
from core import memory
from core import knowledge_base as kb
from agents.pipeline_forge.n8n_client import import_workflow, call_webhook

logger = logging.getLogger("hermes.mailmind")

# ─── Meta Keywords ────────────────────────────────────────
_META_KEYWORDS = (
    "cosa fai", "chi sei", "come funzioni", "help", "aiuto",
    "cosa puoi fare", "che sai fare", "presentati", "info",
    "cosa sai", "come ti uso", "istruzioni",
    "potresti", "puoi fare", "sei capace", "sai fare",
    "riesci a", "funzionalità", "capacità",
)

# ─── State ────────────────────────────────────────────────
# Ultimo digest in memoria per interazione conversazionale
_last_digest: list[dict] = []
_digest_timestamp: str = ""


# ─── Entry Point ──────────────────────────────────────────

async def handle_request(user_text: str, bot: Bot | None = None) -> str:
    """Entry point MailMind — gestisce comandi e conversazione."""
    text_lower = user_text.lower().strip()

    # ─── Pre-check: domande informative/meta ──────────────
    if _is_meta_query(text_lower):
        return await _handle_meta(user_text)

    # Setup n8n workflows
    if "setup" in text_lower or "configura" in text_lower:
        return await setup_n8n_workflows()

    # Azioni batch su digest (es: "ok 1,2,4-8", "elimina 1,3", "archivia tutto")
    if _last_digest and _looks_like_action(text_lower):
        return await _execute_actions(user_text, bot)

    # Rispondi a email specifica (es: "rispondi 2 con: grazie" o "rispondi 2")
    if re.match(r"rispondi\s+\d+", text_lower):
        return await _handle_reply(user_text, bot)

    # Genera bozza (es: "bozza 3")
    if re.match(r"bozz[ae]\s+\d+", text_lower):
        return await _handle_draft(user_text)

    # Chi è (es: "chi è Marco Rossi")
    if any(w in text_lower for w in ("chi è", "chi e'", "who is")):
        return await _handle_who_is(user_text)

    # Fetch email / digest (trigger manuale)
    if any(w in text_lower for w in ("digest", "email", "mail", "posta", "controlla")):
        return await run_email_analysis(bot)

    # Conversazione libera sulle email
    return await _conversational_mail(user_text)


# ─── Meta / Info Queries ──────────────────────────────────

def _is_meta_query(text_lower: str) -> bool:
    """Rileva domande informative/meta su MailMind."""
    if any(kw in text_lower for kw in _META_KEYWORDS):
        return True
    if len(text_lower) < 15 and "?" in text_lower:
        return True
    # Domande esplorative con "?" che non sono comandi email
    if "?" in text_lower and not any(v in text_lower for v in (
        "rispondi", "bozza", "archivia", "elimina", "digest",
        "controlla", "email", "mail", "posta",
    )):
        return True
    return False


async def _handle_meta(user_text: str) -> str:
    """Rispondi a domande informative su MailMind."""
    from core.identity import get_meta_system_prompt

    return await chat(
        messages=[
            {"role": "system", "content": get_meta_system_prompt("MailMind")},
            {"role": "user", "content": user_text},
        ],
        complexity=TaskComplexity.LIGHT,
        temperature=0.5,
        max_tokens=512,
    )


# ─── Core: Analisi Email Autonoma ─────────────────────────

async def run_email_analysis(bot: Bot | None = None) -> str:
    """
    Flusso completo di analisi email.
    Chiamato dal digest schedulato (09:00) o su richiesta.
    """
    global _last_digest, _digest_timestamp

    # ─── Step 1: Reader — fetch email da n8n ──────────
    try:
        raw_emails = await _fetch_emails()
    except Exception as e:
        logger.error(f"Reader: errore fetch email: {e}")
        return (
            "\U0001f4e7 MailMind \u2014 Errore Fetch\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            f"\u26a0\ufe0f Non riesco a leggere le email: {str(e)[:200]}\n\n"
            "Verifica che:\n"
            "1. I workflow n8n siano attivi\n"
            "2. Le credenziali Gmail siano collegate\n"
            "Scrivi 'configura mailmind' per ricreare i workflow."
        )

    if not raw_emails:
        return (
            "\U0001f4e7 MailMind \u2014 Inbox Pulita\n"
            "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            "\u2705 Nessuna email non letta. Tutto sotto controllo!"
        )

    # ─── Step 2: Classifier — categorizza con LLM ────
    classified = await _classify_emails(raw_emails)

    # ─── Step 3: EntityResolver — cerca mittenti KB ───
    classified = await _resolve_entities(classified)

    # ─── Step 4: TaskExtractor — estrai task ──────────
    tasks_extracted = await _extract_tasks(classified)

    # Salva digest in memoria per interazione successiva
    _last_digest = classified
    _digest_timestamp = datetime.now(timezone.utc).isoformat()

    # ─── Step 5: Formatta digest ──────────────────────
    return _format_digest(classified, tasks_extracted)


# ─── Sub-Agent: Reader ────────────────────────────────────

async def _fetch_emails() -> list[dict]:
    """Fetcha email non lette via n8n webhook."""
    result = await call_webhook("hermes-mail-fetch", {})

    # n8n ritorna lista di email o singolo oggetto
    if isinstance(result, dict):
        result = [result]

    emails = []
    for i, raw in enumerate(result):
        emails.append({
            "index": i + 1,
            "id": raw.get("id", raw.get("messageId", "")),
            "from": raw.get("from", raw.get("sender", "")),
            "subject": raw.get("subject", "(nessun oggetto)"),
            "snippet": raw.get("snippet", raw.get("textPlain", ""))[:300],
            "date": raw.get("date", raw.get("internalDate", "")),
            "labels": raw.get("labelIds", []),
        })

    logger.info(f"Reader: {len(emails)} email fetchate")
    return emails


# ─── Sub-Agent: Classifier ────────────────────────────────

async def _classify_emails(emails: list[dict]) -> list[dict]:
    """Classifica email con LLM: urgente/task/da_leggere/da_rispondere/archivio."""

    # Prepara sommario email per LLM
    email_summary = "\n".join(
        f"{e['index']}. Da: {e['from']} | Oggetto: {e['subject']} | Snippet: {e['snippet'][:100]}"
        for e in emails
    )

    system_prompt = """Sei il Classifier di MailMind (HERMES OS). Classifica ogni email.

Categorie:
- "urgente": richiede azione immediata (cliente, deadline, problema)
- "da_rispondere": serve una risposta ma non urgente
- "da_leggere": informativa, vale la pena leggere
- "task": contiene un'azione da fare (manda a TaskBot)
- "archivio": newsletter, notifiche, promo — da archiviare

Per ogni email dai anche:
- "azione_proposta": cosa faresti (es: "rispondo con conferma", "archivio", "creo task")
- "priorita": 1 (alta) a 5 (bassa)

Rispondi in JSON: [{"index": 1, "categoria": "...", "azione_proposta": "...", "priorita": N}, ...]"""

    response = await chat(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": email_summary},
        ],
        complexity=TaskComplexity.LIGHT,
        temperature=0.1,
        max_tokens=2048,
        json_mode=True,
    )

    try:
        classifications = json.loads(response)
    except json.JSONDecodeError:
        # Fallback: tutto come "da_leggere"
        classifications = [{"index": e["index"], "categoria": "da_leggere",
                           "azione_proposta": "da verificare", "priorita": 3} for e in emails]

    # Merge classificazione con dati email
    class_map = {c["index"]: c for c in classifications}
    for email in emails:
        c = class_map.get(email["index"], {})
        email["categoria"] = c.get("categoria", "da_leggere")
        email["azione_proposta"] = c.get("azione_proposta", "")
        email["priorita"] = c.get("priorita", 3)

    # Ordina per priorità
    emails.sort(key=lambda x: x["priorita"])

    logger.info(f"Classifier: {len(emails)} email classificate")
    return emails


# ─── Sub-Agent: EntityResolver ────────────────────────────

async def _resolve_entities(emails: list[dict]) -> list[dict]:
    """Cerca mittenti nella KB. Marca quelli sconosciuti."""
    for email in emails:
        sender = email.get("from", "")
        # Estrai nome dal formato "Nome <email@example.com>"
        name = sender.split("<")[0].strip().strip('"') if "<" in sender else sender.split("@")[0]

        if name:
            kb_info = await kb.search_entity(name)
            if kb_info:
                email["sender_info"] = kb_info
                email["sender_known"] = True
            else:
                email["sender_info"] = None
                email["sender_known"] = False

    unknown = [e for e in emails if not e.get("sender_known", True)]
    if unknown:
        logger.info(f"EntityResolver: {len(unknown)} mittenti sconosciuti")

    return emails


# ─── Sub-Agent: TaskExtractor ─────────────────────────────

async def _extract_tasks(emails: list[dict]) -> list[str]:
    """Estrae task dalle email categorizzate come 'task' e le manda a TaskBot."""
    from agents.task_bot.orchestrator import add_external_task

    task_emails = [e for e in emails if e.get("categoria") == "task"]
    if not task_emails:
        return []

    tasks_created = []
    for email in task_emails:
        # Usa LLM per estrarre la task concreta
        response = await chat(
            messages=[
                {"role": "system", "content": (
                    "Estrai la task concreta da questa email. "
                    "Rispondi con UNA frase che descrive l'azione da fare. "
                    "Includi il nome del mittente/cliente se rilevante."
                )},
                {"role": "user", "content": (
                    f"Da: {email['from']}\n"
                    f"Oggetto: {email['subject']}\n"
                    f"Contenuto: {email['snippet']}"
                )},
            ],
            complexity=TaskComplexity.LIGHT,
            temperature=0.1,
            max_tokens=128,
        )

        task_desc = response.strip()
        task_id = await add_external_task(
            description=task_desc,
            source="MailMind",
            priority="normal",
        )
        tasks_created.append(f"  #{task_id}: {task_desc}")
        logger.info(f"TaskExtractor: task #{task_id} creata da email #{email['index']}")

    return tasks_created


# ─── Digest Formatter ─────────────────────────────────────

def _format_digest(emails: list[dict], tasks_extracted: list[str]) -> str:
    """Formatta il digest interattivo."""
    lines = [
        f"\U0001f4e7 MailMind \u2014 {len(emails)} email non lette",
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501",
    ]

    # Raggruppa per categoria
    urgenti = [e for e in emails if e["categoria"] == "urgente"]
    da_rispondere = [e for e in emails if e["categoria"] == "da_rispondere"]
    da_leggere = [e for e in emails if e["categoria"] == "da_leggere"]
    task_mails = [e for e in emails if e["categoria"] == "task"]
    archivio = [e for e in emails if e["categoria"] == "archivio"]

    if urgenti:
        lines.append("\n\U0001f534 URGENTE")
        for e in urgenti:
            known = "\U0001f464" if e.get("sender_known") else "\u2753"
            lines.append(f"  {e['index']}. {known} {e['from'][:40]}")
            lines.append(f"     \u00ab{e['subject']}\u00bb")
            lines.append(f"     \u2192 {e['azione_proposta']}")

    if da_rispondere:
        lines.append("\n\U0001f7e1 DA RISPONDERE")
        for e in da_rispondere:
            known = "\U0001f464" if e.get("sender_known") else "\u2753"
            lines.append(f"  {e['index']}. {known} {e['from'][:40]}")
            lines.append(f"     \u00ab{e['subject']}\u00bb")
            lines.append(f"     \u2192 {e['azione_proposta']}")

    if da_leggere:
        lines.append("\n\U0001f535 DA LEGGERE")
        for e in da_leggere:
            lines.append(f"  {e['index']}. {e['from'][:40]} \u2014 \u00ab{e['subject']}\u00bb")

    if task_mails:
        lines.append("\n\U0001f4cb TASK ESTRATTE \u2192 TaskBot")
        for t in tasks_extracted:
            lines.append(t)

    if archivio:
        nums = ", ".join(str(e["index"]) for e in archivio)
        lines.append(f"\n\U0001f5d1\ufe0f ARCHIVIO ({len(archivio)} email): #{nums}")
        lines.append("  \u2192 Proposta: archivio tutto")

    # Mittenti sconosciuti
    unknown = [e for e in emails if not e.get("sender_known", True)
               and e["categoria"] in ("urgente", "da_rispondere")]
    if unknown:
        lines.append("\n\u2753 MITTENTI SCONOSCIUTI")
        for e in unknown:
            lines.append(f"  {e['index']}. {e['from'][:50]} \u2014 chi \u00e8?")

    lines.append("\n\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501")
    lines.append("Rispondi con:")
    lines.append("  'ok 1,4-8' \u2014 conferma azioni proposte")
    lines.append("  'archivia 1,3,7' \u2014 archivia")
    lines.append("  'rispondi 2 con: ...' \u2014 rispondi")
    lines.append("  'bozza 3' \u2014 genera bozza AI")
    lines.append("  oppure parlami delle email liberamente")

    return "\n".join(lines)


# ─── Azioni su Digest ─────────────────────────────────────

def _looks_like_action(text: str) -> bool:
    """Rileva se il messaggio è un'azione sul digest."""
    return bool(re.match(
        r"^(ok|archivia|elimina|cancella|conferma|si|sì)\s",
        text
    )) or text in ("archivia tutto", "ok", "si", "sì")


def _parse_numbers(text: str) -> list[int]:
    """Parsa numeri e range (es: '1,3,4-8' → [1,3,4,5,6,7,8])."""
    numbers = []
    # Rimuovi parole, tieni solo numeri e range
    clean = re.sub(r"[^0-9,\-]", " ", text)
    parts = re.findall(r"\d+(?:-\d+)?", clean)
    for part in parts:
        if "-" in part:
            start, end = part.split("-", 1)
            numbers.extend(range(int(start), int(end) + 1))
        else:
            numbers.append(int(part))
    return sorted(set(numbers))


async def _execute_actions(user_text: str, bot: Bot | None = None) -> str:
    """Esegue azioni batch sul digest corrente."""
    text_lower = user_text.lower().strip()
    numbers = _parse_numbers(user_text)

    if not numbers and "tutto" not in text_lower:
        return "\u26a0\ufe0f Non ho capito i numeri. Esempio: 'ok 1,3,5-8' o 'archivia tutto'"

    # "archivia tutto" → tutti gli archivio
    if "tutto" in text_lower:
        numbers = [e["index"] for e in _last_digest if e["categoria"] == "archivio"]

    # Trova email corrispondenti
    targets = [e for e in _last_digest if e["index"] in numbers]
    if not targets:
        return "\u26a0\ufe0f Nessuna email trovata con quei numeri."

    # Determina azione
    if any(w in text_lower for w in ("elimina", "cancella")):
        action = "elimina"
    elif any(w in text_lower for w in ("archivia", "tutto")):
        action = "archivia"
    else:
        # "ok" = conferma azioni proposte (archivia gli archivio, ecc.)
        action = "conferma"

    results = []
    for email in targets:
        if action == "conferma":
            # Esegui l'azione proposta
            if email["categoria"] == "archivio":
                await _archive_email(email["id"])
                results.append(f"  \u2705 #{email['index']} archiviata")
            else:
                results.append(f"  \u2139\ufe0f #{email['index']} \u2014 azione proposta confermata")
        elif action == "archivia":
            await _archive_email(email["id"])
            results.append(f"  \u2705 #{email['index']} archiviata")
        elif action == "elimina":
            await _archive_email(email["id"])  # Per sicurezza: archivia, non elimina
            results.append(f"  \u2705 #{email['index']} rimossa")

    return (
        f"\U0001f4e7 MailMind \u2014 Azioni eseguite\n"
        "\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        + "\n".join(results)
    )


async def _archive_email(message_id: str):
    """Archivia email via n8n webhook."""
    try:
        await call_webhook("hermes-mail-archive", {"message_id": message_id})
    except Exception as e:
        logger.error(f"Errore archiviazione email {message_id}: {e}")


# ─── Sub-Agent: Drafter ───────────────────────────────────

async def _handle_reply(user_text: str, bot: Bot | None = None) -> str:
    """Rispondi a email: 'rispondi 2 con: testo' oppure 'rispondi 2' (chiede cosa dire)."""
    # Con testo esplicito
    match_full = re.match(r"rispondi\s+(\d+)\s+con[:\s]+(.+)", user_text, re.IGNORECASE | re.DOTALL)
    # Solo numero (senza testo → chiedi)
    match_num = re.match(r"rispondi\s+(\d+)\s*$", user_text, re.IGNORECASE)

    if match_full:
        num = int(match_full.group(1))
        reply_text = match_full.group(2).strip()
    elif match_num:
        num = int(match_num.group(1))
        email = next((e for e in _last_digest if e["index"] == num), None)
        if not email:
            return f"\u26a0\ufe0f Email #{num} non trovata nel digest corrente."

        # Chiedi cosa rispondere
        if bot:
            answers = await ask_questions(
                agent_name="MailMind",
                task_description=f"Rispondere a: {email['from']} — «{email['subject']}»",
                questions=["Cosa vuoi che risponda? (oppure scrivo io una bozza AI — rispondi 'bozza')"],
                bot=bot,
            )
            if answers:
                answer = answers.get(1, "")
                if "bozza" in answer.lower():
                    return await _handle_draft(f"bozza {num}")
                reply_text = answer
            else:
                return await _handle_draft(f"bozza {num}")
        else:
            return f"\u270f\ufe0f Per rispondere: 'rispondi {num} con: il tuo messaggio'\nOppure: 'bozza {num}' per generare una bozza AI"
    else:
        return "\u26a0\ufe0f Formato: 'rispondi 2 con: il tuo messaggio' oppure 'rispondi 2'"

    email = next((e for e in _last_digest if e["index"] == num), None)
    if not email:
        return f"\u26a0\ufe0f Email #{num} non trovata nel digest corrente."

    # Invia via n8n
    try:
        sender_email = email["from"]
        email_match = re.search(r"<(.+?)>", sender_email)
        to_addr = email_match.group(1) if email_match else sender_email

        await call_webhook("hermes-mail-send", {
            "to": to_addr,
            "subject": f"Re: {email['subject']}",
            "body": reply_text,
        })
        return f"\u2705 Risposta inviata a {to_addr}\nOggetto: Re: {email['subject']}"
    except Exception as e:
        return f"\u26a0\ufe0f Errore invio risposta: {str(e)[:200]}"


async def _handle_draft(user_text: str, bot: Bot | None = None) -> str:
    """Genera bozza risposta AI: 'bozza 3' o 'bozza 3 formale/informale/...'."""
    match = re.match(r"bozz[ae]\s+(\d+)\s*(.*)", user_text, re.IGNORECASE)
    if not match:
        return "\u26a0\ufe0f Formato: 'bozza 3' oppure 'bozza 3 formale'"

    num = int(match.group(1))
    tone_hint = match.group(2).strip() if match.group(2) else ""

    email = next((e for e in _last_digest if e["index"] == num), None)
    if not email:
        return f"\u26a0\ufe0f Email #{num} non trovata nel digest corrente."

    # Cerca contesto mittente nella KB
    sender_context = email.get("sender_info", "")

    tone_instruction = ""
    if tone_hint:
        tone_instruction = f"\nTono richiesto: {tone_hint}."

    response = await chat(
        messages=[
            {"role": "system", "content": (
                "Sei MailMind di HERMES. Genera una bozza di risposta email professionale "
                "ma diretta, in italiano. Stile: breve, cordiale, operativo. "
                "Non essere troppo formale. Juan \u00e8 un consulente AI/media buyer."
                f"{tone_instruction}"
                f"\n\nInfo mittente dalla KB: {sender_context or 'nessuna info disponibile'}"
            )},
            {"role": "user", "content": (
                f"Da: {email['from']}\n"
                f"Oggetto: {email['subject']}\n"
                f"Contenuto: {email['snippet']}\n\n"
                "Genera una bozza di risposta."
            )},
        ],
        complexity=TaskComplexity.MEDIUM,
        temperature=0.4,
        max_tokens=512,
    )

    return (
        f"\u270f\ufe0f Bozza risposta a #{num}\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"A: {email['from']}\n"
        f"Oggetto: Re: {email['subject']}\n\n"
        f"{response}\n\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"Per inviare: 'rispondi {num} con: [testo]'\n"
        f"O modifica e incolla."
    )


# ─── Chi \u00e8 ──────────────────────────────────────────────

async def _handle_who_is(user_text: str) -> str:
    """Cerca info su mittente nella KB."""
    name = user_text.lower()
    for prefix in ("chi \u00e8", "chi e'", "who is"):
        name = name.replace(prefix, "")
    name = name.strip()

    result = await kb.search_entity(name)
    if result:
        return f"\U0001f464 {name}:\n{result}"
    return f"\U0001f464 {name}: non trovato nella Knowledge Base. Dimmi chi \u00e8 e lo salvo!"


# ─── Conversazione Libera ─────────────────────────────────

async def _conversational_mail(user_text: str) -> str:
    """Gestione conversazionale delle email — parla liberamente."""
    # Includi contesto del digest se presente
    digest_context = ""
    if _last_digest:
        digest_context = "Ultimo digest email:\n" + "\n".join(
            f"  {e['index']}. {e['from'][:30]} | {e['subject'][:50]} | {e['categoria']}"
            for e in _last_digest[:10]
        )

    response = await chat(
        messages=[
            {"role": "system", "content": (
                "Sei MailMind di HERMES OS. L'utente sta parlando delle sue email. "
                "Puoi rispondere a domande, suggerire azioni, generare risposte. "
                "Hai accesso al digest delle email non lette. "
                "Rispondi in italiano, breve e operativo.\n\n"
                f"{digest_context}"
            )},
            {"role": "user", "content": user_text},
        ],
        complexity=TaskComplexity.MEDIUM,
        temperature=0.4,
        max_tokens=1024,
    )
    return response


# ─── Setup n8n Workflows ──────────────────────────────────

async def setup_n8n_workflows() -> str:
    """Crea i workflow n8n necessari per MailMind."""
    workflows_created = []

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
        "3. Testa con: 'controlla email'"
    )


# ─── Scheduled Digest (chiamato da APScheduler) ──────────

async def scheduled_morning_digest():
    """Chiamato ogni mattina alle 09:00 da APScheduler."""
    from telegram import Bot as TgBot
    from bot.telegram_utils import _split_text, TG_MAX_LENGTH

    if not config.TELEGRAM_MAIL_TOKEN and not config.TELEGRAM_MASTER_TOKEN:
        logger.warning("MailMind scheduled: nessun token bot configurato")
        return

    # Usa il mail bot se disponibile, altrimenti master
    token = config.TELEGRAM_MAIL_TOKEN or config.TELEGRAM_MASTER_TOKEN
    bot = TgBot(token=token)

    try:
        digest = await run_email_analysis(bot)
        # Split per rispettare il limite Telegram 4096 chars
        for chunk in _split_text(digest, TG_MAX_LENGTH):
            await bot.send_message(chat_id=config.TELEGRAM_CHAT_ID, text=chunk)
        logger.info("MailMind: digest mattutino inviato")
    except Exception as e:
        logger.error(f"MailMind scheduled digest error: {e}")
