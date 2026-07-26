"""Shared helpers for interacting with the Telegram API."""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


async def safe_edit_message(
    query: Any,
    text: str,
    reply_markup: Optional[Any] = None,
    parse_mode: str = "MarkdownV2",
) -> bool:
    """Edit a callback query's message, tolerating unchanged content.

    Telegram raises ``BadRequest("Message is not modified")`` when an edit
    would leave the message exactly as it already is -- which happens every
    time a user taps a refresh button and the data has not changed yet.
    That is not an error the user should ever see.

    Returns True if the message was actually edited, False if Telegram
    reported it as unchanged. Any other failure is re-raised.
    """
    try:
        await query.edit_message_text(
            text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )
        return True
    except Exception as err:
        if "Message is not modified" in str(err):
            return False
        raise
