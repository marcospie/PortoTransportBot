"""CP Comboios (trains) related handlers."""

import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.database import is_favorite
from bot.handlers.start import _clear_awaiting
from bot.keyboards.inline import (
    trains_menu_keyboard,
    train_station_results_keyboard,
    train_station_actions_keyboard,
    train_lines_keyboard,
)
from bot.services import cp
from bot.services.cp import CP_LINES, STATIONS
from bot.utils.formatting import escape_md, format_metro_schedule
from bot.utils.i18n import get_lang, t

logger = logging.getLogger(__name__)

AWAITING_TRAIN_SEARCH = "awaiting_train_search"


async def trains_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /comboios command."""
    lang = get_lang(update)
    await update.message.reply_text(
        t("trains_title", lang),
        parse_mode="MarkdownV2",
        reply_markup=trains_menu_keyboard(lang),
    )


async def estacao_command(update: Update,
                          context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /estacao <name> command for quick station lookup."""
    lang = get_lang(update)
    if not context.args:
        await update.message.reply_text(
            t("trains_station_usage", lang),
            parse_mode="MarkdownV2",
        )
        return

    query = " ".join(context.args)
    await _search_and_show_stations(update.message, query, context, lang=lang)


async def trains_menu_callback(update: Update,
                                context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show trains menu."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)
    _clear_awaiting(context)
    await query.edit_message_text(
        t("trains_title", lang),
        parse_mode="MarkdownV2",
        reply_markup=trains_menu_keyboard(lang),
    )


async def train_search_callback(update: Update,
                                 context: ContextTypes.DEFAULT_TYPE) -> None:
    """Redirect user to inline mode for live station autocomplete."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)
    _clear_awaiting(context)
    await query.edit_message_text(
        t("trains_search_title", lang),
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t("trains_search_button", lang),
                                  switch_inline_query_current_chat="train ")],
            [InlineKeyboardButton(t("kb_back", lang), callback_data="menu:trains")],
        ]),
    )


async def train_lines_callback(update: Update,
                                context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show all CP train lines."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)

    all_lines = cp.get_all_lines()
    lines_text = []
    for line in all_lines:
        type_label = f"\\({escape_md(line['type'])}\\)"
        lines_text.append(
            f"{line['emoji']} *{escape_md(line['name'])}* {type_label}\n"
            f"   \U0001f4cd {escape_md(line['route'])}\n"
            f"   \\({escape_md(str(line['station_count']))} "
            + ("estacoes" if lang == "pt" else "stations")
            + "\\)"
        )

    lines_joined = "\n\n".join(lines_text)
    text = t("trains_lines_title", lang).format(lines=lines_joined)

    await query.edit_message_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=train_lines_keyboard(lang),
    )


async def train_line_callback(update: Update,
                               context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show line details with stations."""
    query = update.callback_query
    lang = get_lang(update)
    await query.answer(t("loading", lang))

    line_id = query.data.split(":")[-1]
    try:
        line_data = CP_LINES.get(line_id)
        if not line_data:
            await query.edit_message_text(
                t("trains_line_not_found", lang),
                parse_mode="MarkdownV2",
                reply_markup=train_lines_keyboard(lang),
            )
            return

        stations = cp.get_line_stations(line_id)
        emoji = line_data.get("emoji", "\U0001f686")
        name = line_data.get("name", line_id)
        route = line_data.get("route", "")
        line_type = line_data.get("type", "")

        lines = [f"{emoji} *{escape_md(name)}*"]
        if route:
            lines.append(f"_{escape_md(route)}_")
        if line_type:
            lines.append(f"Tipo: {escape_md(line_type)}\n")

        for i, station_name in enumerate(stations):
            escaped_name = escape_md(station_name)
            if i == 0 or i == len(stations) - 1:
                lines.append(f"  {emoji} *{escaped_name}*")
            else:
                lines.append(f"  {emoji} {escaped_name}")
            if i < len(stations) - 1:
                lines.append("  \u2502")

        lines.append(f"\n\U0001f4ca {len(stations)} " + ("estacoes" if lang == "pt" else "stations"))

        text = "\n".join(lines)
        if len(text) > 4000:
            text = text[:3950] + "\n\n\\.\\.\\. _\\(lista truncada\\)_"

        # Build keyboard with key stations
        buttons = []
        key_stations = []
        if stations:
            key_stations.append(stations[0])
            if len(stations) > 2:
                mid = len(stations) // 2
                key_stations.append(stations[mid])
            if stations[-1] not in key_stations:
                key_stations.append(stations[-1])

        row = []
        for sname in key_stations[:6]:
            label = f"{emoji} {sname}"
            if len(label) > 40:
                label = f"{emoji} {sname[:32]}..."
            cb_data = f"train:station:{sname}"
            if len(cb_data.encode("utf-8")) <= 64:
                row.append(InlineKeyboardButton(label, callback_data=cb_data))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)

        buttons.append([InlineKeyboardButton(t("kb_back", lang), callback_data="train:lines")])

        await query.edit_message_text(
            text,
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
    except Exception:
        logger.exception("Error in train_line_callback for %s", line_id)
        await query.edit_message_text(
            t("error_load_train_line", lang),
            parse_mode="MarkdownV2",
            reply_markup=train_lines_keyboard(lang),
        )


async def train_station_callback(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show station departures."""
    query = update.callback_query
    lang = get_lang(update)
    await query.answer(t("loading", lang))

    station_name = query.data.split(":", 2)[-1]
    try:
        user_id = query.from_user.id
        is_fav = await is_favorite(user_id, "train", station_name)
        departures = cp.get_next_departures(station_name)

        station_data = STATIONS.get(station_name, {})
        lines_info = []
        for lid in station_data.get("lines", []):
            ld = CP_LINES.get(lid, {})
            train_emoji = ld.get('emoji', '\U0001f686')
            train_name = ld.get('name', lid)
            lines_info.append(f"{train_emoji} {train_name}")
        line_info_str = " \\| ".join(escape_md(l) for l in lines_info) if lines_info else ""

        text = format_metro_schedule(station_name, line_info_str, departures)
        # Replace metro emoji with train emoji in header
        text = text.replace("\U0001f687 *", "\U0001f686 *", 1)

        if departures and departures[0].get("estimated"):
            text += f"\n\n{t('trains_estimated_warning', lang)}"

        if departures and departures[0].get("direction") == "Servi\u00e7o encerrado":
            text = (
                "\U0001f31a *Servi\u00e7o encerrado*\n\n"
                f"Os comboios funcionam das "
                f"{escape_md(cp.OPERATING_HOURS['start'].strftime('%H:%M'))} "
                f"\u00e0s {escape_md(cp.OPERATING_HOURS['end'].strftime('%H:%M'))}\\."
            )

        back_cb = context.user_data.get("train_back", "menu:trains")
        await query.edit_message_text(
            text,
            parse_mode="MarkdownV2",
            reply_markup=train_station_actions_keyboard(station_name, is_fav=is_fav, lang=lang, back_callback=back_cb),
        )
    except Exception:
        logger.exception("Error in train_station_callback for %s", station_name)
        await query.edit_message_text(
            t("error_load_train_station", lang).format(name=escape_md(station_name)),
            parse_mode="MarkdownV2",
            reply_markup=trains_menu_keyboard(lang),
        )


async def train_station_lines_callback(update: Update,
                                        context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show lines for a specific station."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)

    station_name = query.data.split(":", 2)[-1]
    user_id = query.from_user.id
    is_fav = await is_favorite(user_id, "train", station_name)
    info = cp.get_station_info(station_name)

    if not info:
        await query.edit_message_text(
            t("train_station_not_found", lang).format(name=escape_md(station_name)),
            parse_mode="MarkdownV2",
            reply_markup=trains_menu_keyboard(lang),
        )
        return

    lines_text = []
    for line in info["lines"]:
        lines_text.append(
            f"{line['emoji']} *{escape_md(line['name'])}*\n"
            f"   \U0001f4cd {escape_md(line['route'])}\n"
            f"   Tipo: {escape_md(line['type'])}"
        )

    text = f"\U0001f686 *{escape_md(info['name'])}*\n\n" + "\n\n".join(lines_text)

    await query.edit_message_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=train_station_actions_keyboard(station_name, is_fav=is_fav, lang=lang),
    )


async def train_location_callback(update: Update,
                                   context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send station location on the map."""
    query = update.callback_query
    lang = get_lang(update)
    await query.answer(t("loading_location", lang))

    station_name = query.data.split(":", 2)[-1]
    try:
        user_id = query.from_user.id
        is_fav = await is_favorite(user_id, "train", station_name)
        await query.edit_message_reply_markup(reply_markup=None)
        info = cp.get_station_info(station_name)
        if info and info.get("lat") and info.get("lon"):
            await context.bot.send_location(
                chat_id=query.message.chat_id,
                latitude=info["lat"],
                longitude=info["lon"],
            )
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"\U0001f4cd *{escape_md(station_name)}*",
                parse_mode="MarkdownV2",
                reply_markup=train_station_actions_keyboard(station_name, is_fav=is_fav, lang=lang),
            )
        else:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=t("location_unavailable", lang).format(id=escape_md(station_name)),
                parse_mode="MarkdownV2",
            )
    except Exception:
        logger.exception("Error sending train station location for %s", station_name)
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=t("error_location", lang),
            parse_mode="MarkdownV2",
        )


async def handle_train_text_input(update: Update,
                                   context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle text input for train station search. Returns True if handled."""
    ts = context.user_data.get(AWAITING_TRAIN_SEARCH)
    lang = get_lang(update)
    if ts and isinstance(ts, datetime) and (datetime.now() - ts).total_seconds() < 300:
        context.user_data.pop(AWAITING_TRAIN_SEARCH, None)
        query = update.message.text.strip()
        await _search_and_show_stations(update.message, query, context, lang=lang)
        return True
    elif ts is True:
        context.user_data.pop(AWAITING_TRAIN_SEARCH, None)
        query = update.message.text.strip()
        await _search_and_show_stations(update.message, query, context, lang=lang)
        return True
    context.user_data.pop(AWAITING_TRAIN_SEARCH, None)
    return False


async def _search_and_show_stations(message, query: str, context=None, lang: str = "pt") -> None:
    """Search for CP stations and show results."""
    stations = cp.search_stations(query)

    if not stations:
        await message.reply_text(
            t("no_train_stations_found", lang).format(query=escape_md(query)),
            parse_mode="MarkdownV2",
            reply_markup=trains_menu_keyboard(lang),
        )
        return

    if len(stations) == 1:
        station = stations[0]
        departures = cp.get_next_departures(station["name"])

        lines_info = []
        for l in station["lines"]:
            lines_info.append(f"{l['emoji']} {l['name']}")
        line_info_str = " \\| ".join(escape_md(li) for li in lines_info)

        text = format_metro_schedule(station["name"], line_info_str, departures)
        text = text.replace("\U0001f687 *", "\U0001f686 *", 1)

        if departures and departures[0].get("estimated"):
            text += f"\n\n{t('trains_estimated_warning', lang)}"

        user_id = message.from_user.id if message.from_user else None
        is_fav = await is_favorite(user_id, "train", station["name"]) if user_id else False
        await message.reply_text(
            text,
            parse_mode="MarkdownV2",
            reply_markup=train_station_actions_keyboard(station["name"], is_fav=is_fav, lang=lang),
        )
        return

    await message.reply_text(
        t("trains_results_for", lang).format(query=escape_md(query)),
        parse_mode="MarkdownV2",
        reply_markup=train_station_results_keyboard(stations, lang=lang),
    )
