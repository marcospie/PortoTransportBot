"""Metro do Porto related handlers."""

import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.config import METRO_LINES
from bot.handlers.start import _clear_awaiting
from bot.keyboards.inline import (
    metro_menu_keyboard,
    metro_lines_keyboard,
    metro_station_results_keyboard,
    metro_station_actions_keyboard,
    metro_line_actions_keyboard,
    cancel_keyboard,
)
from bot.services import metro
from bot.utils.formatting import escape_md, format_metro_schedule, format_metro_line_info
from bot.utils.i18n import get_lang, get_zone_display, t

logger = logging.getLogger(__name__)

AWAITING_METRO_SEARCH = "awaiting_metro_search"


async def metro_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /metro command."""
    await update.message.reply_text(
        "🚇 *Metro do Porto*\n\nEscolhe uma opção:",
        parse_mode="MarkdownV2",
        reply_markup=metro_menu_keyboard(),
    )


async def station_command(update: Update,
                           context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /station <name> command."""
    if not context.args:
        await update.message.reply_text(
            "Uso: /station <nome>\nExemplo: `/station Trindade`",
            parse_mode="MarkdownV2",
        )
        return

    query = " ".join(context.args)
    await _search_and_show_stations(update.message, query, context)


async def metro_menu_callback(update: Update,
                                context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show metro menu."""
    query = update.callback_query
    await query.answer()
    _clear_awaiting(context)
    await query.edit_message_text(
        "🚇 *Metro do Porto*\n\nEscolhe uma opção:",
        parse_mode="MarkdownV2",
        reply_markup=metro_menu_keyboard(),
    )


async def metro_search_callback(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE) -> None:
    """Redirect user to inline mode for live station autocomplete."""
    query = update.callback_query
    await query.answer()
    _clear_awaiting(context)
    await query.edit_message_text(
        "🔍 *Pesquisar estação*\n\n"
        "Toca no botão abaixo e começa a escrever \\- "
        "as sugestões aparecem enquanto digitas\\!\n\n"
        "Exemplo: `Trind` → Trindade, `Bol` → Bolhão",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Escrever nome da estação...",
                                  switch_inline_query_current_chat="metro ")],
            [InlineKeyboardButton("🔙 Voltar", callback_data="menu:metro")],
        ]),
    )


async def metro_lines_callback(update: Update,
                                 context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show all metro lines."""
    query = update.callback_query
    await query.answer()

    all_lines = metro.get_all_lines()
    lines_text = []
    for line in all_lines:
        lines_text.append(
            f"{line['emoji']} *{escape_md(line['name'])}* "
            f"\\({escape_md(str(line['station_count']))} estações\\)\n"
            f"   📍 {escape_md(line['route'])}"
        )

    text = "🗺 *Linhas do Metro do Porto*\n\n" + "\n\n".join(lines_text)
    text += "\n\nSeleciona uma linha para mais detalhes:"

    await query.edit_message_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=metro_lines_keyboard(),
    )


async def metro_freq_callback(update: Update,
                                context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show frequency information for all lines."""
    query = update.callback_query
    await query.answer()

    lines = []
    for code, data in METRO_LINES.items():
        freq = metro.get_frequency_info(code)
        lines.append(
            f"{data['emoji']} *{escape_md(data['name'])}*\n"
            f"   🏢 Hora ponta: {escape_md(freq['peak'])}\n"
            f"   ☀️ Fora de ponta: {escape_md(freq['off_peak'])}\n"
            f"   📅 Fim\\-de\\-semana: {escape_md(freq['weekend'])}"
        )

    text = (
        "🕐 *Frequências do Metro*\n\n"
        + "\n\n".join(lines)
        + f"\n\n⏰ *Horário:* {escape_md('06:00 - 01:00')}"
    )

    await query.edit_message_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=metro_menu_keyboard(),
    )


async def metro_line_callback(update: Update,
                                context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show line details with stations."""
    query = update.callback_query
    await query.answer("A carregar...")

    line_code = query.data.split(":")[-1]
    try:
        line_data = METRO_LINES.get(line_code)
        if not line_data:
            await query.edit_message_text(
                "❌ Linha não encontrada\\.",
                parse_mode="MarkdownV2",
                reply_markup=metro_lines_keyboard(),
            )
            return

        stations = metro.get_line_stations(line_code)
        text = format_metro_line_info(line_code, line_data, stations)

        await query.edit_message_text(
            text,
            parse_mode="MarkdownV2",
            reply_markup=metro_line_actions_keyboard(line_code),
        )
    except Exception:
        logger.exception("Error in metro_line_callback for %s", line_code)
        await query.edit_message_text(
            "❌ Erro ao carregar linha\\. Tenta novamente\\.",
            parse_mode="MarkdownV2",
            reply_markup=metro_lines_keyboard(),
        )


async def metro_line_freq_callback(update: Update,
                                     context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show frequency for a specific line."""
    query = update.callback_query
    await query.answer()

    line_code = query.data.split(":")[-1]
    line_data = METRO_LINES.get(line_code, {})
    freq = metro.get_frequency_info(line_code)

    text = (
        f"{line_data.get('emoji', '🚇')} *{escape_md(line_data.get('name', f'Linha {line_code}'))}*\n\n"
        f"🏢 *Hora ponta \\(7h\\-9h, 17h\\-19h\\):*\n   {escape_md(freq['peak'])}\n\n"
        f"☀️ *Fora de ponta:*\n   {escape_md(freq['off_peak'])}\n\n"
        f"📅 *Fim\\-de\\-semana:*\n   {escape_md(freq['weekend'])}\n\n"
        f"⏰ *Horário de funcionamento:*\n   {escape_md(freq['hours'])}"
    )

    await query.edit_message_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=metro_line_actions_keyboard(line_code),
    )


async def metro_station_callback(update: Update,
                                   context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show station departures."""
    query = update.callback_query
    await query.answer("A carregar...")

    station_name = query.data.split(":", 2)[-1]
    try:
        departures = metro.get_next_departures(station_name)

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
            text += f"\n\n📍 Zona Andante: *{escape_md(zone_display)}*"

        if departures and departures[0].get("estimated"):
            text += "\n\n_⚠️ Tempos estimados com base nas frequências_"

        # Night service suggestion when metro is closed
        if departures and departures[0].get("direction") == "Serviço encerrado":
            lang = get_lang(update)
            text = t("metro_closed", lang)

        await query.edit_message_text(
            text,
            parse_mode="MarkdownV2",
            reply_markup=metro_station_actions_keyboard(station_name),
        )

        # Onboarding tip for first-time users
        if not context.user_data.get("onboarded"):
            context.user_data["onboarded"] = True
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="💡 *Dica:* Podes escrever o nome ou código de qualquer paragem diretamente no chat, sem usar o menu\\!",
                parse_mode="MarkdownV2",
            )
    except Exception:
        logger.exception("Error in metro_station_callback for %s", station_name)
        await query.edit_message_text(
            f"❌ Erro ao carregar estação *{escape_md(station_name)}*\\. Tenta novamente\\.",
            parse_mode="MarkdownV2",
            reply_markup=metro_menu_keyboard(),
        )


async def metro_station_lines_callback(update: Update,
                                         context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show lines for a specific station."""
    query = update.callback_query
    await query.answer()

    station_name = query.data.split(":", 2)[-1]
    lines = metro.get_station_lines(station_name)

    if not lines:
        await query.edit_message_text(
            f"❌ Estação *{escape_md(station_name)}* não encontrada\\.",
            parse_mode="MarkdownV2",
            reply_markup=metro_menu_keyboard(),
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
        reply_markup=metro_station_actions_keyboard(station_name),
    )


async def metro_location_callback(update: Update,
                                     context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send station location on the map."""
    query = update.callback_query
    await query.answer("A carregar localização...")

    station_name = query.data.split(":", 2)[-1]
    try:
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
                reply_markup=metro_station_actions_keyboard(station_name),
            )
        else:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"❌ Localização não disponível para *{escape_md(station_name)}*\\.",
                parse_mode="MarkdownV2",
            )
    except Exception:
        logger.exception("Error sending metro location for %s", station_name)
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="❌ Erro ao obter localização\\. Tenta novamente\\.",
            parse_mode="MarkdownV2",
        )


async def handle_metro_text_input(update: Update,
                                    context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle text input for metro search. Returns True if handled."""
    ts = context.user_data.get(AWAITING_METRO_SEARCH)
    if ts and isinstance(ts, datetime) and (datetime.now() - ts).total_seconds() < 300:
        context.user_data.pop(AWAITING_METRO_SEARCH, None)
        query = update.message.text.strip()
        await _search_and_show_stations(update.message, query, context)
        return True
    elif ts is True:
        # Legacy boolean flag
        context.user_data.pop(AWAITING_METRO_SEARCH, None)
        query = update.message.text.strip()
        await _search_and_show_stations(update.message, query, context)
        return True
    # Clear expired flag
    context.user_data.pop(AWAITING_METRO_SEARCH, None)
    return False


async def _search_and_show_stations(message, query: str, context=None) -> None:
    """Search for stations and show results."""
    stations = metro.search_stations(query)

    if not stations:
        await message.reply_text(
            f"❌ Nenhuma estação encontrada para *{escape_md(query)}*\\.\n"
            "Tenta outro nome\\.",
            parse_mode="MarkdownV2",
            reply_markup=metro_menu_keyboard(),
        )
        return

    if len(stations) == 1:
        # Single result - show departures directly
        station = stations[0]
        departures = metro.get_next_departures(station["name"])

        lines_info = []
        for l in station["lines"]:
            lines_info.append(f"{l['emoji']} {l['name']}")
        line_info_str = " \\| ".join(escape_md(li) for li in lines_info)

        text = format_metro_schedule(station["name"], line_info_str, departures)
        if departures and departures[0].get("estimated"):
            text += "\n\n_⚠️ Tempos estimados com base nas frequências_"

        # Night service suggestion
        if departures and departures[0].get("direction") == "Serviço encerrado":
            text = t("metro_closed", "pt")

        await message.reply_text(
            text,
            parse_mode="MarkdownV2",
            reply_markup=metro_station_actions_keyboard(station["name"]),
        )

        # Onboarding tip for first-time users
        if context and not context.user_data.get("onboarded"):
            context.user_data["onboarded"] = True
            await message.reply_text(
                "💡 *Dica:* Podes escrever o nome ou código de qualquer paragem diretamente no chat, sem usar o menu\\!",
                parse_mode="MarkdownV2",
            )
        return

    await message.reply_text(
        f"🔍 Resultados para *{escape_md(query)}*:\n\n"
        "Seleciona uma estação:",
        parse_mode="MarkdownV2",
        reply_markup=metro_station_results_keyboard(stations),
    )
