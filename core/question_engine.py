"""
HERMES OS — Question Engine
Gestisce il ciclo domanda-risposta tra agenti e Juan.
Componente trasversale usato da tutti gli orchestratori.

Regole:
- Max 3 round di domande per task
- Tutte le domande aggregate in 1 solo messaggio
- Max 5 domande per messaggio
- Timeout 30 min → procede con best guess + avviso
- Se info in KB → usa quella, non chiede
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

import config
from core import knowledge_base as kb

logger = logging.getLogger("hermes.questions")

# Stato pending delle domande in attesa di risposta
_pending_questions: dict[str, dict] = {}
# Risposte ricevute (question_id → risposta)
_received_answers: dict[str, str] = {}
# Event per notifica risposta
_answer_events: dict[str, asyncio.Event] = {}


def _format_question_message(
    agent_name: str,
    task_description: str,
    questions: list[str],
) -> str:
    """Formatta il messaggio domande secondo il template standard."""
    q_list = "\n".join(f"{i+1}. {q}" for i, q in enumerate(questions))

    return (
        f"\u2753 HERMES ha bisogno di info \u2014 {agent_name}\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"Prima di procedere con: {task_description}\n"
        f"Ho bisogno di chiarire:\n\n"
        f"{q_list}\n\n"
        f"Rispondi con: '1: risposta / 2: risposta'\n"
        f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
        f"\u23f3 Attendo {config.QUESTION_TIMEOUT_MINUTES} min, poi procedo con best guess"
    )


async def ask_questions(
    agent_name: str,
    task_description: str,
    questions: list[str],
    round_number: int = 1,
    bot: Bot | None = None,
) -> dict[int, str]:
    """
    Invia domande a Juan via Telegram e attende risposte.

    Args:
        agent_name: Nome dell'agente che chiede
        task_description: Descrizione del task in corso
        questions: Lista di domande (max 5)
        round_number: Numero del round corrente (max 3)
        bot: Istanza del bot Telegram

    Returns:
        Dict {numero_domanda: risposta} — vuoto se timeout
    """
    # Verifica limiti
    if round_number > config.MAX_QUESTION_ROUNDS:
        logger.warning(f"Max round ({config.MAX_QUESTION_ROUNDS}) raggiunto per {agent_name}")
        return {}

    # Tronca a max domande per round
    if len(questions) > config.MAX_QUESTIONS_PER_ROUND:
        logger.warning(f"Troppe domande ({len(questions)}), prendo le prime {config.MAX_QUESTIONS_PER_ROUND}")
        questions = questions[:config.MAX_QUESTIONS_PER_ROUND]

    # Prima cerca nella KB
    answered = {}
    remaining = []
    for i, q in enumerate(questions):
        # Prova a trovare risposta nella KB
        kb_answer = await _search_kb_for_answer(q)
        if kb_answer:
            answered[i + 1] = kb_answer
            logger.info(f"Domanda {i+1} risolta da KB: {q[:50]}...")
        else:
            remaining.append((i + 1, q))

    # Se tutte le risposte trovate in KB, ritorna subito
    if not remaining:
        logger.info("Tutte le domande risolte dalla KB")
        return answered

    # Invia messaggio Telegram
    remaining_questions = [q for _, q in remaining]
    message_text = _format_question_message(agent_name, task_description, remaining_questions)

    question_id = f"{agent_name}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    _answer_events[question_id] = asyncio.Event()
    _pending_questions[question_id] = {
        "agent": agent_name,
        "questions": {num: q for num, q in remaining},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if bot and config.TELEGRAM_CHAT_ID:
        try:
            await bot.send_message(
                chat_id=config.TELEGRAM_CHAT_ID,
                text=message_text,
                parse_mode=None,  # Plain text per evitare problemi con caratteri speciali
            )
            logger.info(f"Domande inviate a Juan: {question_id}")
        except Exception as e:
            logger.error(f"Errore invio domande Telegram: {e}")
            return answered

    # Attendi risposta con timeout
    try:
        await asyncio.wait_for(
            _answer_events[question_id].wait(),
            timeout=config.QUESTION_TIMEOUT_MINUTES * 60,
        )
        # Risposta ricevuta
        if question_id in _received_answers:
            raw = _received_answers.pop(question_id)
            parsed = _parse_answers(raw, remaining)
            answered.update(parsed)
            logger.info(f"Risposte ricevute per {question_id}")
    except asyncio.TimeoutError:
        logger.warning(f"Timeout per {question_id} — procedo con best guess")
        # Non blocchiamo, l'agente procedera' con best guess

    # Cleanup
    _pending_questions.pop(question_id, None)
    _answer_events.pop(question_id, None)

    return answered


def receive_answer(answer_text: str):
    """
    Chiamato quando Juan risponde a un messaggio di domande.
    Matcha con la domanda pending piu' recente.
    """
    if not _pending_questions:
        logger.debug("Nessuna domanda pending — messaggio ignorato dal QE")
        return False

    # Prendi la domanda piu' recente
    question_id = list(_pending_questions.keys())[-1]
    _received_answers[question_id] = answer_text

    if question_id in _answer_events:
        _answer_events[question_id].set()
        logger.info(f"Risposta ricevuta per {question_id}")
        return True

    return False


def has_pending_questions() -> bool:
    """Controlla se ci sono domande in attesa."""
    return len(_pending_questions) > 0


def _parse_answers(raw_text: str, questions: list[tuple[int, str]]) -> dict[int, str]:
    """
    Parsa risposte nel formato '1: risposta / 2: risposta'.
    Supporta anche risposte libere se c'e' una sola domanda.
    """
    answers = {}

    # Se una sola domanda, la risposta intera e' per quella
    if len(questions) == 1:
        num, _ = questions[0]
        answers[num] = raw_text.strip()
        return answers

    # Parsing formato "1: risposta / 2: risposta"
    parts = raw_text.split("/")
    for part in parts:
        part = part.strip()
        if ":" in part:
            try:
                num_str, answer = part.split(":", 1)
                num = int(num_str.strip())
                answers[num] = answer.strip()
            except (ValueError, IndexError):
                continue

    # Se non ha parsato niente, assegna tutta la risposta alla prima domanda
    if not answers and questions:
        num, _ = questions[0]
        answers[num] = raw_text.strip()

    return answers


async def _search_kb_for_answer(question: str) -> Optional[str]:
    """
    Cerca nella KB se la risposta a una domanda e' gia' nota.
    Estrae keyword dalla domanda e cerca.
    """
    # Estrai potenziali nomi/entita' dalla domanda
    # (semplificato — in futuro puo' usare LLM per estrazione)
    words = question.split()
    for word in words:
        # Cerca parole capitalizzate come potenziali entita'
        if len(word) > 3 and word[0].isupper():
            result = await kb.search_entity(word)
            if result:
                return result
    return None


async def save_answers_to_kb(answers: dict[int, str], questions: list[str]):
    """
    Salva le risposte ricevute nella KB per apprendimento permanente.
    Regola: ogni entita' sconosciuta viene appresa e non chiesta mai piu'.
    """
    for num, answer in answers.items():
        if num <= len(questions):
            question = questions[num - 1]
            # Log in history
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
            entry = f"### [{now}] Q&A\n**D**: {question}\n**R**: {answer}\n"
            await kb.log_history("decisions", entry)
