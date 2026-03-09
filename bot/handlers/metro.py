"""Metro do Porto related handlers."""

import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.config import METRO_LINES
from bot.database import is_favorite
from bot.handlers.start import _clear_awaiting
from bot.keyboards.inline import (
    metro_menu_keyboard,
    metro_lines_keyboard,
    metro_station_results_keyboard,
    metro_station_actions_keyboard,
    metro_line_actions_keyboard,
    metro_line_detail_keyboard,
    cancel_keyboard,
)
from bot.services import metro
from bot.services.metro import STATIONS
from bot.utils.formatting import escape_md, format_metro_schedule, format_metro_line_info
from bot.utils.i18n import get_lang, get_zone_display, t

logger = logging.getLogger(__name__)

AWAITING_METRO_SEARCH = "awaiting_metro_search"


async def metro_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /metro command."""
    lang = get_lang(update)
    await update.message.reply_text(
        t("metro_title", lang),
        parse_mode="MarkdownV2",
        reply_markup=metro_menu_keyboard(lang),
    )


async def station_command(update: Update,
                           context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /station <name> command."""
    lang = get_lang(update)
    if not context.args:
        await update.message.reply_text(
            t("metro_station_usage", lang),
            parse_mode="MarkdownV2",
        )
        return

    query = " ".join(context.args)
    await _search_and_show_stations(update.message, query, context, lang=lang)


async def metro_menu_callback(update: Update,
                                context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show metro menu."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)
    _clear_awaiting(context)
    context.user_data.pop("metro_back", None)
    await query.edit_message_text(
        t("metro_title", lang),
        parse_mode="MarkdownV2",
        reply_markup=metro_menu_keyboard(lang),
    )


async def metro_search_callback(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE) -> None:
    """Redirect user to inline mode for live station autocomplete."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)
    _clear_awaiting(context)
    await query.edit_message_text(
        t("metro_search_title", lang),
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t("metro_search_button", lang),
                                  switch_inline_query_current_chat="metro ")],
            [InlineKeyboardButton(t("kb_back", lang), callback_data="menu:metro")],
        ]),
    )


async def metro_lines_callback(update: Update,
                                 context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show all metro lines."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)

    all_lines = metro.get_all_lines()
    lines_text = []
    for line in all_lines:
        lines_text.append(
            f"{line['emoji']} *{escape_md(line['name'])}* "
            f"\\({escape_md(str(line['station_count']))} "
            + ("estações" if lang == "pt" else "stations")
            + "\\)\n"
            f"   📍 {escape_md(line['route'])}"
        )

    lines_joined = "\n\n".join(lines_text)
    text = t("metro_lines_title", lang).format(lines=lines_joined)

    await query.edit_message_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=metro_lines_keyboard(lang),
    )


async def metro_freq_callback(update: Update,
                                context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show frequency information for all lines."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)

    lines = []
    for code, data in METRO_LINES.items():
        freq = metro.get_frequency_info(code)
        lines.append(
            f"{data['emoji']} *{escape_md(data['name'])}*\n"
            f"   {t('metro_peak', lang)}: {escape_md(freq['peak'])}\n"
            f"   {t('metro_offpeak', lang)}: {escape_md(freq['off_peak'])}\n"
            f"   {t('metro_weekend', lang)}: {escape_md(freq['weekend'])}"
        )

    text = (
        t("metro_freq_title", lang) + "\n\n"
        + "\n\n".join(lines)
        + f"\n\n{t('metro_schedule', lang)} {escape_md('06:00 - 01:00')}"
    )

    await query.edit_message_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=metro_menu_keyboard(lang),
    )


async def metro_line_callback(update: Update,
                                context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show line details with stations."""
    query = update.callback_query
    lang = get_lang(update)
    await query.answer(t("loading", lang))

    line_code = query.data.split(":")[-1]
    try:
        line_data = METRO_LINES.get(line_code)
        if not line_data:
            await query.edit_message_text(
                t("metro_line_not_found", lang),
                parse_mode="MarkdownV2",
                reply_markup=metro_lines_keyboard(lang),
            )
            return

        stations = metro.get_line_stations(line_code)
        text = format_metro_line_info(line_code, line_data, stations,
                                      stations_data=STATIONS)
        tap_hint = "_Toca numa estação para ver horários_" if lang == "pt" else "_Tap a station to see schedules_"
        text += "\n\n" + tap_hint

        # Remember where to go back from station detail
        context.user_data["metro_back"] = f"metro:line:{line_code}"

        await query.edit_message_text(
            text,
            parse_mode="MarkdownV2",
            reply_markup=metro_line_detail_keyboard(line_code, stations,
                                                     stations_data=STATIONS,
                                                     lang=lang),
        )
    except Exception:
        logger.exception("Error in metro_line_callback for %s", line_code)
        await query.edit_message_text(
            t("error_load_metro_line", lang),
            parse_mode="MarkdownV2",
            reply_markup=metro_lines_keyboard(lang),
        )


async def metro_line_freq_callback(update: Update,
                                     context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show frequency for a specific line."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)

    line_code = query.data.split(":")[-1]
    line_data = METRO_LINES.get(line_code, {})
    freq = metro.get_frequency_info(line_code)

    text = (
        f"{line_data.get('emoji', '🚇')} *{escape_md(line_data.get('name', f'Linha {line_code}'))}*\n\n"
        f"{t('metro_peak_hours', lang)}\n   {escape_md(freq['peak'])}\n\n"
        f"{t('metro_offpeak', lang)}:\n   {escape_md(freq['off_peak'])}\n\n"
        f"{t('metro_weekend', lang)}:\n   {escape_md(freq['weekend'])}\n\n"
        f"{t('metro_schedule', lang)}\n   {escape_md(freq['hours'])}"
    )

    await query.edit_message_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=metro_line_actions_keyboard(line_code, lang=lang),
    )


def _build_station_text(station_name: str, departures: list[dict],
                        lang: str) -> str:
    """Build the formatted text for a metro station's departures."""
    station_data = metro.STATIONS.get(station_name, {})
    lines_info = []
    for lc in station_data.get("lines", []):
        ld = METRO_LINES.get(lc, {})
        lines_info.append(f"{ld.get('emoji', '🚇')} {ld.get('name', lc)}")
    line_info_str = " \\| ".join(escape_md(l) for l in lines_info) if lines_info else ""

    text = format_metro_schedule(station_name, line_info_str, departures)

    # Add zone info if available
    zone = station_data.get("zone", "")
    if zone:
        zone_display = get_zone_display(zone)
        text += f"\n\n{t('zone_info', lang).format(zone=escape_md(zone_display))}"

    has_realtime = departures and departures[0].get("realtime")
    if has_realtime:
        text += f"\n\n{t('metro_realtime_note', lang)}"
    elif departures and departures[0].get("estimated"):
        text += f"\n\n{t('metro_estimated_warning', lang)}"
    elif departures and not departures[0].get("estimated") and departures[0].get("line"):
        text += f"\n\n{t('metro_scheduled_note', lang)}"

    # Night service suggestion when metro is closed
    if departures and departures[0].get("direction") == "Serviço encerrado":
        text = t("metro_closed", lang)

    return text


async def metro_station_callback(update: Update,
                                   context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show station departures via MOTIS API (schedule-based, ~1-2s)."""
    query = update.callback_query
    lang = get_lang(update)
    await query.answer(t("loading", lang))

    station_name = query.data.split(":", 2)[-1]
    try:
        user_id = query.from_user.id
        is_fav = await is_favorite(user_id, "metro", station_name)
        # Try MOTIS API first (fast ~1-2s), fallback to local GTFS/estimate
        departures = await metro.get_next_departures_async(station_name)

        text = _build_station_text(station_name, departures, lang)

        back_cb = context.user_data.get("metro_back", "menu:metro")
        try:
            await query.edit_message_text(
                text,
                parse_mode="MarkdownV2",
                reply_markup=metro_station_actions_keyboard(
                    station_name, is_fav=is_fav, lang=lang,
                    back_callback=back_cb,
                ),
            )
        except Exception as edit_err:
            if "Message is not modified" in str(edit_err):
                pass  # Content unchanged, ignore
            else:
                raise

        # Onboarding tip for first-time users
        if not context.user_data.get("onboarded"):
            context.user_data["onboarded"] = True
            from bot.database import set_user_onboarded
            await set_user_onboarded(user_id)
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=t("tip_direct_search", lang),
                parse_mode="MarkdownV2",
            )
    except Exception:
        logger.exception("Error in metro_station_callback for %s", station_name)
        await query.edit_message_text(
            t("error_load_station", lang).format(name=escape_md(station_name)),
            parse_mode="MarkdownV2",
            reply_markup=metro_menu_keyboard(lang),
        )


async def metro_station_realtime_callback(update: Update,
                                           context: ContextTypes.DEFAULT_TYPE) -> None:
    """Alias — kept for backwards compat with metro:realtime: callback data."""
    return await metro_station_callback(update, context)


async def metro_station_lines_callback(update: Update,
                                         context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show lines for a specific station."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)

    station_name = query.data.split(":", 2)[-1]
    user_id = query.from_user.id
    is_fav = await is_favorite(user_id, "metro", station_name)
    lines = metro.get_station_lines(station_name)

    if not lines:
        await query.edit_message_text(
            t("station_not_found", lang).format(name=escape_md(station_name)),
            parse_mode="MarkdownV2",
            reply_markup=metro_menu_keyboard(lang),
        )
        return

    lines_text = []
    for line in lines:
        lines_text.append(
            f"{line['emoji']} *{escape_md(line['name'])}*\n"
            f"   📍 {escape_md(line['route'])}"
        )

    text = f"🚇 *{escape_md(station_name)}*\n\n" + "\n\n".join(lines_text)

    await query.edit_message_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=metro_station_actions_keyboard(station_name, is_fav=is_fav, lang=lang),
    )


async def metro_location_callback(update: Update,
                                     context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send station location on the map."""
    query = update.callback_query
    lang = get_lang(update)
    await query.answer(t("loading_location", lang))

    station_name = query.data.split(":", 2)[-1]
    try:
        user_id = query.from_user.id
        is_fav = await is_favorite(user_id, "metro", station_name)
        await query.edit_message_reply_markup(reply_markup=None)
        coords = metro.get_station_coordinates(station_name)
        if coords:
            await context.bot.send_location(
                chat_id=query.message.chat_id,
                latitude=coords["lat"],
                longitude=coords["lon"],
            )
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"📍 *{escape_md(station_name)}*",
                parse_mode="MarkdownV2",
                reply_markup=metro_station_actions_keyboard(station_name, is_fav=is_fav, lang=lang),
            )
        else:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=t("location_unavailable", lang).format(id=escape_md(station_name)),
                parse_mode="MarkdownV2",
            )
    except Exception:
        logger.exception("Error sending metro location for %s", station_name)
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=t("error_location", lang),
            parse_mode="MarkdownV2",
        )


async def handle_metro_text_input(update: Update,
                                    context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle text input for metro search. Returns True if handled."""
    ts = context.user_data.get(AWAITING_METRO_SEARCH)
    lang = get_lang(update)
    if ts and isinstance(ts, datetime) and (datetime.now() - ts).total_seconds() < 300:
        context.user_data.pop(AWAITING_METRO_SEARCH, None)
        query = update.message.text.strip()
        await _search_and_show_stations(update.message, query, context, lang=lang)
        return True
    elif ts is True:
        # Legacy boolean flag
        context.user_data.pop(AWAITING_METRO_SEARCH, None)
        query = update.message.text.strip()
        await _search_and_show_stations(update.message, query, context, lang=lang)
        return True
    # Clear expired flag
    context.user_data.pop(AWAITING_METRO_SEARCH, None)
    return False


async def _search_and_show_stations(message, query: str, context=None, lang: str = "pt") -> None:
    """Search for stations and show results."""
    stations = metro.search_stations(query)

    if not stations:
        await message.reply_text(
            t("no_stations_found", lang).format(query=escape_md(query)),
            parse_mode="MarkdownV2",
            reply_markup=metro_menu_keyboard(lang),
        )
        return

    if len(stations) == 1:
        # Single result - show departures directly
        station = stations[0]
        departures = await metro.get_next_departures_async(station["name"])

        lines_info = []
        for l in station["lines"]:
            lines_info.append(f"{l['emoji']} {l['name']}")
        line_info_str = " \\| ".join(escape_md(li) for li in lines_info)

        text = format_metro_schedule(station["name"], line_info_str, departures)
        has_realtime = departures and departures[0].get("realtime")
        if has_realtime:
            text += f"\n\n{t('metro_realtime_note', lang)}"
        elif departures and departures[0].get("estimated"):
            text += f"\n\n{t('metro_estimated_warning', lang)}"
        elif departures and not departures[0].get("estimated") and departures[0].get("line"):
            text += f"\n\n{t('metro_scheduled_note', lang)}"

        # Night service suggestion
        if departures and departures[0].get("direction") == "Serviço encerrado":
            text = t("metro_closed", lang)

        user_id = message.from_user.id if message.from_user else None
        is_fav = await is_favorite(user_id, "metro", station["name"]) if user_id else False
        await message.reply_text(
            text,
            parse_mode="MarkdownV2",
            reply_markup=metro_station_actions_keyboard(station["name"], is_fav=is_fav, lang=lang),
        )

        # Onboarding tip for first-time users
        if context and not context.user_data.get("onboarded"):
            context.user_data["onboarded"] = True
            user_id = message.from_user.id if message.from_user else None
            if user_id:
                from bot.database import set_user_onboarded
                await set_user_onboarded(user_id)
            await message.reply_text(
                t("tip_direct_search", lang),
                parse_mode="MarkdownV2",
            )
        return

    await message.reply_text(
        t("metro_results_for", lang).format(query=escape_md(query)),
        parse_mode="MarkdownV2",
        reply_markup=metro_station_results_keyboard(stations, lang=lang),
    )
