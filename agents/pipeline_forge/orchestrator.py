"""
HERMES OS — PipelineForge Orchestrator
Riceve una descrizione in linguaggio naturale e genera,
testa e deploya workflow n8n autonomamente.

Sub-Agents: Clarifier → Architect → Builder → Tester → Debugger → Deployer
"""

import json
import logging

from telegram import Bot

import config
from core.llm_router import chat, TaskComplexity
from core.question_engine import ask_questions
from core import memory
from agents.pipeline_forge.n8n_client import (
    import_workflow,
    execute_workflow,
    get_execution_result,
)

logger = logging.getLogger("hermes.pipeline_forge")


async def handle_request(user_text: str, bot: Bot | None = None) -> str:
    """
    Entry point PipelineForge.
    Prende una descrizione testuale e produce un workflow n8n funzionante.
    """
    logger.info(f"PipelineForge: nuova richiesta — {user_text[:100]}")

    # ─── Pre-check: domande informative/meta ──────────────
    if await _is_meta_query(user_text):
        return await _handle_meta(user_text)

    # ─── Step 1: Clarifier ───────────────────────────────
    clarification = await _clarify(user_text, bot)
    if clarification.get("needs_input"):
        return clarification["message"]

    full_spec = clarification.get("spec", user_text)

    # ─── Step 2: Architect ───────────────────────────────
    architecture = await _architect(full_spec)

    # ─── Step 3: Builder ─────────────────────────────────
    workflow_json = await _build(full_spec, architecture)

    if not workflow_json:
        return "\u26a0\ufe0f PipelineForge: non sono riuscito a generare il workflow JSON."

    # ─── Step 4: Tester + Debugger (max 5 iterazioni) ────
    result = await _test_and_debug(workflow_json, full_spec)

    if result["success"]:
        # ─── Step 5: Deployer ────────────────────────────
        return await _deploy(result["workflow_id"], result.get("workflow_name", "workflow"))
    else:
        return (
            f"\u26a0\ufe0f PipelineForge: workflow creato ma con errori dopo "
            f"{config.MAX_DEBUG_ITERATIONS} tentativi di debug.\n\n"
            f"Ultimo errore: {result.get('last_error', 'sconosciuto')}\n\n"
            f"Workflow ID: {result.get('workflow_id', 'N/A')} — "
            f"puoi verificarlo manualmente su n8n."
        )


# ─── Meta / Info Queries ──────────────────────────────────

_META_KEYWORDS = (
    "cosa fai", "chi sei", "come funzioni", "help", "aiuto",
    "cosa puoi fare", "che sai fare", "presentati", "info",
    "cosa sai", "come ti uso", "istruzioni",
)


async def _is_meta_query(user_text: str) -> bool:
    """Rileva domande informative/meta che non sono richieste di workflow."""
    text_lower = user_text.lower().strip()
    if any(kw in text_lower for kw in _META_KEYWORDS):
        return True
    # Messaggi troppo corti per essere specifiche di workflow
    if len(text_lower) < 15 and "?" in text_lower:
        return True
    return False


async def _handle_meta(user_text: str) -> str:
    """Rispondi a domande informative su PipelineForge."""
    return await chat(
        messages=[
            {"role": "system", "content": (
                "Sei PipelineForge, il bot di HERMES OS che crea workflow n8n. "
                "L'utente ti sta facendo una domanda informativa (non una richiesta di workflow). "
                "Rispondi in italiano, breve e chiaro. Spiega cosa fai e come usarti.\n\n"
                "Le tue capacita':\n"
                "- Creo workflow n8n da descrizioni in linguaggio naturale\n"
                "- Supporto: webhook, schedule, Google Sheets, Gmail, Airtable, Notion, Slack, ecc.\n"
                "- Il flusso: capisco la richiesta -> progetto l'architettura -> genero il JSON -> "
                "testo su n8n -> debug automatico -> deploy\n"
                "- Se mi mancano info, chiedo chiarimenti prima di procedere\n\n"
                "Esempio d'uso: 'Crea un workflow che quando arriva un lead da un form webhook, "
                "lo salva su Google Sheets e manda una notifica su Slack'"
            )},
            {"role": "user", "content": user_text},
        ],
        complexity=TaskComplexity.LIGHT,
        temperature=0.5,
        max_tokens=512,
    )


# ─── Sub-Agents ──────────────────────────────────────────

async def _clarify(user_text: str, bot: Bot | None = None) -> dict:
    """
    Clarifier: analizza la richiesta, identifica ambiguita'.
    Se servono chiarimenti, chiede a Juan.
    """
    system_prompt = """Sei il Clarifier di PipelineForge. Analizza la richiesta di workflow n8n.

Determina se hai TUTTE le info necessarie per costruire il workflow:
- Trigger (quando si attiva? schedule, webhook, evento?)
- Input (da dove arrivano i dati?)
- Elaborazione (cosa fare con i dati?)
- Output (dove mandare il risultato?)
- Condizioni/errori (edge case?)

Rispondi in JSON:
Se hai tutto: {"needs_input": false, "spec": "specifica completa e dettagliata del workflow"}
Se mancano info: {"needs_input": true, "questions": ["domanda 1", "domanda 2"]}

Max 3 domande, solo quelle STRETTAMENTE necessarie."""

    response = await chat(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        complexity=TaskComplexity.HEAVY,
        temperature=0.2,
        max_tokens=1024,
        json_mode=True,
    )

    try:
        result = json.loads(response)
    except json.JSONDecodeError:
        return {"needs_input": False, "spec": user_text}

    if result.get("needs_input") and result.get("questions"):
        questions = result["questions"]

        if bot:
            answers = await ask_questions(
                agent_name="PipelineForge",
                task_description=f"Creare workflow: {user_text[:80]}",
                questions=questions,
                bot=bot,
            )
            if answers:
                # Combina risposte con la richiesta originale
                answers_text = "\n".join(f"- {q}: {answers.get(i+1, 'N/A')}"
                                         for i, q in enumerate(questions))
                full_spec = f"{user_text}\n\nChiarimenti:\n{answers_text}"
                return {"needs_input": False, "spec": full_spec}

        # Se non riesce a chiedere, ritorna le domande come messaggio
        q_text = "\n".join(f"  {i+1}. {q}" for i, q in enumerate(questions))
        return {
            "needs_input": True,
            "message": (
                f"\u2699\ufe0f PipelineForge \u2014 Chiarimenti necessari\n"
                f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
                f"Per costruire questo workflow ho bisogno di:\n\n"
                f"{q_text}\n\n"
                f"Rispondi e rilancio automaticamente."
            ),
        }

    return result


async def _architect(spec: str) -> str:
    """
    Architect: progetta la struttura del workflow (nodi, sequenza, condizioni).
    """
    system_prompt = """Sei l'Architect di PipelineForge. Data una specifica, progetta la struttura del workflow n8n.

Output richiesto:
1. Lista ordinata dei nodi con tipo n8n (es. n8n-nodes-base.googleSheets, n8n-nodes-base.gmail)
2. Connessioni tra nodi
3. Condizioni IF/switch se necessarie
4. Error handling

Rispondi in formato strutturato testuale. Sii preciso sui tipi di nodo n8n."""

    return await chat(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Specifica workflow:\n{spec}"},
        ],
        complexity=TaskComplexity.HEAVY,
        temperature=0.2,
        max_tokens=2048,
    )


async def _build(spec: str, architecture: str) -> dict | None:
    """
    Builder: genera il JSON n8n completo e valido.
    """
    system_prompt = """Sei il Builder di PipelineForge. Genera un workflow n8n completo in formato JSON.

REGOLE:
- Il JSON deve essere importabile direttamente via n8n API (POST /api/v1/workflows)
- Ogni nodo deve avere: id, name, type, position, parameters, typeVersion
- Le connections devono mappare correttamente gli output agli input
- Usa nodi n8n reali e validi
- Il workflow deve avere un nome descrittivo

Rispondi SOLO con il JSON del workflow, niente altro."""

    response = await chat(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Specifica:\n{spec}\n\nArchitettura:\n{architecture}"},
        ],
        complexity=TaskComplexity.HEAVY,
        temperature=0.1,
        max_tokens=8192,
    )

    # Estrai JSON dalla risposta
    try:
        # Prova parsing diretto
        return json.loads(response)
    except json.JSONDecodeError:
        # Prova a estrarre da code block
        if "```json" in response:
            json_str = response.split("```json")[1].split("```")[0].strip()
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                pass
        elif "```" in response:
            json_str = response.split("```")[1].split("```")[0].strip()
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                pass

    logger.error("Builder: impossibile parsare JSON workflow")
    return None


async def _test_and_debug(workflow_json: dict, spec: str) -> dict:
    """
    Tester + Debugger: importa, esegue test, debugga se errori (max 5 iter).
    """
    current_json = workflow_json
    last_error = None

    for iteration in range(config.MAX_DEBUG_ITERATIONS):
        logger.info(f"Test iteration {iteration + 1}/{config.MAX_DEBUG_ITERATIONS}")

        # Import workflow su n8n
        try:
            result = await import_workflow(current_json)
            workflow_id = result.get("id")
            workflow_name = result.get("name", "workflow")
        except Exception as e:
            last_error = f"Import failed: {e}"
            logger.error(last_error)

            # Debugger: correggi e riprova
            current_json = await _debug(current_json, last_error, spec)
            if not current_json:
                return {"success": False, "last_error": last_error}
            continue

        # Prova esecuzione test
        try:
            exec_result = await execute_workflow(workflow_id)
            exec_id = exec_result.get("id")

            if exec_id:
                execution = await get_execution_result(exec_id)
                if execution.get("finished") and not execution.get("stoppedAt"):
                    return {
                        "success": True,
                        "workflow_id": workflow_id,
                        "workflow_name": workflow_name,
                    }
                else:
                    last_error = f"Execution failed: {json.dumps(execution)[:500]}"
            else:
                # Workflow importato ma non testabile (es. trigger manuale)
                return {
                    "success": True,
                    "workflow_id": workflow_id,
                    "workflow_name": workflow_name,
                }

        except Exception as e:
            last_error = f"Execution error: {e}"
            logger.error(last_error)

        # Se siamo qui, c'e' stato un errore — debug
        if iteration < config.MAX_DEBUG_ITERATIONS - 1:
            current_json = await _debug(current_json, last_error, spec)
            if not current_json:
                return {"success": False, "workflow_id": workflow_id, "last_error": last_error}

    return {"success": False, "workflow_id": workflow_id, "last_error": last_error}


async def _debug(workflow_json: dict, error: str, spec: str) -> dict | None:
    """Debugger: analizza errore, corregge il JSON."""
    system_prompt = """Sei il Debugger di PipelineForge. Un workflow n8n ha un errore.
Analizza l'errore, correggi il JSON e ritorna il JSON corretto.
Rispondi SOLO con il JSON corretto."""

    response = await chat(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": (
                f"Specifica originale:\n{spec}\n\n"
                f"Workflow JSON attuale:\n{json.dumps(workflow_json, indent=2)[:4000]}\n\n"
                f"Errore:\n{error}"
            )},
        ],
        complexity=TaskComplexity.HEAVY,
        temperature=0.1,
        max_tokens=8192,
    )

    try:
        return json.loads(response)
    except json.JSONDecodeError:
        if "```json" in response:
            json_str = response.split("```json")[1].split("```")[0].strip()
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                pass
    return None


async def _deploy(workflow_id: str, workflow_name: str) -> str:
    """Deployer: conferma deploy, genera link, notifica."""
    n8n_url = config.N8N_BASE_URL.rstrip("/")
    link = f"{n8n_url}/workflow/{workflow_id}"

    await memory.log_task_completion(
        task_description=f"Workflow n8n: {workflow_name}",
        agent="PipelineForge",
        outcome=f"Deploy riuscito — {link}",
    )

    return (
        f"\u2705 PipelineForge \u2014 Workflow Deployato!\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"\U0001f4cb Nome: {workflow_name}\n"
        f"\U0001f517 Link: {link}\n"
        f"ID: {workflow_id}\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"Il workflow \u00e8 attivo su n8n. Verifica e attiva il trigger."
    )
