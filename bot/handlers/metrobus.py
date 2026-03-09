"""MetroBus (BRT) related handlers."""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.keyboards.inline import (
    metrobus_menu_keyboard,
    metrobus_lines_keyboard,
    metrobus_stop_results_keyboard,
    metrobus_stop_actions_keyboard,
)
from bot.services import metrobus
from bot.services.metrobus import STOPS, METROBUS_LINES
from bot.utils.formatting import escape_md, format_metrobus_schedule, format_metrobus_line_info
from bot.utils.i18n import get_lang, get_zone_display, t

logger = logging.getLogger(__name__)


async def metrobus_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /metrobus command."""
    lang = get_lang(update)
    await update.message.reply_text(
        t("metrobus_title", lang),
        parse_mode="MarkdownV2",
        reply_markup=metrobus_menu_keyboard(lang),
    )


async def metrobus_menu_callback(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show metrobus menu."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)
    context.user_data.pop("metrobus_back", None)
    await query.edit_message_text(
        t("metrobus_title", lang),
        parse_mode="MarkdownV2",
        reply_markup=metrobus_menu_keyboard(lang),
    )


async def metrobus_search_callback(update: Update,
                                    context: ContextTypes.DEFAULT_TYPE) -> None:
    """Redirect user to inline mode for live stop autocomplete."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    await query.edit_message_text(
        t("metrobus_search_title", lang),
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t("metrobus_search_button", lang),
                                  switch_inline_query_current_chat="metrobus ")],
            [InlineKeyboardButton(t("kb_back", lang), callback_data="menu:metrobus")],
        ]),
    )


async def metrobus_lines_callback(update: Update,
                                    context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show all MetroBus lines."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)

    all_lines = metrobus.get_all_lines()
    lines_text = []
    for line in all_lines:
        stop_label = "paragens" if lang == "pt" else "stops"
        lines_text.append(
            f"{line['emoji']} *{escape_md(line['name'])}* "
            f"\\({escape_md(str(line['stop_count']))} {stop_label}\\)\n"
            f"   📍 {escape_md(line['route'])}"
        )

    lines_joined = "\n\n".join(lines_text)
    text = t("metrobus_lines_title", lang).format(lines=lines_joined)

    await query.edit_message_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=metrobus_lines_keyboard(lang),
    )


async def metrobus_freq_callback(update: Update,
                                   context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show frequency information for all MetroBus lines."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)

    lines = []
    for code, data in METROBUS_LINES.items():
        freq = metrobus.get_frequency_info(code)
        peak_label = t('metro_peak', lang)
        offpeak_label = t('metro_offpeak', lang)
        weekend_label = t('metro_weekend', lang)
        lines.append(
            f"{data['emoji']} *{escape_md(data['name'])}*\n"
            f"   {peak_label}: {escape_md(freq['peak'])}\n"
            f"   {offpeak_label}: {escape_md(freq['off_peak'])}\n"
            f"   {weekend_label}: {escape_md(freq['weekend'])}"
        )

    text = (
        t("metrobus_freq_title", lang) + "\n\n"
        + "\n\n".join(lines)
        + f"\n\n{t('metro_schedule', lang)} {escape_md('06:00 - 01:00')}"
    )

    await query.edit_message_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=metrobus_menu_keyboard(lang),
    )


async def metrobus_line_callback(update: Update,
                                   context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show line details with stops."""
    query = update.callback_query
    lang = get_lang(update)
    await query.answer(t("loading", lang))

    line_code = query.data.split(":")[-1]
    try:
        line_data = METROBUS_LINES.get(line_code)
        if not line_data:
            await query.edit_message_text(
                t("metrobus_line_not_found", lang),
                parse_mode="MarkdownV2",
                reply_markup=metrobus_lines_keyboard(lang),
            )
            return

        stops = metrobus.get_line_stops(line_code)
        text = format_metrobus_line_info(line_code, line_data, stops,
                                          stops_data=STOPS)

        tap_hint = "_Toca numa paragem para ver horários_" if lang == "pt" else "_Tap a stop to see schedules_"
        text += "\n\n" + tap_hint

        # Build keyboard with stops
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        buttons = []
        emoji = line_data.get("emoji", "\U0001f68d")
        row = []
        # Show first, last, and a few middle stops
        key_stops = []
        if stops:
            key_stops.append(stops[0])
            mid = len(stops) // 2
            if mid > 0 and stops[mid] not in key_stops:
                key_stops.append(stops[mid])
            if stops[-1] not in key_stops:
                key_stops.append(stops[-1])

        for name in key_stops[:6]:
            label = f"{emoji} {name}"
            if len(label) > 40:
                label = f"{emoji} {name[:32]}..."
            cb_data = f"metrobus:stop:{name}"
            if len(cb_data.encode("utf-8")) <= 64:
                row.append(InlineKeyboardButton(label, callback_data=cb_data))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)

        buttons.append([InlineKeyboardButton(t("kb_back", lang), callback_data="metrobus:lines")])

        await query.edit_message_text(
            text,
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
    except Exception:
        logger.exception("Error in metrobus_line_callback for %s", line_code)
        await query.edit_message_text(
            t("error_load_metrobus_line", lang),
            parse_mode="MarkdownV2",
            reply_markup=metrobus_lines_keyboard(lang),
        )


async def metrobus_stop_callback(update: Update,
                                   context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show stop departures."""
    query = update.callback_query
    lang = get_lang(update)
    await query.answer(t("loading", lang))

    stop_name = query.data.split(":", 2)[-1]
    try:
        from bot.database import is_favorite
        user_id = query.from_user.id
        is_fav = await is_favorite(user_id, "metrobus", stop_name)
        departures = metrobus.get_next_departures(stop_name)

        stop_data = STOPS.get(stop_name, {})
        lines_info = []
        for lc in stop_data.get("lines", []):
            ld = METROBUS_LINES.get(lc, {})
            default_emoji = "\U0001f68d"
            lines_info.append(f"{ld.get('emoji', default_emoji)} {ld.get('name', lc)}")
        line_info_str = " \\| ".join(escape_md(li) for li in lines_info) if lines_info else ""

        text = format_metrobus_schedule(stop_name, line_info_str, departures)

        # Add zone info
        zone = stop_data.get("zone", "")
        if zone:
            zone_display = get_zone_display(zone)
            text += f"\n\n{t('zone_info', lang).format(zone=escape_md(zone_display))}"

        if departures and departures[0].get("estimated"):
            text += f"\n\n{t('metrobus_estimated_warning', lang)}"

        if departures and departures[0].get("direction") == "Serviço encerrado":
            text = t("metrobus_closed", lang)

        back_cb = context.user_data.get("metrobus_back", "menu:metrobus")
        try:
            await query.edit_message_text(
                text,
                parse_mode="MarkdownV2",
                reply_markup=metrobus_stop_actions_keyboard(stop_name, is_fav=is_fav, lang=lang, back_callback=back_cb),
            )
        except Exception as edit_err:
            if "Message is not modified" in str(edit_err):
                pass
            else:
                raise
    except Exception:
        logger.exception("Error in metrobus_stop_callback for %s", stop_name)
        await query.edit_message_text(
            t("error_load_metrobus_stop", lang).format(name=escape_md(stop_name)),
            parse_mode="MarkdownV2",
            reply_markup=metrobus_menu_keyboard(lang),
        )


async def metrobus_stop_lines_callback(update: Update,
                                         context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show lines for a specific MetroBus stop."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)

    stop_name = query.data.split(":", 2)[-1]
    from bot.database import is_favorite
    user_id = query.from_user.id
    is_fav = await is_favorite(user_id, "metrobus", stop_name)
    stop_info = metrobus.get_stop_info(stop_name)

    if not stop_info:
        await query.edit_message_text(
            t("metrobus_stop_not_found", lang).format(name=escape_md(stop_name)),
            parse_mode="MarkdownV2",
            reply_markup=metrobus_menu_keyboard(lang),
        )
        return

    lines_text = []
    for line in stop_info["lines"]:
        lines_text.append(
            f"{line['emoji']} *{escape_md(line['name'])}*\n"
            f"   📍 {escape_md(line['route'])}"
        )

    text = f"\U0001f68d *{escape_md(stop_name)}*\n\n" + "\n\n".join(lines_text)

    await query.edit_message_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=metrobus_stop_actions_keyboard(stop_name, is_fav=is_fav, lang=lang),
    )


async def metrobus_location_callback(update: Update,
                                       context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send stop location on the map."""
    query = update.callback_query
    lang = get_lang(update)
    await query.answer(t("loading_location", lang))

    stop_name = query.data.split(":", 2)[-1]
    try:
        from bot.database import is_favorite
        user_id = query.from_user.id
        is_fav = await is_favorite(user_id, "metrobus", stop_name)
        await query.edit_message_reply_markup(reply_markup=None)
        coords = metrobus.get_stop_coordinates(stop_name)
        if coords:
            await context.bot.send_location(
                chat_id=query.message.chat_id,
                latitude=coords["lat"],
                longitude=coords["lon"],
            )
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"📍 *{escape_md(stop_name)}*",
                parse_mode="MarkdownV2",
                reply_markup=metrobus_stop_actions_keyboard(stop_name, is_fav=is_fav, lang=lang),
            )
        else:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=t("location_unavailable", lang).format(id=escape_md(stop_name)),
                parse_mode="MarkdownV2",
            )
    except Exception:
        logger.exception("Error sending metrobus location for %s", stop_name)
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=t("error_location", lang),
            parse_mode="MarkdownV2",
        )
