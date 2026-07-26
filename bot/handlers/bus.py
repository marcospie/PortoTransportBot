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
from bot.database import is_favorite
from bot.handlers.start import _clear_awaiting
from bot.services import stcp
from bot.utils.formatting import escape_md, format_bus_arrivals
from bot.utils.i18n import get_lang, get_zone_display, t

logger = logging.getLogger(__name__)

# Conversation state keys (unified)
AWAITING_BUS_FIND = "awaiting_bus_find"
# Legacy keys kept for cleanup
AWAITING_BUS_SEARCH = "awaiting_bus_search"
AWAITING_BUS_CODE = "awaiting_bus_code"


async def bus_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /bus command."""
    lang = get_lang(update)
    await update.message.reply_text(
        t("bus_title", lang),
        parse_mode="MarkdownV2",
        reply_markup=bus_menu_keyboard(lang),
    )


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /stop <code> command for quick stop lookup."""
    lang = get_lang(update)
    if not context.args:
        await update.message.reply_text(
            t("bus_stop_usage", lang),
            parse_mode="MarkdownV2",
        )
        return

    stop_id = context.args[0].upper()
    await _send_stop_realtime(update.message, stop_id, context, lang=lang)


async def bus_menu_callback(update: Update,
                             context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show bus menu."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)
    _clear_awaiting(context)
    context.user_data.pop("bus_routes", None)
    context.user_data.pop("bus_back", None)
    await safe_edit_message(
        query, t("bus_title", lang),
        reply_markup=bus_menu_keyboard(lang),
    )


async def bus_find_callback(update: Update,
                             context: ContextTypes.DEFAULT_TYPE) -> None:
    """Redirect user to inline mode for live bus stop autocomplete."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)
    _clear_awaiting(context)
    await safe_edit_message(
        query, t("bus_find_title", lang),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t("bus_find_button", lang),
                                  switch_inline_query_current_chat="bus ")],
            [InlineKeyboardButton(t("kb_back", lang), callback_data="menu:bus")],
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
    lang = get_lang(update)
    _clear_awaiting(context)
    await safe_edit_message(
        query, t("bus_code_title", lang),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t("bus_code_button", lang),
                                  switch_inline_query_current_chat="bus ")],
            [InlineKeyboardButton(t("kb_back", lang), callback_data="menu:bus")],
        ]),
    )


async def bus_routes_callback(update: Update,
                               context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show list of bus routes."""
    query = update.callback_query
    lang = get_lang(update)
    await query.answer(t("loading_lines", lang))

    routes = await stcp.get_routes()
    if not routes:
        await safe_edit_message(
            query, t("error_load_lines", lang),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(t("retry", lang), callback_data="bus:routes")],
                [InlineKeyboardButton(t("kb_back", lang), callback_data="menu:bus")],
            ]),
        )
        return

    # Store routes in user_data for pagination
    context.user_data["bus_routes"] = routes
    await safe_edit_message(
        query, t("bus_lines_title", lang).format(count=escape_md(str(len(routes)))),
        reply_markup=bus_routes_keyboard(routes, page=0, lang=lang),
    )


async def bus_routes_page_callback(update: Update,
                                    context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle route list pagination."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)

    page = int(query.data.split(":")[-1])
    routes = context.user_data.get("bus_routes", [])
    if not routes:
        routes = await stcp.get_routes()
        context.user_data["bus_routes"] = routes

    await safe_edit_message(
        query, t("bus_lines_title", lang).format(count=escape_md(str(len(routes)))),
        reply_markup=bus_routes_keyboard(routes, page=page, lang=lang),
    )


async def bus_stop_callback(update: Update,
                             context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show real-time arrivals for a specific stop."""
    query = update.callback_query
    lang = get_lang(update)
    await query.answer(t("loading", lang))

    stop_id = query.data.split(":")[-1]
    try:
        user_id = query.from_user.id
        is_fav = await is_favorite(user_id, "bus", stop_id)
        data = await stcp.get_stop_real_time(stop_id)
        text = format_bus_arrivals(
            stop_id, data["stop_name"], data["arrivals"],
        )
        back_cb = context.user_data.get("bus_back", "menu:bus")
        try:
            await safe_edit_message(
                query, text,
                reply_markup=bus_stop_actions_keyboard(stop_id, is_fav=is_fav, lang=lang, back_callback=back_cb),
            )
        except Exception as edit_err:
            if "Message is not modified" in str(edit_err):
                pass
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
        logger.exception("Error in bus_stop_callback for %s", stop_id)
        await safe_edit_message(
            query, t("error_load_stop", lang).format(stop_id=escape_md(stop_id)),
            reply_markup=bus_menu_keyboard(lang),
        )


async def bus_stop_info_callback(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show detailed stop information."""
    query = update.callback_query
    lang = get_lang(update)
    await query.answer(t("loading", lang))

    stop_id = query.data.split(":")[-1]
    user_id = query.from_user.id
    is_fav = await is_favorite(user_id, "bus", stop_id)
    info = await stcp.get_stop_info(stop_id)

    lines = [
        f"🚏 *{escape_md(info['name'])}* \\(`{escape_md(stop_id)}`\\)\n",
    ]
    if info.get("zone"):
        zone_display = get_zone_display(info['zone'])
        lines.append(t("zone_info", lang).format(zone=escape_md(zone_display)))
    # Raw latitude/longitude was printed here as hardcoded Portuguese noise.
    # The keyboard already has a Map button, which is what a user can act on.

    if info["routes"]:
        lines.append(t("bus_routes_serving", lang))
        for route in info["routes"]:
            lines.append(f"  • *{escape_md(route['number'])}* \\- {escape_md(route['name'])}")

    await safe_edit_message(
        query, "\n".join(lines),
        reply_markup=bus_stop_actions_keyboard(stop_id, is_fav=is_fav, lang=lang),
    )


async def bus_route_callback(update: Update,
                              context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show route information."""
    query = update.callback_query
    lang = get_lang(update)
    await query.answer(t("loading", lang))

    route_num = query.data.split(":")[-1]
    try:
        # Get route stops for direction 0
        stops = await stcp.get_route_stops(route_num, direction=0)

        if not stops:
            await safe_edit_message(
                query, t("error_load_line", lang).format(route=escape_md(route_num)),
                reply_markup=bus_menu_keyboard(lang),
            )
            return

        lines = [
            t("bus_line_title", lang).format(route=escape_md(route_num)),
            t("bus_line_stops", lang).format(count=escape_md(str(len(stops)))),
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
                t("bus_line_title", lang).format(route=escape_md(route_num)),
                t("bus_line_stops_short", lang).format(count=escape_md(str(len(stops)))),
                f"🔴 {escape_md(stops[0]['name'])} \\(`{escape_md(stops[0]['stop_id'])}`\\)",
            ]
            for stop in stops[1:3]:
                lines.append(f"⚪ {escape_md(stop['name'])}")
            lines.append(t("bus_stops_more", lang).format(count=escape_md(str(len(stops) - 4))))
            for stop in stops[-2:]:
                lines.append(f"⚪ {escape_md(stop['name'])}")
            lines.append(f"🔴 {escape_md(stops[-1]['name'])} \\(`{escape_md(stops[-1]['stop_id'])}`\\)")
            text = "\n".join(lines)

        await safe_edit_message(
            query, text,
            reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t("kb_back", lang), callback_data="bus:routes")],
            ]),
        )
    except Exception:
        logger.exception("Error in bus_route_callback for %s", route_num)
        await safe_edit_message(
            query, t("error_load_line2", lang).format(route=escape_md(route_num)),
            reply_markup=bus_menu_keyboard(lang),
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

    lang = get_lang(update)

    # Auto-detect: if short text with digits, treat as stop code
    if len(text) <= 6 and any(c.isdigit() for c in text):
        stop_id = text.upper()
        await _send_stop_realtime(update.message, stop_id, context, lang=lang)
    else:
        await _search_and_show_stops(update.message, text, context, lang=lang)

    return True


async def _search_and_show_stops(message, query: str, context=None, lang: str = "pt") -> None:
    """Search for stops and show results."""
    stops = await stcp.search_stops(query)

    if not stops:
        await message.reply_text(
            t("no_stops_found", lang).format(query=escape_md(query)),
            parse_mode="MarkdownV2",
            reply_markup=bus_menu_keyboard(lang),
        )
        return

    await message.reply_text(
        t("results_for", lang).format(query=escape_md(query)),
        parse_mode="MarkdownV2",
        reply_markup=bus_stop_results_keyboard(stops, lang=lang),
    )


async def bus_location_callback(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send stop location on the map."""
    query = update.callback_query
    lang = get_lang(update)
    await query.answer(t("loading_location", lang))

    stop_id = query.data.split(":")[-1]
    try:
        user_id = query.from_user.id
        is_fav = await is_favorite(user_id, "bus", stop_id)
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
                reply_markup=bus_stop_actions_keyboard(stop_id, is_fav=is_fav, lang=lang),
            )
        else:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=t("location_unavailable", lang).format(id=escape_md(stop_id)),
                parse_mode="MarkdownV2",
            )
    except Exception:
        logger.exception("Error sending bus stop location for %s", stop_id)
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=t("error_location", lang),
            parse_mode="MarkdownV2",
        )


async def _send_stop_realtime(message, stop_id: str, context=None, lang: str = "pt") -> None:
    """Fetch and send real-time data for a stop."""
    data = await stcp.get_stop_real_time(stop_id)

    if not data["arrivals"] and data["stop_name"] == stop_id:
        await message.reply_text(
            t("stop_not_found", lang).format(stop_id=escape_md(stop_id)),
            parse_mode="MarkdownV2",
            reply_markup=bus_menu_keyboard(lang),
        )
        return

    text = format_bus_arrivals(stop_id, data["stop_name"], data["arrivals"])
    user_id = message.from_user.id if message.from_user else None
    is_fav = await is_favorite(user_id, "bus", stop_id) if user_id else False
    await message.reply_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=bus_stop_actions_keyboard(stop_id, is_fav=is_fav, lang=lang),
    )

    # Onboarding tip for first-time users
    if context and not context.user_data.get("onboarded"):
        context.user_data["onboarded"] = True
        if user_id:
            from bot.database import set_user_onboarded
            await set_user_onboarded(user_id)
        await message.reply_text(
            t("tip_direct_search", lang),
            parse_mode="MarkdownV2",
        )
