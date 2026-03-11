"""
HERMES OS — Telegram Utilities
Funzioni helper per gestire limiti e peculiarità dell'API Telegram.
"""

from telegram import Update

# Telegram message character limit
TG_MAX_LENGTH = 4096


async def send_long_message(
    update: Update,
    text: str,
    parse_mode: str | None = None,
) -> None:
    """
    Invia un messaggio Telegram, splittando automaticamente
    se supera il limite di 4096 caratteri.
    Taglia su newline quando possibile per non spezzare frasi.
    """
    if not text:
        return

    if len(text) <= TG_MAX_LENGTH:
        await update.message.reply_text(text, parse_mode=parse_mode)
        return

    chunks = _split_text(text, TG_MAX_LENGTH)
    for chunk in chunks:
        await update.message.reply_text(chunk, parse_mode=parse_mode)


def _split_text(text: str, max_len: int) -> list[str]:
    """Splitta testo in chunk ≤ max_len, preferendo newline come punto di taglio."""
    chunks = []
    while len(text) > max_len:
        # Cerca l'ultimo newline entro il limite
        cut = text.rfind("\n", 0, max_len)
        if cut == -1 or cut < max_len // 4:
            # Nessun newline utile — taglia su spazio
            cut = text.rfind(" ", 0, max_len)
        if cut == -1 or cut < max_len // 4:
            # Nessuno spazio utile — taglio forzato
            cut = max_len

        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")

    if text.strip():
        chunks.append(text)

    return chunks
