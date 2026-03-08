"""Favorites management handlers.

Uses the database layer (bot.database) which transparently falls back to
JSON file storage when DATABASE_URL is not configured.
"""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.database import add_favorite, remove_favorite, get_favorites, is_favorite
from bot.keyboards.inline import favorites_keyboard, bus_stop_actions_keyboard
from bot.handlers.start import _clear_awaiting
from bot.utils.formatting import escape_md
from bot.utils.i18n import get_lang, t

logger = logging.getLogger(__name__)


async def favorites_command(update: Update,
                             context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /favorites command."""
    lang = get_lang(update)
    user_id = update.effective_user.id
    favs = await get_favorites(user_id)

    if not favs:
        text = t("favs_title", lang) + "\n\n" + t("favs_empty", lang)
    else:
        text = t("favs_count", lang).format(count=escape_md(str(len(favs))))

    await update.message.reply_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=favorites_keyboard(favs, lang=lang),
    )


async def favorites_callback(update: Update,
                               context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show favorites menu via callback."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)
    _clear_awaiting(context)

    user_id = update.effective_user.id
    favs = await get_favorites(user_id)

    if not favs:
        text = t("favs_title", lang) + "\n\n" + t("favs_empty", lang)
    else:
        text = t("favs_count", lang).format(count=escape_md(str(len(favs))))

    await query.edit_message_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=favorites_keyboard(favs, lang=lang),
    )


async def add_favorite_callback(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE) -> None:
    """Add a stop/station to favorites."""
    query = update.callback_query
    lang = get_lang(update)
    user_id = update.effective_user.id

    # Parse callback data: fav:add:bus:BCM2 or fav:add:metro:Trindade
    parts = query.data.split(":", 3)
    if len(parts) < 4:
        await query.answer(t("fav_add_error", lang))
        return

    fav_type = parts[2]  # bus or metro
    fav_id = parts[3]    # stop_id or station_name

    # Check if already favorited
    if await is_favorite(user_id, fav_type, fav_id):
        await query.answer(t("fav_already", lang))
        return

    # Get name
    if fav_type == "bus":
        from bot.services import stcp
        info = await stcp.get_stop_info(fav_id)
        name = info.get("name", fav_id)
    else:
        name = fav_id

    await add_favorite(user_id, fav_type, fav_id, name)

    await query.answer(t("fav_added", lang).format(name=name))


async def remove_favorite_callback(update: Update,
                                     context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove a stop/station from favorites."""
    query = update.callback_query
    lang = get_lang(update)
    user_id = update.effective_user.id

    parts = query.data.split(":", 3)
    if len(parts) < 4:
        await query.answer(t("fav_remove_error", lang))
        return

    fav_type = parts[2]
    fav_id = parts[3]

    await remove_favorite(user_id, fav_type, fav_id)

    await query.answer(t("fav_removed", lang))

    # Refresh the favorites list
    favs = await get_favorites(user_id)
    if not favs:
        text = t("favs_title", lang) + "\n\n" + t("favs_empty", lang)
    else:
        text = t("favs_count", lang).format(count=escape_md(str(len(favs))))

    await query.edit_message_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=favorites_keyboard(favs, lang=lang),
    )


async def fav_quick_command(update: Update,
                             context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /fav command - show first favorite's real-time data."""
    lang = get_lang(update)
    user_id = update.effective_user.id
    favs = await get_favorites(user_id)

    if not favs:
        await update.message.reply_text(
            t("favs_empty_short", lang),
            parse_mode="MarkdownV2",
        )
        return

    fav = favs[0]
    if fav["type"] == "bus":
        from bot.handlers.bus import _send_stop_realtime
        await _send_stop_realtime(update.message, fav["id"], context, lang=lang)
    else:
        from bot.handlers.metro import _search_and_show_stations
        await _search_and_show_stations(update.message, fav["id"], context, lang=lang)
