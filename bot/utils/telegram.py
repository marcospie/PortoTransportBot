"""Shared helpers for interacting with the Telegram API."""

import logging
from typing import Any, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.utils.i18n import t

logger = logging.getLogger(__name__)

#: Telegram rejects any callback_data longer than this many *bytes* (not
#: characters — accented Portuguese names cost 2 bytes per accent).
CALLBACK_DATA_MAX_BYTES = 64


def _is_not_modified(err: BaseException) -> bool:
    """Whether a Telegram error means "the message already looks like that"."""
    return "message is not modified" in str(err).lower()


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
        if _is_not_modified(err):
            return False
        raise


async def safe_edit_reply_markup(
    query: Any,
    reply_markup: Optional[Any] = None,
) -> bool:
    """Replace only a message's keyboard, tolerating unchanged content.

    Same contract as :func:`safe_edit_message`: returns False when Telegram
    reports the markup as unchanged, re-raises anything else.
    """
    try:
        await query.edit_message_reply_markup(reply_markup=reply_markup)
        return True
    except Exception as err:
        if _is_not_modified(err):
            return False
        raise


def t_safe(key: str, lang: str = "pt", *, pt: str = "", en: str = "") -> str:
    """Translate ``key``, falling back to inline defaults.

    :func:`bot.utils.i18n.t` returns the key itself when a translation is
    missing, which would show users raw identifiers like
    ``kb_bus_direction_swap``. This wrapper keeps every string going through
    ``t()`` (so translations win as soon as they land in ``i18n.py``) while
    guaranteeing the user never sees a key.
    """
    value = t(key, lang)
    if value != key:
        return value
    if lang != "pt" and en:
        return en
    return pt or en or key


def callback_data_ok(data: str) -> bool:
    """Whether ``data`` fits Telegram's hard 64-byte callback_data limit."""
    return len(data.encode("utf-8")) <= CALLBACK_DATA_MAX_BYTES


def safe_callback_button(label: str, data: str) -> Optional[InlineKeyboardButton]:
    """Build a button, or None when its callback_data would be over the limit.

    Telegram silently rejects the whole keyboard if any callback_data exceeds
    64 bytes, so a button that cannot be encoded must be dropped rather than
    breaking every other button in the message.
    """
    if not callback_data_ok(data):
        logger.warning("Dropping button %r: callback_data is %d bytes (max %d)",
                       label, len(data.encode("utf-8")), CALLBACK_DATA_MAX_BYTES)
        return None
    return InlineKeyboardButton(label, callback_data=data)


def truncate_label(text: str, max_chars: int = 30) -> str:
    """Shorten a button label so it stays readable on narrow phone screens."""
    if len(text) <= max_chars:
        return text
    return text[: max(1, max_chars - 1)].rstrip() + "…"


def rows_of(buttons: list, per_row: int = 2) -> list[list]:
    """Chunk a flat list of buttons into keyboard rows."""
    return [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]


def mark_active_button(keyboard: InlineKeyboardMarkup,
                       active_callback_data: str,
                       marker: str = "•") -> InlineKeyboardMarkup:
    """Return a copy of ``keyboard`` with one button visually marked as active.

    Telegram has no "selected" state for inline buttons, so the currently
    applied filter is shown by wrapping its label ("Atrasos" -> "* Atrasos *").
    Labels are copied from the original keyboard, so they stay translated.
    """
    rows = []
    for row in keyboard.inline_keyboard:
        new_row = []
        for button in row:
            if button.callback_data and button.callback_data == active_callback_data:
                new_row.append(InlineKeyboardButton(
                    f"{marker} {button.text} {marker}",
                    callback_data=button.callback_data,
                ))
            else:
                new_row.append(button)
        rows.append(new_row)
    return InlineKeyboardMarkup(rows)
