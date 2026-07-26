"""Persistence for the WhatsApp channel, on top of ``bot.database``.

``bot.database`` is channel-agnostic (favorites/settings are keyed by a single
user id), so the WhatsApp bot reuses it instead of inventing a second store.
Two things make that safe:

**1. Id namespacing.**  WhatsApp identifies users by phone number, Telegram by a
numeric account id, and both land in the *same* ``users.id`` column.  A textual
``"wa:351..."`` prefix is impossible here - the schema in ``bot/database.py``
declares::

    users.id            BIGINT PRIMARY KEY
    favorites.user_id   BIGINT NOT NULL REFERENCES users(id)

so the id has to stay an integer.  :func:`wa_user_id` therefore namespaces by
*sign*: WhatsApp users are stored as the **negative** of their E.164 digits.
Telegram user ids are always positive, which makes a collision impossible while
staying inside BIGINT.  (Consequence: a person cannot share one favorites list
between Telegram and WhatsApp - that would need an explicit account-linking
feature, not an id trick.)

**2. Defensive calls.**  ``bot/database.py`` is owned by the Telegram side, so
every function here goes through :func:`_call`, which tolerates a missing
attribute or a raising implementation instead of 500-ing the webhook.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

__all__ = [
    "wa_user_id",
    "add_favorite",
    "remove_favorite",
    "get_favorites",
    "is_favorite",
    "get_language",
    "set_language",
]

# Postgres BIGINT range.
_BIGINT_MAX = 9_223_372_036_854_775_807


def wa_user_id(phone: str) -> int:
    """Map a WhatsApp phone number to a namespaced integer user id.

    Returns ``-int(digits)`` so WhatsApp ids can never collide with Telegram's
    (always positive) ids while remaining storable in a BIGINT column.  Absurdly
    long inputs are folded through blake2b to stay in range.
    """
    digits = "".join(c for c in (phone or "") if c.isdigit())
    if not digits:
        raise ValueError("WhatsApp sender has no digits to derive a user id from")
    value = int(digits)
    if value > _BIGINT_MAX:
        # Never happens for a real E.164 number (max 15 digits); fold instead of
        # overflowing the column.
        digest = hashlib.blake2b(digits.encode(), digest_size=7).digest()
        value = int.from_bytes(digest, "big")
    return -value


async def _call(name: str, *args, default: Any = None) -> Any:
    """Call ``bot.database.<name>(*args)`` defensively.

    ``bot.database`` is imported lazily and looked up by name so that a change
    on the Telegram side degrades to "favorites unavailable" rather than an
    exception escaping into the webhook worker.
    """
    try:
        from bot import database as db
    except Exception:
        logger.exception("bot.database is unavailable")
        return default

    fn: Callable | None = getattr(db, name, None)
    if fn is None:
        logger.error("bot.database.%s is missing - favorites feature degraded", name)
        return default

    try:
        result = fn(*args)
        if hasattr(result, "__await__"):
            result = await result
        return result
    except Exception:
        logger.exception("bot.database.%s failed", name)
        return default


async def add_favorite(phone: str, fav_type: str, item_id: str, name: str) -> bool:
    """Store a favorite for a WhatsApp user. True if newly added."""
    return bool(await _call(
        "add_favorite", wa_user_id(phone), fav_type, item_id, name, default=False,
    ))


async def remove_favorite(phone: str, fav_type: str, item_id: str) -> bool:
    """Remove a favorite. True if something was deleted."""
    return bool(await _call(
        "remove_favorite", wa_user_id(phone), fav_type, item_id, default=False,
    ))


async def get_favorites(phone: str) -> list[dict]:
    """Return the user's favorites (``[{type, id, name}, ...]``)."""
    favs = await _call("get_favorites", wa_user_id(phone), default=[])
    return list(favs) if favs else []


async def is_favorite(phone: str, fav_type: str, item_id: str) -> bool:
    """True if the stop/station is already a favorite."""
    return bool(await _call(
        "is_favorite", wa_user_id(phone), fav_type, item_id, default=False,
    ))


async def get_language(phone: str) -> str | None:
    """Return the stored language preference, or None if unset/auto."""
    settings = await _call("get_user_settings", wa_user_id(phone), default=None)
    if not isinstance(settings, dict):
        return None
    lang = settings.get("language")
    if not lang or lang == "auto":
        return None
    return str(lang)


async def set_language(phone: str, lang: str) -> None:
    """Persist the user's language preference."""
    await _call("update_user_setting", wa_user_id(phone), "language", lang)
