"""Handler for Andante Zone Calculator feature."""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.services.zones import (
    calculate_zones,
    get_zone_for_station,
    get_stations_in_zone,
    get_all_zones,
    search_station,
)
from bot.keyboards.inline import (
    zones_menu_keyboard,
    zones_result_keyboard,
    zones_map_keyboard,
    zone_detail_keyboard,
)
from bot.utils.i18n import t, get_lang
from bot.utils.formatting import escape_md

logger = logging.getLogger(__name__)


async def zones_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /zonas command."""
    lang = get_lang(update)
    args = context.args

    if args and len(args) >= 2:
        origin = args[0]
        dest = " ".join(args[1:])
        result = calculate_zones(origin, dest)
        if result:
            await _send_zone_result(update.message, result, lang)
            return

    await update.message.reply_text(
        t("zones_title", lang),
        parse_mode="MarkdownV2",
        reply_markup=zones_menu_keyboard(lang),
    )


async def zones_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show zone calculator menu."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)
    context.user_data.pop("zones_step", None)
    context.user_data.pop("zones_origin", None)
    await query.edit_message_text(
        t("zones_title", lang),
        parse_mode="MarkdownV2",
        reply_markup=zones_menu_keyboard(lang),
    )


async def zones_calculate_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start zone calculation - ask for origin."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)
    context.user_data["zones_step"] = "origin"
    await query.edit_message_text(
        t("zones_ask_origin", lang),
        parse_mode="MarkdownV2",
    )


async def zones_map_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show zone map overview."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)
    await query.edit_message_text(
        t("zones_map_title", lang),
        parse_mode="MarkdownV2",
        reply_markup=zones_map_keyboard(lang),
    )


async def zones_zone_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show stations in a specific zone."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)
    zone = query.data.split(":")[-1]
    stations = get_stations_in_zone(zone)

    if stations:
        station_list = "\n".join(f"• {escape_md(s)}" for s in stations[:20])
        if len(stations) > 20:
            station_list += f"\n_\\.\\.\\.e mais {len(stations) - 20}_"
    else:
        station_list = escape_md("Nenhuma estação nesta zona")

    text = t("zones_zone_detail", lang).format(
        zone=escape_md(zone),
        stations=station_list,
    )
    await query.edit_message_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=zone_detail_keyboard(zone, lang),
    )


async def handle_zones_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle text input during zone calculation. Returns True if handled."""
    step = context.user_data.get("zones_step")
    if not step:
        return False

    text = update.message.text.strip()
    lang = get_lang(update)

    if step == "origin":
        zone = get_zone_for_station(text)
        if not zone:
            results = search_station(text)
            if results:
                text = results[0][0]
                zone = results[0][1]

        if not zone:
            await update.message.reply_text(
                t("zones_not_found", lang).format(name=escape_md(text)),
                parse_mode="MarkdownV2",
            )
            return True

        context.user_data["zones_origin"] = text
        context.user_data["zones_step"] = "dest"
        await update.message.reply_text(
            t("zones_origin_set", lang).format(
                name=escape_md(text),
                zone=escape_md(zone),
            ) + "\n\n" + t("zones_ask_dest", lang),
            parse_mode="MarkdownV2",
        )
        return True

    elif step == "dest":
        origin = context.user_data.get("zones_origin", "")
        result = calculate_zones(origin, text)
        if not result:
            results = search_station(text)
            if results:
                result = calculate_zones(origin, results[0][0])

        if not result:
            await update.message.reply_text(
                t("zones_not_found", lang).format(name=escape_md(text)),
                parse_mode="MarkdownV2",
            )
            return True

        context.user_data.pop("zones_step", None)
        context.user_data.pop("zones_origin", None)
        await _send_zone_result(update.message, result, lang)
        return True

    return False


async def _send_zone_result(message, result: dict, lang: str) -> None:
    """Send a formatted zone calculation result."""
    text = t("zones_result", lang).format(
        origin=escape_md(result["origin_name"]),
        origin_zone=escape_md(result["origin_zone"]),
        dest=escape_md(result["dest_name"]),
        dest_zone=escape_md(result["dest_zone"]),
        zones_needed=escape_md(str(result["zones_needed"])),
        price=escape_md(f"{result['price']:.2f}€"),
        day_pass=escape_md(f"{result['day_pass_price']:.2f}€"),
    )

    if result["zones_needed"] == 1:
        text += "\n" + t("zones_tip_same", lang)
    elif result["zones_needed"] >= 3:
        text += "\n" + t("zones_tip_day_pass", lang)

    origin_lower = result["origin_name"].lower()
    dest_lower = result["dest_name"].lower()
    if "aeroporto" in origin_lower or "aeroporto" in dest_lower:
        text += "\n" + t("zones_tip_airport", lang)

    await message.reply_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=zones_result_keyboard(
            result["origin_name"], result["dest_name"], lang
        ),
    )
