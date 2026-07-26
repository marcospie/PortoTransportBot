"""Favorites management handlers.

Uses the database layer (bot.database) which transparently falls back to
JSON file storage when DATABASE_URL is not configured.
"""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.database import add_favorite, remove_favorite, get_favorites, is_favorite
from bot.keyboards.inline import (
    favorites_keyboard,
    bus_stop_actions_keyboard,
    metro_station_actions_keyboard,
    metrobus_stop_actions_keyboard,
    train_station_actions_keyboard,
    favorite_emoji,
)
from bot.handlers.start import _clear_awaiting
from bot.utils.formatting import escape_md
from bot.utils.i18n import get_lang, t
from bot.utils.telegram import safe_edit_message

logger = logging.getLogger(__name__)

#: The four favorite types the bot can store, matching the ``fav:add:<type>:``
#: callback fragments emitted by the station/stop action keyboards.
FAV_TYPES = ("bus", "metro", "metrobus", "train")

#: Builder for the station/stop "actions" keyboard of each mode, so a star
#: toggled from a detail view can be re-rendered in place.
_ACTIONS_KEYBOARDS = {
    "bus": bus_stop_actions_keyboard,
    "metro": metro_station_actions_keyboard,
    "metrobus": metrobus_stop_actions_keyboard,
    "train": train_station_actions_keyboard,
}

#: Where "back" goes by default for each mode's detail view.
_DEFAULT_BACK = {
    "bus": "menu:bus",
    "metro": "menu:metro",
    "metrobus": "menu:metrobus",
    "train": "menu:trains",
}

#: Callback prefixes that appear *only* in a mode's detail keyboard.  Their
#: presence is what tells us the star was tapped from a detail view (where the
#: user is reading arrivals) rather than from the favorites list.
_DETAIL_MARKERS = {
    "bus": ("bus:info:", "bus:loc:"),
    "metro": ("metro:station_lines:", "metro:loc:"),
    "metrobus": ("metrobus:stop_lines:", "metrobus:loc:"),
    "train": ("train:station_lines:", "train:loc:"),
}

#: Fallback wording for keys not yet present in bot.utils.i18n.
_FALLBACKS = {
    "pt": {
        "fav_usage": ("Uso: `/fav` \\| `/fav 2` \\| `/fav Trindade`\n"
                      "Toca num favorito abaixo ou indica o número/nome\\."),
        "fav_not_found": "❌ Não encontrei o favorito *{query}*\\.",
    },
    "en": {
        "fav_usage": ("Usage: `/fav` \\| `/fav 2` \\| `/fav Trindade`\n"
                      "Tap a favorite below or pass its number/name\\."),
        "fav_not_found": "❌ No favorite matching *{query}*\\.",
    },
}


def _t(key: str, lang: str = "pt") -> str:
    """Translate ``key``, falling back to this module's own wording."""
    value = t(key, lang)
    if value != key:
        return value
    table = _FALLBACKS.get(lang) or _FALLBACKS["pt"]
    return table.get(key, _FALLBACKS["pt"].get(key, key))


# ===================================================================
# Helpers for editing the view a favorite toggle came from
# ===================================================================

def _keyboard_rows(query) -> list | None:
    """Return the current message's keyboard rows, or None if unavailable."""
    message = getattr(query, "message", None)
    markup = getattr(message, "reply_markup", None)
    rows = getattr(markup, "inline_keyboard", None)
    if isinstance(rows, (list, tuple)):
        return list(rows)
    return None


def _is_detail_view(rows: list | None, fav_type: str) -> bool:
    """True when the current keyboard is a station/stop detail keyboard."""
    if not rows:
        return False
    markers = _DETAIL_MARKERS.get(fav_type)
    if not markers:
        return False
    for row in rows:
        for button in row:
            data = getattr(button, "callback_data", None)
            if isinstance(data, str) and data.startswith(markers):
                return True
    return False


def _back_callback(rows: list | None, fav_type: str) -> str:
    """Recover the detail view's "back" target so it survives a re-render."""
    default = _DEFAULT_BACK.get(fav_type, "menu:main")
    if not rows:
        return default
    for row in rows:
        buttons = list(row)
        if not any(isinstance(getattr(b, "callback_data", None), str)
                   and getattr(b, "callback_data").startswith("fav:")
                   for b in buttons):
            continue
        for button in reversed(buttons):
            data = getattr(button, "callback_data", None)
            if isinstance(data, str) and not data.startswith("fav:"):
                return data
    return default


def _message_markdown(query) -> str | None:
    """Return the current message text as MarkdownV2, or None.

    Only the pre-escaped MarkdownV2 renderings are acceptable: re-sending the
    plain ``.text`` with ``parse_mode="MarkdownV2"`` would fail on any name
    containing a hyphen, dot or parenthesis.
    """
    message = getattr(query, "message", None)
    if message is None:
        return None
    for attr in ("text_markdown_v2", "text_markdown_v2_urled"):
        try:
            value = getattr(message, attr, None)
        except Exception:
            value = None
        if isinstance(value, str) and value.strip():
            return value
    return None


async def _rerender_detail_view(query, fav_type: str, fav_id: str,
                                is_fav: bool, lang: str,
                                rows: list | None) -> bool:
    """Re-draw the detail view the user is on with the star toggled.

    Returns True when the view was re-rendered, False when there was nothing
    safe to edit (caller should then fall back to the favorites list).
    """
    builder = _ACTIONS_KEYBOARDS.get(fav_type)
    if builder is None:
        return False

    keyboard = builder(fav_id, is_fav=is_fav, lang=lang,
                       back_callback=_back_callback(rows, fav_type))
    text = _message_markdown(query)
    try:
        if text is None:
            # Text could not be recovered — swap just the keyboard so the
            # user still keeps whatever they were reading.
            await query.edit_message_reply_markup(reply_markup=keyboard)
        else:
            await safe_edit_message(query, text, reply_markup=keyboard)
    except Exception:
        logger.exception("Could not re-render detail view for %s:%s",
                         fav_type, fav_id)
        return False
    return True


def _favorites_text(favs: list[dict], lang: str) -> str:
    """Header text for the favorites list."""
    if not favs:
        return t("favs_title", lang) + "\n\n" + t("favs_empty", lang)
    return t("favs_count", lang).format(count=escape_md(str(len(favs))))


# ===================================================================
# Commands & callbacks
# ===================================================================

async def favorites_command(update: Update,
                             context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /favorites command."""
    lang = get_lang(update)
    user_id = update.effective_user.id
    favs = await get_favorites(user_id)

    text = _favorites_text(favs, lang)
    if favs:
        text += "\n\n" + _favorites_listing(favs) + "\n\n" + _t("fav_usage", lang)

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

    await query.edit_message_text(
        _favorites_text(favs, lang),
        parse_mode="MarkdownV2",
        reply_markup=favorites_keyboard(favs, lang=lang),
    )


async def add_favorite_callback(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE) -> None:
    """Add a stop/station to favorites and toggle the button in place."""
    query = update.callback_query
    lang = get_lang(update)
    user_id = update.effective_user.id

    # Parse callback data: fav:add:bus:BCM2 or fav:add:train:Porto-Campanha
    parts = query.data.split(":", 3)
    if len(parts) < 4:
        await query.answer(t("fav_add_error", lang))
        return

    fav_type = parts[2]  # bus, metro, metrobus or train
    fav_id = parts[3]    # stop_id or station_name

    rows = _keyboard_rows(query)

    # Check if already favorited
    if await is_favorite(user_id, fav_type, fav_id):
        await query.answer(t("fav_already", lang))
        # The keyboard was showing a stale "add" button — fix it so the user
        # is not stuck tapping a button that can only ever fail.
        if _is_detail_view(rows, fav_type):
            await _rerender_detail_view(query, fav_type, fav_id,
                                        is_fav=True, lang=lang, rows=rows)
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

    if _is_detail_view(rows, fav_type):
        await _rerender_detail_view(query, fav_type, fav_id,
                                    is_fav=True, lang=lang, rows=rows)


async def remove_favorite_callback(update: Update,
                                     context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove a stop/station from favorites, staying where the user was."""
    query = update.callback_query
    lang = get_lang(update)
    user_id = update.effective_user.id

    parts = query.data.split(":", 3)
    if len(parts) < 4:
        await query.answer(t("fav_remove_error", lang))
        return

    fav_type = parts[2]
    fav_id = parts[3]

    rows = _keyboard_rows(query)
    from_detail = _is_detail_view(rows, fav_type)

    await remove_favorite(user_id, fav_type, fav_id)

    await query.answer(t("fav_removed", lang))

    # Unfavoriting from a station detail view must not throw away the arrivals
    # the user is reading — only the star flips back.
    if from_detail and await _rerender_detail_view(
            query, fav_type, fav_id, is_fav=False, lang=lang, rows=rows):
        return

    # Came from the favorites list (or an unknown view): refresh the list.
    favs = await get_favorites(user_id)
    await safe_edit_message(query, _favorites_text(favs, lang),
                            reply_markup=favorites_keyboard(favs, lang=lang))


# ===================================================================
# /fav quick command
# ===================================================================

def _favorites_listing(favs: list[dict]) -> str:
    """Numbered, MarkdownV2-escaped listing of every favorite."""
    lines = []
    for i, fav in enumerate(favs, start=1):
        emoji = favorite_emoji(fav.get("type", "metro"))
        name = escape_md(str(fav.get("name") or fav["id"]))
        if fav.get("type") == "bus":
            lines.append(f"  {i}\\. {emoji} {name} \\(`{escape_md(fav['id'])}`\\)")
        else:
            lines.append(f"  {i}\\. {emoji} {name}")
    return "\n".join(lines)


def _resolve_favorite(favs: list[dict], argument: str) -> dict | None:
    """Resolve a /fav argument to one favorite, by index or by name."""
    argument = argument.strip()
    if not argument:
        return None

    if argument.isdigit():
        index = int(argument)
        if 1 <= index <= len(favs):
            return favs[index - 1]
        return None

    needle = argument.casefold()
    # Exact name/id match first, then prefix, then substring.
    for matcher in (
        lambda value: value == needle,
        lambda value: value.startswith(needle),
        lambda value: needle in value,
    ):
        for fav in favs:
            candidates = (str(fav.get("name") or "").casefold(),
                          str(fav.get("id") or "").casefold())
            if any(candidate and matcher(candidate) for candidate in candidates):
                return fav
    return None


async def _open_favorite(message, fav: dict, context, lang: str) -> None:
    """Show live data for one favorite using its own transport handler."""
    fav_type = fav.get("type")
    fav_id = fav["id"]

    if fav_type == "bus":
        from bot.handlers.bus import _send_stop_realtime
        await _send_stop_realtime(message, fav_id, context, lang=lang)
    elif fav_type == "metrobus":
        await _send_metrobus_stop(message, fav_id, lang=lang)
    elif fav_type == "train":
        from bot.handlers.trains import _search_and_show_stations
        await _search_and_show_stations(message, fav_id, context, lang=lang)
    else:
        from bot.handlers.metro import _search_and_show_stations
        await _search_and_show_stations(message, fav_id, context, lang=lang)


_METROBUS_EMOJI = "\U0001f68d"


async def _send_metrobus_stop(message, stop_name: str, lang: str = "pt",
                               is_fav: bool = True) -> None:
    """Send MetroBus departures for a stop.

    The MetroBus handler only exposes callback entry points, so the message is
    assembled here from the same service + formatter it uses.
    """
    from bot.services import metrobus
    from bot.services.metrobus import METROBUS_LINES, STOPS
    from bot.utils.formatting import format_metrobus_schedule

    stop_data = STOPS.get(stop_name, {})
    lines_info = []
    for line_code in stop_data.get("lines", []):
        line = METROBUS_LINES.get(line_code, {})
        emoji = line.get("emoji", _METROBUS_EMOJI)
        lines_info.append(f"{emoji} {line.get('name', line_code)}")
    line_info_str = " \\| ".join(escape_md(li) for li in lines_info) if lines_info else ""

    departures = metrobus.get_next_departures(stop_name)
    text = format_metrobus_schedule(stop_name, line_info_str, departures)

    await message.reply_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=metrobus_stop_actions_keyboard(stop_name, is_fav=is_fav,
                                                     lang=lang),
    )


async def fav_quick_command(update: Update,
                             context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /fav — open a favorite by number or name, or list them all.

    ``/fav`` with a single favorite opens it directly; with several it shows a
    dashboard of all of them.  ``/fav 2`` and ``/fav Campanhã`` open a
    specific one.
    """
    lang = get_lang(update)
    user_id = update.effective_user.id
    favs = await get_favorites(user_id)

    if not favs:
        await update.message.reply_text(
            t("favs_empty_short", lang),
            parse_mode="MarkdownV2",
        )
        return

    args = getattr(context, "args", None) or []
    argument = " ".join(str(a) for a in args).strip()

    if argument:
        fav = _resolve_favorite(favs, argument)
        if fav is not None:
            await _open_favorite(update.message, fav, context, lang)
            return
        # Unresolved argument: say so, then show the dashboard so the user can
        # see the valid numbers and names.
        await update.message.reply_text(
            _t("fav_not_found", lang).format(query=escape_md(argument))
            + "\n\n" + _t("fav_usage", lang),
            parse_mode="MarkdownV2",
            reply_markup=favorites_keyboard(favs, lang=lang),
        )
        return

    if len(favs) == 1:
        await _open_favorite(update.message, favs[0], context, lang)
        return

    # Several favorites and no argument: one dashboard message with all of
    # them, instead of silently opening only the first.
    text = (_favorites_text(favs, lang) + "\n\n"
            + _favorites_listing(favs) + "\n\n"
            + _t("fav_usage", lang))
    await update.message.reply_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=favorites_keyboard(favs, lang=lang),
    )
