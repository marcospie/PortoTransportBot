"""Bus (STCP) related handlers."""

import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.keyboards.inline import (
    bus_menu_keyboard,
    bus_stop_actions_keyboard,
    bus_stop_results_keyboard,
    bus_routes_keyboard,
    cancel_keyboard,
)
from bot.handlers.start import _clear_awaiting
from bot.services import stcp
from bot.utils.formatting import escape_md, format_bus_arrivals
from bot.utils.i18n import get_zone_display

logger = logging.getLogger(__name__)

# Conversation state keys (unified)
AWAITING_BUS_FIND = "awaiting_bus_find"
# Legacy keys kept for cleanup
AWAITING_BUS_SEARCH = "awaiting_bus_search"
AWAITING_BUS_CODE = "awaiting_bus_code"


async def bus_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /bus command."""
    await update.message.reply_text(
        "🚌 *Autocarros STCP*\n\nEscolhe uma opção:",
        parse_mode="MarkdownV2",
        reply_markup=bus_menu_keyboard(),
    )


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /stop <code> command for quick stop lookup."""
    if not context.args:
        await update.message.reply_text(
            "Uso: /stop <código>\nExemplo: `/stop BCM2`",
            parse_mode="MarkdownV2",
        )
        return

    stop_id = context.args[0].upper()
    await _send_stop_realtime(update.message, stop_id, context)


async def bus_menu_callback(update: Update,
                             context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show bus menu."""
    query = update.callback_query
    await query.answer()
    _clear_awaiting(context)
    context.user_data.pop("bus_routes", None)
    await query.edit_message_text(
        "🚌 *Autocarros STCP*\n\nEscolhe uma opção:",
        parse_mode="MarkdownV2",
        reply_markup=bus_menu_keyboard(),
    )


async def bus_find_callback(update: Update,
                             context: ContextTypes.DEFAULT_TYPE) -> None:
    """Redirect user to inline mode for live bus stop autocomplete."""
    query = update.callback_query
    await query.answer()
    _clear_awaiting(context)
    await query.edit_message_text(
        "🔍 *Encontrar paragem*\n\n"
        "Toca no botão abaixo e começa a escrever \\- "
        "as sugestões aparecem enquanto digitas\\!\n\n"
        "Exemplo: `BIBG` → BIBG1, BIBG2 \\| `Casa` → Casa da Música",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Escrever nome ou código...",
                                  switch_inline_query_current_chat="bus ")],
            [InlineKeyboardButton("🔙 Voltar", callback_data="menu:bus")],
        ]),
    )


# Backwards compatibility aliases
async def bus_search_callback(update: Update,
                               context: ContextTypes.DEFAULT_TYPE) -> None:
    """Legacy handler - redirects to bus_find_callback."""
    await bus_find_callback(update, context)


async def bus_code_callback(update: Update,
                             context: ContextTypes.DEFAULT_TYPE) -> None:
    """Redirect user to inline mode for stop code autocomplete."""
    query = update.callback_query
    await query.answer()
    _clear_awaiting(context)
    await query.edit_message_text(
        "🔢 *Consultar por código*\n\n"
        "Toca no botão abaixo e escreve o código \\- "
        "as sugestões aparecem enquanto digitas\\!\n\n"
        "Exemplo: `BCM` → BCM1, BCM2 \\| `TRD` → TRD1, TRD2",
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Escrever código da paragem...",
                                  switch_inline_query_current_chat="bus ")],
            [InlineKeyboardButton("🔙 Voltar", callback_data="menu:bus")],
        ]),
    )


async def bus_routes_callback(update: Update,
                               context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show list of bus routes."""
    query = update.callback_query
    await query.answer("A carregar linhas...")

    routes = await stcp.get_routes()
    if not routes:
        await query.edit_message_text(
            "❌ Não foi possível carregar as linhas\\.\n\n"
            "O serviço STCP pode estar temporariamente indisponível\\.\n"
            "Tenta novamente em alguns minutos\\.",
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Tentar novamente", callback_data="bus:routes")],
                [InlineKeyboardButton("🔙 Voltar", callback_data="menu:bus")],
            ]),
        )
        return

    # Store routes in user_data for pagination
    context.user_data["bus_routes"] = routes
    await query.edit_message_text(
        f"🚌 *Linhas STCP* \\({escape_md(str(len(routes)))} linhas\\)\n\n"
        "Seleciona uma linha:",
        parse_mode="MarkdownV2",
        reply_markup=bus_routes_keyboard(routes, page=0),
    )


async def bus_routes_page_callback(update: Update,
                                    context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle route list pagination."""
    query = update.callback_query
    await query.answer()

    page = int(query.data.split(":")[-1])
    routes = context.user_data.get("bus_routes", [])
    if not routes:
        routes = await stcp.get_routes()
        context.user_data["bus_routes"] = routes

    await query.edit_message_text(
        f"🚌 *Linhas STCP* \\({escape_md(str(len(routes)))} linhas\\)\n\n"
        "Seleciona uma linha:",
        parse_mode="MarkdownV2",
        reply_markup=bus_routes_keyboard(routes, page=page),
    )


async def bus_stop_callback(update: Update,
                             context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show real-time arrivals for a specific stop."""
    query = update.callback_query
    await query.answer("A carregar...")

    stop_id = query.data.split(":")[-1]
    try:
        data = await stcp.get_stop_real_time(stop_id)
        text = format_bus_arrivals(
            stop_id, data["stop_name"], data["arrivals"],
        )
        await query.edit_message_text(
            text,
            parse_mode="MarkdownV2",
            reply_markup=bus_stop_actions_keyboard(stop_id),
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
        logger.exception("Error in bus_stop_callback for %s", stop_id)
        await query.edit_message_text(
            f"❌ Erro ao carregar paragem *{escape_md(stop_id)}*\\. Tenta novamente\\.",
            parse_mode="MarkdownV2",
            reply_markup=bus_menu_keyboard(),
        )


async def bus_stop_info_callback(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show detailed stop information."""
    query = update.callback_query
    await query.answer("A carregar...")

    stop_id = query.data.split(":")[-1]
    info = await stcp.get_stop_info(stop_id)

    lines = [
        f"🚏 *{escape_md(info['name'])}* \\(`{escape_md(stop_id)}`\\)\n",
    ]
    if info.get("zone"):
        zone_display = get_zone_display(info['zone'])
        lines.append(f"📍 Zona Andante: *{escape_md(zone_display)}*")
    if info.get("lat") and info.get("lon"):
        lines.append(f"🗺 Coordenadas: {info['lat']}, {info['lon']}")

    if info["routes"]:
        lines.append(f"\n🚌 *Linhas que servem esta paragem:*\n")
        for route in info["routes"]:
            lines.append(f"  • *{escape_md(route['number'])}* \\- {escape_md(route['name'])}")

    await query.edit_message_text(
        "\n".join(lines),
        parse_mode="MarkdownV2",
        reply_markup=bus_stop_actions_keyboard(stop_id),
    )


async def bus_route_callback(update: Update,
                              context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show route information."""
    query = update.callback_query
    await query.answer("A carregar...")

    route_num = query.data.split(":")[-1]
    try:
        # Get route stops for direction 0
        stops = await stcp.get_route_stops(route_num, direction=0)

        if not stops:
            await query.edit_message_text(
                f"❌ Não foi possível carregar a linha {escape_md(route_num)}\\.",
                parse_mode="MarkdownV2",
                reply_markup=bus_menu_keyboard(),
            )
            return

        lines = [
            f"🚌 *Linha {escape_md(route_num)}*\n",
            f"*Paragens \\({escape_md(str(len(stops)))}\\):*\n",
        ]

        for i, stop in enumerate(stops):
            if i == 0 or i == len(stops) - 1:
                prefix = "🔴"
            else:
                prefix = "⚪"
            lines.append(f"  {prefix} {escape_md(stop['name'])} \\(`{escape_md(stop['stop_id'])}`\\)")

        # Truncate if too long
        text = "\n".join(lines)
        if len(text) > 4000:
            lines = [
                f"🚌 *Linha {escape_md(route_num)}*\n",
                f"*{escape_md(str(len(stops)))} paragens*\n",
                f"🔴 {escape_md(stops[0]['name'])} \\(`{escape_md(stops[0]['stop_id'])}`\\)",
            ]
            for stop in stops[1:3]:
                lines.append(f"⚪ {escape_md(stop['name'])}")
            lines.append(f"  ⋮ \\.\\.\\.  {escape_md(str(len(stops) - 4))} paragens \\.\\.\\.")
            for stop in stops[-2:]:
                lines.append(f"⚪ {escape_md(stop['name'])}")
            lines.append(f"🔴 {escape_md(stops[-1]['name'])} \\(`{escape_md(stops[-1]['stop_id'])}`\\)")
            text = "\n".join(lines)

        await query.edit_message_text(
            text,
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Voltar", callback_data="bus:routes")],
            ]),
        )
    except Exception:
        logger.exception("Error in bus_route_callback for %s", route_num)
        await query.edit_message_text(
            f"❌ Erro ao carregar a linha {escape_md(route_num)}\\. Tenta novamente\\.",
            parse_mode="MarkdownV2",
            reply_markup=bus_menu_keyboard(),
        )


async def handle_bus_text_input(update: Update,
                                 context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle text input for bus find (unified search/code). Returns True if handled."""
    text = update.message.text.strip()

    # Check unified state first, then legacy states
    ts = context.user_data.get(AWAITING_BUS_FIND)
    ts_search = context.user_data.get(AWAITING_BUS_SEARCH)
    ts_code = context.user_data.get(AWAITING_BUS_CODE)

    # Check if any flag is active and not expired (5 min timeout)
    is_awaiting = False
    for flag_ts in (ts, ts_search, ts_code):
        if flag_ts is True:
            is_awaiting = True
            break
        if isinstance(flag_ts, datetime) and (datetime.now() - flag_ts).total_seconds() < 300:
            is_awaiting = True
            break

    if not is_awaiting:
        # Clear any expired flags
        context.user_data.pop(AWAITING_BUS_FIND, None)
        context.user_data.pop(AWAITING_BUS_SEARCH, None)
        context.user_data.pop(AWAITING_BUS_CODE, None)
        return False

    # Clear all awaiting flags
    context.user_data.pop(AWAITING_BUS_FIND, None)
    context.user_data.pop(AWAITING_BUS_SEARCH, None)
    context.user_data.pop(AWAITING_BUS_CODE, None)

    # Auto-detect: if short text with digits, treat as stop code
    if len(text) <= 6 and any(c.isdigit() for c in text):
        stop_id = text.upper()
        await _send_stop_realtime(update.message, stop_id, context)
    else:
        await _search_and_show_stops(update.message, text, context)

    return True


async def _search_and_show_stops(message, query: str, context=None) -> None:
    """Search for stops and show results."""
    stops = await stcp.search_stops(query)

    if not stops:
        await message.reply_text(
            f"❌ Nenhuma paragem encontrada para *{escape_md(query)}*\\.\n"
            "Tenta outro nome ou usa o código da paragem\\.",
            parse_mode="MarkdownV2",
            reply_markup=bus_menu_keyboard(),
        )
        return

    await message.reply_text(
        f"🔍 Resultados para *{escape_md(query)}*:\n\n"
        "Seleciona uma paragem:",
        parse_mode="MarkdownV2",
        reply_markup=bus_stop_results_keyboard(stops),
    )


async def bus_location_callback(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send stop location on the map."""
    query = update.callback_query
    await query.answer("A carregar localização...")

    stop_id = query.data.split(":")[-1]
    try:
        await query.edit_message_reply_markup(reply_markup=None)
        info = await stcp.get_stop_info(stop_id)
        lat = info.get("lat")
        lon = info.get("lon")
        if lat and lon:
            await context.bot.send_location(
                chat_id=query.message.chat_id,
                latitude=lat,
                longitude=lon,
            )
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"📍 *{escape_md(info.get('name', stop_id))}* \\(`{escape_md(stop_id)}`\\)",
                parse_mode="MarkdownV2",
                reply_markup=bus_stop_actions_keyboard(stop_id),
            )
        else:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"❌ Localização não disponível para *{escape_md(stop_id)}*\\.",
                parse_mode="MarkdownV2",
            )
    except Exception:
        logger.exception("Error sending bus stop location for %s", stop_id)
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="❌ Erro ao obter localização\\. Tenta novamente\\.",
            parse_mode="MarkdownV2",
        )


async def _send_stop_realtime(message, stop_id: str, context=None) -> None:
    """Fetch and send real-time data for a stop."""
    data = await stcp.get_stop_real_time(stop_id)

    if not data["arrivals"] and data["stop_name"] == stop_id:
        await message.reply_text(
            f"❌ Paragem *{escape_md(stop_id)}* não encontrada ou sem dados\\.\n"
            "Verifica o código e tenta novamente\\.",
            parse_mode="MarkdownV2",
            reply_markup=bus_menu_keyboard(),
        )
        return

    text = format_bus_arrivals(stop_id, data["stop_name"], data["arrivals"])
    await message.reply_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=bus_stop_actions_keyboard(stop_id),
    )

    # Onboarding tip for first-time users
    if context and not context.user_data.get("onboarded"):
        context.user_data["onboarded"] = True
        await message.reply_text(
            "💡 *Dica:* Podes escrever o nome ou código de qualquer paragem diretamente no chat, sem usar o menu\\!",
            parse_mode="MarkdownV2",
        )
