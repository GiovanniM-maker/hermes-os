"""
HERMES OS — CodeForge Orchestrator
Genera codice, landing page, script e componenti.

Sub-Agents: Analyst → Coder → Reviewer → Deployer
Supporta: Python, JS/TS, HTML/CSS, React, shell scripts.
"""

import json
import logging

from telegram import Bot

import config
from core.llm_router import chat, TaskComplexity
from core.question_engine import ask_questions
from core import memory

logger = logging.getLogger("hermes.code_forge")


_META_KEYWORDS = (
    "cosa fai", "chi sei", "come funzioni", "help", "aiuto",
    "cosa puoi fare", "che sai fare", "presentati", "info",
    "cosa sai", "come ti uso", "istruzioni",
)


async def handle_request(user_text: str, bot: Bot | None = None) -> str:
    """Entry point CodeForge."""
    logger.info(f"CodeForge: nuova richiesta — {user_text[:100]}")

    # ─── Pre-check: domande informative/meta ──────────────
    text_lower = user_text.lower().strip()
    if any(kw in text_lower for kw in _META_KEYWORDS) or (len(text_lower) < 15 and "?" in text_lower):
        return await _handle_meta(user_text)

    # ─── Step 1: Analyst — capisce cosa serve ─────────
    analysis = await _analyze(user_text, bot)
    if analysis.get("needs_input"):
        return analysis["message"]

    spec = analysis.get("spec", user_text)
    lang = analysis.get("language", "python")
    task_type = analysis.get("type", "script")

    # ─── Step 2: Coder — genera il codice ─────────────
    code_result = await _generate_code(spec, lang, task_type)

    if not code_result:
        return "\u26a0\ufe0f CodeForge: non sono riuscito a generare il codice."

    # ─── Step 3: Reviewer — review qualità ────────────
    review = await _review(code_result, spec, lang)

    # ─── Step 4: Se ci sono problemi, correggi ────────
    if review.get("issues"):
        code_result = await _fix(code_result, review["issues"], spec, lang)

    # ─── Formatta output ──────────────────────────────
    filename = code_result.get("filename", f"output.{_ext(lang)}")
    code = code_result.get("code", "")
    explanation = code_result.get("explanation", "")

    await memory.log_task_completion(
        task_description=f"CodeForge: {filename}",
        agent="CodeForge",
        outcome=f"Generato {lang} — {len(code)} chars",
    )

    # Tronca se troppo lungo per Telegram (max ~4096 chars)
    if len(code) > 3500:
        code_display = code[:3500] + "\n\n# ... (troncato, file completo disponibile)"
    else:
        code_display = code

    return (
        f"\U0001f4bb CodeForge \u2014 Codice Generato\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"\U0001f4c4 File: {filename}\n"
        f"\U0001f3f7\ufe0f Linguaggio: {lang}\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n\n"
        f"```{lang}\n{code_display}\n```\n\n"
        f"{explanation}"
    )


# ─── Meta / Info Queries ──────────────────────────────────

async def _handle_meta(user_text: str) -> str:
    """Rispondi a domande informative su CodeForge."""
    return await chat(
        messages=[
            {"role": "system", "content": (
                "Sei CodeForge, il bot di HERMES OS che genera codice. "
                "L'utente ti sta facendo una domanda informativa (non una richiesta di codice). "
                "Rispondi in italiano, breve e chiaro. Spiega cosa fai e come usarti.\n\n"
                "Le tue capacita':\n"
                "- Genero codice in Python, JavaScript/TypeScript, HTML/CSS, React, shell scripts\n"
                "- Creo: script, landing page, componenti React, API, bot, automazioni\n"
                "- Il flusso: analizzo la richiesta -> genero il codice -> review qualita' -> "
                "correggo eventuali problemi -> consegno\n"
                "- Se mi mancano info, chiedo chiarimenti prima di procedere\n\n"
                "Esempio d'uso: 'Scrivi uno script Python che scrape i prezzi da Amazon' "
                "oppure 'Crea una landing page per un corso di AI'"
            )},
            {"role": "user", "content": user_text},
        ],
        complexity=TaskComplexity.LIGHT,
        temperature=0.5,
        max_tokens=512,
    )


# ─── Sub-Agents ──────────────────────────────────────────

async def _analyze(user_text: str, bot: Bot | None = None) -> dict:
    """Analyst: capisce il tipo di task, linguaggio, e specifiche."""
    system_prompt = """Sei l'Analyst di CodeForge (HERMES OS). Analizza la richiesta di codice.

Determina:
1. Tipo: script, landing_page, component, api, automation, full_project
2. Linguaggio: python, javascript, typescript, html, css, react, shell, sql
3. Se hai TUTTE le info necessarie

Rispondi in JSON:
Se hai tutto: {"needs_input": false, "spec": "specifica dettagliata", "language": "python", "type": "script"}
Se mancano info: {"needs_input": true, "questions": ["domanda 1", "domanda 2"]}

Max 3 domande, solo quelle STRETTAMENTE necessarie.
Se la richiesta è chiara, NON chiedere nulla — procedi."""

    response = await chat(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        complexity=TaskComplexity.MEDIUM,
        temperature=0.2,
        max_tokens=1024,
        json_mode=True,
    )

    try:
        result = json.loads(response)
    except json.JSONDecodeError:
        return {"needs_input": False, "spec": user_text, "language": "python", "type": "script"}

    if result.get("needs_input") and result.get("questions"):
        questions = result["questions"]

        if bot:
            answers = await ask_questions(
                agent_name="CodeForge",
                task_description=f"Generare codice: {user_text[:80]}",
                questions=questions,
                bot=bot,
            )
            if answers:
                answers_text = "\n".join(f"- {q}: {answers.get(i+1, 'N/A')}"
                                         for i, q in enumerate(questions))
                full_spec = f"{user_text}\n\nChiarimenti:\n{answers_text}"
                result["needs_input"] = False
                result["spec"] = full_spec
                return result

        q_text = "\n".join(f"  {i+1}. {q}" for i, q in enumerate(questions))
        return {
            "needs_input": True,
            "message": (
                f"\U0001f4bb CodeForge \u2014 Chiarimenti necessari\n"
                f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
                f"Per generare il codice ho bisogno di:\n\n"
                f"{q_text}\n\n"
                f"Rispondi e procedo."
            ),
        }

    return result


async def _generate_code(spec: str, lang: str, task_type: str) -> dict | None:
    """Coder: genera il codice."""
    type_instructions = {
        "landing_page": (
            "Genera una landing page HTML completa con CSS inline moderno. "
            "Design responsive, mobile-first. Includi sezioni hero, features, CTA. "
            "Usa colori professionali e tipografia pulita."
        ),
        "script": "Genera uno script pulito, commentato, con error handling.",
        "component": "Genera un componente riusabile con props/parametri documentati.",
        "api": "Genera endpoint API con validazione input, error handling, e documentazione.",
        "automation": "Genera script di automazione robusto con logging e retry logic.",
        "full_project": (
            "Genera la struttura completa del progetto con tutti i file necessari. "
            "Separa i file con commenti '# === FILE: path/nome.ext ==='."
        ),
    }

    extra = type_instructions.get(task_type, type_instructions["script"])

    system_prompt = f"""Sei il Coder di CodeForge (HERMES OS). Genera codice {lang} di alta qualità.

REGOLE:
- Codice production-ready, non demo
- Commenti solo dove necessario (no over-commenting)
- Nomi variabili/funzioni chiari e descrittivi
- Error handling appropriato
- {extra}

Rispondi in JSON:
{{
    "filename": "nome_file.ext",
    "code": "il codice completo",
    "explanation": "breve spiegazione (2-3 frasi) di come usare/deployare"
}}"""

    response = await chat(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Specifica:\n{spec}"},
        ],
        complexity=TaskComplexity.HEAVY,
        temperature=0.2,
        max_tokens=8192,
        json_mode=True,
    )

    try:
        return json.loads(response)
    except json.JSONDecodeError:
        # Fallback: prova a estrarre JSON
        if "```json" in response:
            try:
                json_str = response.split("```json")[1].split("```")[0].strip()
                return json.loads(json_str)
            except (json.JSONDecodeError, IndexError):
                pass
        # Ultimo fallback: il codice raw
        return {
            "filename": f"output.{_ext(lang)}",
            "code": response,
            "explanation": "",
        }


async def _review(code_result: dict, spec: str, lang: str) -> dict:
    """Reviewer: controlla qualità, sicurezza, correttezza."""
    code = code_result.get("code", "")

    system_prompt = """Sei il Reviewer di CodeForge. Controlla il codice per:
1. Bug o errori logici
2. Vulnerabilità di sicurezza (injection, XSS, etc.)
3. Mancanze rispetto alla specifica
4. Best practice mancate

Rispondi in JSON:
{"issues": ["issue 1", "issue 2"], "score": 8, "notes": "commento generale"}

Se il codice è buono: {"issues": [], "score": 9, "notes": "ok"}"""

    response = await chat(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": (
                f"Linguaggio: {lang}\n"
                f"Specifica: {spec[:1000]}\n\n"
                f"Codice:\n```\n{code[:4000]}\n```"
            )},
        ],
        complexity=TaskComplexity.MEDIUM,
        temperature=0.1,
        max_tokens=1024,
        json_mode=True,
    )

    try:
        return json.loads(response)
    except json.JSONDecodeError:
        return {"issues": [], "score": 7, "notes": "Review non parsabile"}


async def _fix(code_result: dict, issues: list, spec: str, lang: str) -> dict:
    """Fixer: corregge i problemi trovati dal Reviewer."""
    issues_text = "\n".join(f"- {issue}" for issue in issues)

    system_prompt = f"""Sei il Fixer di CodeForge. Correggi i problemi trovati nel codice {lang}.

Problemi da risolvere:
{issues_text}

Rispondi in JSON:
{{"filename": "nome_file.ext", "code": "codice corretto completo", "explanation": "cosa è stato corretto"}}"""

    response = await chat(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": (
                f"Specifica: {spec[:1000]}\n\n"
                f"Codice attuale:\n```\n{code_result.get('code', '')[:4000]}\n```"
            )},
        ],
        complexity=TaskComplexity.HEAVY,
        temperature=0.1,
        max_tokens=8192,
        json_mode=True,
    )

    try:
        fixed = json.loads(response)
        fixed.setdefault("filename", code_result.get("filename", f"output.{_ext(lang)}"))
        return fixed
    except json.JSONDecodeError:
        return code_result  # Se fallisce il fix, ritorna l'originale


def _ext(lang: str) -> str:
    """Estensione file per linguaggio."""
    return {
        "python": "py",
        "javascript": "js",
        "typescript": "ts",
        "html": "html",
        "css": "css",
        "react": "tsx",
        "shell": "sh",
        "sql": "sql",
    }.get(lang, "txt")
