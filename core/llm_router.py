"""
HERMES OS — LLM Router
Routing intelligente tra modelli via OpenRouter.
Usa il modello piu' economico che risolve il problema.
"""

import logging
from enum import Enum

from openai import AsyncOpenAI

import config

logger = logging.getLogger("hermes.llm")


class TaskComplexity(str, Enum):
    """Livelli di complessita' task per routing LLM."""
    LIGHT = "light"      # Classificazione, routing, risposte brevi
    MEDIUM = "medium"    # Analisi dati, report, riassunti complessi
    HEAVY = "heavy"      # Codice, ragionamento multi-step, workflow


# Mapping complessita' → modello
COMPLEXITY_MODEL_MAP = {
    TaskComplexity.LIGHT: config.LLM_MODEL_LIGHT,    # Gemini Flash
    TaskComplexity.MEDIUM: config.LLM_MODEL_MEDIUM,   # Gemini Pro
    TaskComplexity.HEAVY: config.LLM_MODEL_HEAVY,     # Claude Sonnet
}

# Client OpenRouter (OpenAI-compatible)
_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    """Lazy init del client OpenRouter."""
    global _client
    if _client is None:
        if not config.OPENROUTER_API_KEY:
            raise RuntimeError("OPENROUTER_API_KEY non configurata")
        _client = AsyncOpenAI(
            api_key=config.OPENROUTER_API_KEY,
            base_url=config.OPENROUTER_BASE_URL,
            default_headers={
                "HTTP-Referer": "https://hermes-os.onrender.com",
                "X-Title": "HERMES OS",
            },
        )
    return _client


async def chat(
    messages: list[dict],
    complexity: TaskComplexity = TaskComplexity.HEAVY,
    model_override: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 4096,
    json_mode: bool = False,
) -> str:
    """
    Chiama LLM via OpenRouter con routing per complessita'.

    Args:
        messages: Lista di messaggi [{"role": "system"|"user"|"assistant", "content": "..."}]
        complexity: Livello complessita' per scegliere il modello
        model_override: Forza un modello specifico (ignora routing)
        temperature: 0.0-1.0
        max_tokens: Limite token risposta
        json_mode: Se True, forza output JSON

    Returns:
        Testo della risposta LLM
    """
    client = _get_client()
    model = model_override or COMPLEXITY_MODEL_MAP[complexity]

    kwargs = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    logger.info(f"LLM call → {model} (complexity={complexity.value}, tokens={max_tokens})")

    try:
        response = await client.chat.completions.create(**kwargs)
        content = response.choices[0].message.content or ""
        logger.debug(f"LLM response ({model}): {content[:200]}...")
        return content

    except Exception as e:
        logger.error(f"LLM call failed ({model}): {e}")
        raise


async def classify_intent(user_message: str) -> dict:
    """
    Classifica l'intent di un messaggio utente.
    Usa Gemini Flash (costo minimo) per routing veloce.

    Returns:
        {"intent": str, "confidence": float, "details": str}
    """
    system_prompt = """Sei il router di HERMES OS. Classifica il messaggio dell'utente in UNA di queste categorie:

- pipeline_request: richiesta di creare/modificare workflow n8n o automazioni
- ads_question: domanda su campagne pubblicitarie, performance ads, metriche
- mail_task: gestione email, risposte, draft, digest
- task_mgmt: gestione task, to-do, priorita', brief
- code_request: generazione codice, landing page, script, app
- complex_project: progetto che richiede piu' agenti (es. "crea campagna completa")
- general_question: domanda generica, conversazione, info
- system_command: comandi di sistema (status, help, config)

Rispondi SOLO in JSON con: {"intent": "...", "confidence": 0.0-1.0, "details": "breve spiegazione"}"""

    response = await chat(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        complexity=TaskComplexity.LIGHT,
        temperature=0.1,
        max_tokens=256,
        json_mode=True,
    )

    import json
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        return {"intent": "general_question", "confidence": 0.5, "details": "parsing failed"}
