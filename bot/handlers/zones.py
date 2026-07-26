"""Handler for the Andante Zone Calculator feature.

Notes for whoever wires this up:

* Every prompt now carries an inline keyboard so the user can always back out.
  The cancel button reuses the already-registered ``menu:zones`` callback, so
  no new handler registration is needed.
* Typo suggestions are offered as buttons on the already-registered
  ``zones:zone:.+`` pattern; :func:`zones_zone_callback` tells a zone code
  (``PRT1``) apart from a station name and dispatches accordingly.  A dedicated
  ``^zones:pick:`` pattern in ``bot/main.py`` would be tidier, but this works
  without touching the router.
* New i18n keys are listed in :data:`_FALLBACK_STRINGS`.  Until they land in
  ``bot/utils/i18n.py`` the fallbacks below are used, so nothing ever shows a
  raw key to a user.
"""

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.services import fares
from bot.services.zones import (
    ZONE_ADJACENCY,
    calculate_zones,
    get_stations_in_zone,
    resolve_station,
    search_station,
    suggest_stations,
)
from bot.keyboards.inline import (
    zones_menu_keyboard,
    zones_result_keyboard,
    zones_map_keyboard,
    zone_detail_keyboard,
)
from bot.utils.i18n import t, get_lang
from bot.utils.formatting import escape_md
from bot.utils.telegram import safe_edit_message

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# i18n keys this handler introduces.  bot/utils/i18n.py is owned by another
# agent, so until these land we fall back to the text below rather than showing
# the user a raw key name.
# ---------------------------------------------------------------------------

_FALLBACK_STRINGS: dict[str, dict[str, str]] = {
    "zones_zone_empty": {
        "pt": "_Nenhuma estação nesta zona_",
        "en": "_No stations in this zone_",
    },
    "zones_suggestions": {
        "pt": "Será que querias dizer:",
        "en": "Did you mean:",
    },
    "zones_approx": {
        "pt": (
            "⚠️ *Estimativa* — a zona de uma das estações não é publicada pelo "
            "operador\\. Confirma na máquina Andante\\."
        ),
        "en": (
            "⚠️ *Estimate* — the operator does not publish the zone of one of "
            "these stations\\. Please confirm at an Andante machine\\."
        ),
    },
    "zones_outside": {
        "pt": (
            "ℹ️ *{name}* está fora da rede Andante, por isso não há título "
            "Andante para esta viagem\\. Compra bilhete CP normal\\."
        ),
        "en": (
            "ℹ️ *{name}* is outside the Andante network, so no Andante title "
            "covers this trip\\. Buy a regular CP ticket\\."
        ),
    },
    "zones_price_unpublished": {
        "pt": (
            "O operador não publica o preço do título *{title}*\\. "
            "Confirma na máquina Andante\\."
        ),
        "en": (
            "The operator does not publish the price of the *{title}* title\\. "
            "Please check at an Andante machine\\."
        ),
    },
    "zones_zone_label": {
        "pt": "🎟 *Título necessário:* {title}",
        "en": "🎟 *Title needed:* {title}",
    },
}

#: Convenience list for the integrator: every new key used here.
NEW_I18N_KEYS: tuple[str, ...] = tuple(_FALLBACK_STRINGS)


def _s(key: str, lang: str) -> str:
    """Translate ``key``, falling back to our own copy if i18n lacks it.

    ``bot.utils.i18n.t`` returns the key itself when it is unknown, which would
    leak ``zones_zone_empty`` into a chat message.
    """
    value = t(key, lang)
    if value != key:
        return value
    fallback = _FALLBACK_STRINGS.get(key, {})
    return fallback.get(lang) or fallback.get("pt") or key


# ---------------------------------------------------------------------------
# Local keyboards (bot/keyboards/inline.py is owned by another agent)
# ---------------------------------------------------------------------------

def _cancel_keyboard(lang: str = "pt") -> InlineKeyboardMarkup:
    """Cancel / back keyboard for the station-name prompts."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("kb_cancel", lang), callback_data="menu:zones")],
        [InlineKeyboardButton(t("back_main", lang), callback_data="menu:main")],
    ])


def _suggestions_keyboard(names: list[str], lang: str = "pt") -> InlineKeyboardMarkup:
    """Tappable "did you mean ...?" buttons plus a way out."""
    rows = []
    for name in names:
        payload = f"zones:zone:{name}"
        # Telegram caps callback_data at 64 bytes.
        if len(payload.encode("utf-8")) > 64:
            continue
        rows.append([InlineKeyboardButton(f"📍 {name}", callback_data=payload)])
    rows.append([InlineKeyboardButton(t("kb_cancel", lang), callback_data="menu:zones")])
    return InlineKeyboardMarkup(rows)


# ---------------------------------------------------------------------------
# Commands and callbacks
# ---------------------------------------------------------------------------

async def zones_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle ``/zonas``, ``/zonas <origin>`` and ``/zonas <origin> <dest>``."""
    lang = get_lang(update)
    args = context.args or []

    if len(args) >= 2:
        origin = args[0]
        dest = " ".join(args[1:])
        result = calculate_zones(origin, dest)
        if result:
            await _send_zone_result(update.message, result, lang)
            return
        # Fall through to the menu, but say why nothing happened.
        await _reply_not_found(update.message, f"{origin} / {dest}", lang)
        return

    if len(args) == 1:
        # One argument used to be silently dropped.  Treat it as the origin and
        # ask for the destination, showing the two-station usage as a hint.
        origin = args[0]
        resolved = resolve_station(origin)
        if resolved:
            context.user_data["zones_origin"] = resolved["name"]
            context.user_data["zones_step"] = "dest"
            await update.message.reply_text(
                _origin_set_text(resolved, lang)
                + "\n\n" + t("zones_ask_dest", lang)
                + "\n\n_" + escape_md(t("zones_quick_usage", lang)
                                      .replace("`", "")) + "_",
                parse_mode="MarkdownV2",
                reply_markup=_cancel_keyboard(lang),
            )
            return
        await _reply_not_found(update.message, origin, lang)
        return

    await update.message.reply_text(
        t("zones_title", lang) + "\n\n_" + escape_md(
            t("zones_quick_usage", lang).replace("`", "")) + "_",
        parse_mode="MarkdownV2",
        reply_markup=zones_menu_keyboard(lang),
    )


async def zones_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the zone calculator menu (also used as the cancel target)."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)
    context.user_data.pop("zones_step", None)
    context.user_data.pop("zones_origin", None)
    await safe_edit_message(
        query,
        t("zones_title", lang) + "\n\n_" + escape_md(
            t("zones_quick_usage", lang).replace("`", "")) + "_",
        reply_markup=zones_menu_keyboard(lang),
    )


async def zones_calculate_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start a zone calculation - ask for the origin station."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)
    context.user_data["zones_step"] = "origin"
    context.user_data.pop("zones_origin", None)
    await safe_edit_message(
        query,
        t("zones_ask_origin", lang),
        reply_markup=_cancel_keyboard(lang),
    )


async def zones_map_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the zone map overview."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)
    await safe_edit_message(
        query,
        t("zones_map_title", lang),
        reply_markup=zones_map_keyboard(lang),
    )


async def zones_zone_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the stations in a zone, or accept a suggested station name.

    The registered pattern is ``zones:zone:.+``; a payload that is a real zone
    code (``PRT1``) lists that zone's stations, anything else is treated as a
    station the user tapped from a "did you mean ...?" list.
    """
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)
    payload = query.data.split(":", 2)[-1]

    if payload not in ZONE_ADJACENCY:
        await _handle_picked_station(update, context, payload, lang)
        return

    stations = get_stations_in_zone(payload)
    if stations:
        station_list = "\n".join(f"• {escape_md(s)}" for s in stations[:20])
        if len(stations) > 20:
            more = len(stations) - 20
            station_list += "\n" + escape_md(f"...e mais {more}"
                                             if lang == "pt"
                                             else f"...and {more} more")
    else:
        station_list = _s("zones_zone_empty", lang)

    text = t("zones_zone_detail", lang).format(
        zone=escape_md(payload),
        stations=station_list,
    )
    await safe_edit_message(
        query, text, reply_markup=zone_detail_keyboard(payload, lang)
    )


async def _handle_picked_station(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                 name: str, lang: str) -> None:
    """User tapped a suggested station name: feed it into the current step."""
    query = update.callback_query
    step = context.user_data.get("zones_step") or "origin"

    if step == "dest" and context.user_data.get("zones_origin"):
        result = calculate_zones(context.user_data["zones_origin"], name)
        if result:
            context.user_data.pop("zones_step", None)
            context.user_data.pop("zones_origin", None)
            await safe_edit_message(
                query,
                _format_zone_result(result, lang),
                reply_markup=zones_result_keyboard(
                    result["origin_name"], result["dest_name"], lang
                ),
            )
            return

    resolved = resolve_station(name)
    if not resolved:
        await safe_edit_message(
            query,
            t("zones_not_found", lang).format(name=escape_md(name)),
            reply_markup=_cancel_keyboard(lang),
        )
        return

    context.user_data["zones_origin"] = resolved["name"]
    context.user_data["zones_step"] = "dest"
    await safe_edit_message(
        query,
        _origin_set_text(resolved, lang) + "\n\n" + t("zones_ask_dest", lang),
        reply_markup=_cancel_keyboard(lang),
    )


async def handle_zones_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle text input during zone calculation. Returns True if handled."""
    step = context.user_data.get("zones_step")
    if not step:
        return False

    text = update.message.text.strip()
    lang = get_lang(update)

    if step == "origin":
        resolved = resolve_station(text)
        if not resolved:
            matches = search_station(text)
            if matches:
                resolved = resolve_station(matches[0][0])

        if not resolved:
            await _reply_not_found(update.message, text, lang)
            return True

        context.user_data["zones_origin"] = resolved["name"]
        context.user_data["zones_step"] = "dest"
        await update.message.reply_text(
            _origin_set_text(resolved, lang) + "\n\n" + t("zones_ask_dest", lang),
            parse_mode="MarkdownV2",
            reply_markup=_cancel_keyboard(lang),
        )
        return True

    if step == "dest":
        origin = context.user_data.get("zones_origin", "")
        result = calculate_zones(origin, text)
        if not result:
            matches = search_station(text)
            if matches:
                result = calculate_zones(origin, matches[0][0])

        if not result:
            await _reply_not_found(update.message, text, lang)
            return True

        context.user_data.pop("zones_step", None)
        context.user_data.pop("zones_origin", None)
        await _send_zone_result(update.message, result, lang)
        return True

    return False


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

async def _reply_not_found(message, query_text: str, lang: str) -> None:
    """"Not found" reply, with the three closest stations as buttons."""
    suggestions = suggest_stations(query_text, limit=3)
    text = t("zones_not_found", lang).format(name=escape_md(query_text))
    if suggestions:
        text += "\n\n" + escape_md(_s("zones_suggestions", lang))
    await message.reply_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=(_suggestions_keyboard(suggestions, lang) if suggestions
                      else _cancel_keyboard(lang)),
    )


def _origin_set_text(resolved: dict, lang: str) -> str:
    """"Origin: X (zone Y)" line, tolerating stations with no Andante zone."""
    zone = resolved.get("zone") or ("fora da rede" if lang == "pt"
                                    else "outside the network")
    return t("zones_origin_set", lang).format(
        name=escape_md(resolved["name"]),
        zone=escape_md(zone),
    )


def _format_zone_result(result: dict, lang: str) -> str:
    """Render a calculation result as MarkdownV2."""
    if not result.get("covered"):
        outside = (result["dest_name"] if result.get("dest_zone") is None
                   else result["origin_name"])
        return _s("zones_outside", lang).format(name=escape_md(outside))

    title = result.get("title") or "?"
    price = result.get("price")
    day_pass = result.get("day_pass_price")

    text = t("zones_result", lang).format(
        origin=escape_md(result["origin_name"]),
        origin_zone=escape_md(result["origin_zone"] or "?"),
        dest=escape_md(result["dest_name"]),
        dest_zone=escape_md(result["dest_zone"] or "?"),
        zones_needed=escape_md(str(result.get("zones_needed") or "?")),
        price=escape_md(fares.format_price(price, lang)),
        day_pass=escape_md(fares.format_price(day_pass, lang)),
    )

    text += "\n" + _s("zones_zone_label", lang).format(title=escape_md(title))

    if not result.get("price_published"):
        text += "\n" + _s("zones_price_unpublished", lang).format(
            title=escape_md(title))

    zones_needed = result.get("zones_needed")
    if zones_needed == 1:
        text += "\n" + t("zones_tip_same", lang)
    elif zones_needed and zones_needed >= 3 and day_pass is not None:
        text += "\n" + t("zones_tip_day_pass", lang)

    origin_lower = result["origin_name"].lower()
    dest_lower = result["dest_name"].lower()
    if "aeroporto" in origin_lower or "aeroporto" in dest_lower:
        text += "\n" + t("zones_tip_airport", lang)

    if not result.get("exact"):
        text += "\n" + _s("zones_approx", lang)

    # Always show when the prices were last checked, so a stale tariff is
    # visible instead of silently wrong.
    text += "\n\n_" + escape_md(fares.verified_note(lang)) + "_"
    return text


async def _send_zone_result(message, result: dict, lang: str) -> None:
    """Send a formatted zone calculation result."""
    await message.reply_text(
        _format_zone_result(result, lang),
        parse_mode="MarkdownV2",
        reply_markup=zones_result_keyboard(
            result["origin_name"], result["dest_name"], lang
        ),
    )
