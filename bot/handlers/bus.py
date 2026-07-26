"""Bus (STCP) related handlers."""

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.keyboards.inline import (
    bus_menu_keyboard,
    bus_stop_actions_keyboard,
    bus_stop_results_keyboard,
    bus_routes_keyboard,
)
from bot.database import is_favorite
from bot.handlers.start import _clear_awaiting
from bot.services import stcp
from bot.utils.formatting import escape_md, format_bus_arrivals
from bot.utils.i18n import get_lang, get_zone_display, t
from bot.utils.telegram import (
    pop_active_flag,
    rows_of,
    safe_callback_button,
    safe_edit_message,
    safe_edit_reply_markup,
    t_safe,
    truncate_label,
)

logger = logging.getLogger(__name__)

# Conversation state key. Nothing sets it any more (stop search moved to inline
# mode); it is still honoured so a pending prompt from an older session, or a
# future non-inline entry point, still routes text correctly.
AWAITING_BUS_FIND = "awaiting_bus_find"

#: Stops shown per page in the route view.
_ROUTE_STOPS_PER_PAGE = 8

#: A stop code short enough to be a code rather than a name.
_MAX_STOP_CODE_LEN = 6


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
        # Refreshing before the next arrival changes leaves the message
        # byte-identical; the shared helper absorbs Telegram's complaint.
        await safe_edit_message(
            query, text,
            reply_markup=bus_stop_actions_keyboard(
                stop_id, is_fav=is_fav, lang=lang, back_callback=back_cb),
        )

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


def _parse_route_callback(data: str) -> tuple[str, int, int]:
    """Parse ``bus:route:<num>[:<direction>[:<page>]]``.

    The bare two-part form is still accepted so older messages (and the route
    list keyboard, which lives in a module owned elsewhere) keep working.
    """
    parts = data.split(":")
    route_num = parts[2] if len(parts) > 2 else ""
    direction = 0
    page = 0
    if len(parts) > 3:
        try:
            direction = 1 if int(parts[3]) else 0
        except ValueError:
            direction = 0
    if len(parts) > 4:
        try:
            page = max(0, int(parts[4]))
        except ValueError:
            page = 0
    return route_num, direction, page


def _direction_label(direction: int, lang: str) -> str:
    """Human name of a route direction ("Ida" / "Volta")."""
    if direction:
        return t_safe("bus_direction_return", lang, pt="Volta", en="Return")
    return t_safe("bus_direction_outbound", lang, pt="Ida", en="Outbound")


def _bus_route_keyboard(route_num: str, direction: int, page: int,
                        stops: list[dict], lang: str) -> InlineKeyboardMarkup:
    """Keyboard for a route: tappable stops, paging, and a direction toggle.

    Built locally on purpose (``bot/keyboards/inline.py`` is out of scope) and
    every ``callback_data`` is byte-checked: stop names and route codes can be
    accented, and each accent costs two bytes against Telegram's 64-byte cap.
    """
    start = page * _ROUTE_STOPS_PER_PAGE
    page_stops = stops[start:start + _ROUTE_STOPS_PER_PAGE]

    buttons = []
    for stop in page_stops:
        button = safe_callback_button(
            truncate_label(f"\U0001f68f {stop['name']}", 30),
            f"bus:stop:{stop['stop_id']}",
        )
        if button is not None:
            buttons.append(button)
    rows = rows_of(buttons, per_row=2)

    nav = []
    if page > 0:
        prev_btn = safe_callback_button(
            t("kb_previous", lang),
            f"bus:route:{route_num}:{direction}:{page - 1}")
        if prev_btn is not None:
            nav.append(prev_btn)
    if start + _ROUTE_STOPS_PER_PAGE < len(stops):
        next_btn = safe_callback_button(
            t("kb_next", lang),
            f"bus:route:{route_num}:{direction}:{page + 1}")
        if next_btn is not None:
            nav.append(next_btn)
    if nav:
        rows.append(nav)

    other = 1 - direction
    toggle = safe_callback_button(
        t_safe("kb_bus_direction", lang,
               pt=f"\U0001f501 Sentido: {_direction_label(other, 'pt')}",
               en=f"\U0001f501 Direction: {_direction_label(other, 'en')}"),
        f"bus:route:{route_num}:{other}:0",
    )
    if toggle is not None:
        rows.append([toggle])

    rows.append([InlineKeyboardButton(t("kb_back", lang),
                                      callback_data="bus:routes")])
    return InlineKeyboardMarkup(rows)


def _bus_route_text(route_num: str, direction: int, stops: list[dict],
                    lang: str) -> str:
    """Message body listing the stop sequence of one direction of a route."""
    header = [
        t("bus_line_title", lang).format(route=escape_md(route_num)),
        f"_{escape_md(_direction_label(direction, lang))}_",
        t("bus_line_stops", lang).format(count=escape_md(str(len(stops)))),
    ]

    lines = list(header)
    for i, stop in enumerate(stops):
        prefix = "\U0001f534" if i in (0, len(stops) - 1) else "\u26aa"
        lines.append(
            f"  {prefix} {escape_md(stop['name'])} "
            f"\\(`{escape_md(stop['stop_id'])}`\\)"
        )

    text = "\n".join(lines)
    if len(text) <= 4000:
        return text

    # Too long for one Telegram message: keep both ends, elide the middle.
    lines = header[:2] + [
        t("bus_line_stops_short", lang).format(count=escape_md(str(len(stops)))),
        f"\U0001f534 {escape_md(stops[0]['name'])} \\(`{escape_md(stops[0]['stop_id'])}`\\)",
    ]
    for stop in stops[1:3]:
        lines.append(f"\u26aa {escape_md(stop['name'])}")
    lines.append(t("bus_stops_more", lang).format(
        count=escape_md(str(max(0, len(stops) - 4)))))
    for stop in stops[-2:]:
        lines.append(f"\u26aa {escape_md(stop['name'])}")
    lines.append(
        f"\U0001f534 {escape_md(stops[-1]['name'])} "
        f"\\(`{escape_md(stops[-1]['stop_id'])}`\\)"
    )
    return "\n".join(lines)


async def bus_route_callback(update: Update,
                              context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show a route's stop sequence, either direction, with tappable stops.

    The direction used to be hardcoded to 0, so the return journey's stop order
    was unreachable, and the stops were plain text nobody could act on.
    """
    query = update.callback_query
    lang = get_lang(update)
    await query.answer(t("loading", lang))

    route_num, direction, page = _parse_route_callback(query.data)
    try:
        stops = await stcp.get_route_stops(route_num, direction=direction)

        if not stops and direction:
            # Circular routes publish only one direction: say so plainly and
            # leave the toggle in place instead of looking broken.
            await safe_edit_message(
                query,
                escape_md(t_safe(
                    "bus_direction_unavailable", lang,
                    pt=(f"A linha {route_num} nao publica paragens no sentido "
                        f"{_direction_label(direction, 'pt').lower()}."),
                    en=(f"Route {route_num} publishes no stops for the "
                        f"{_direction_label(direction, 'en').lower()} direction."),
                )),
                reply_markup=_bus_route_keyboard(route_num, direction, 0, [], lang),
            )
            return

        if not stops:
            await safe_edit_message(
                query, t("error_load_line", lang).format(route=escape_md(route_num)),
                reply_markup=bus_menu_keyboard(lang),
            )
            return

        text = _bus_route_text(route_num, direction, stops, lang)
        text += "\n\n_" + escape_md(t_safe(
            "bus_tap_stop_hint", lang,
            pt="Toca numa paragem para ver as chegadas",
            en="Tap a stop to see live arrivals",
        )) + "_"

        # Coming back from a stop should return to this route view.
        context.user_data["bus_back"] = f"bus:route:{route_num}:{direction}:{page}"

        await safe_edit_message(
            query, text,
            reply_markup=_bus_route_keyboard(route_num, direction, page,
                                             stops, lang),
        )
    except Exception:
        logger.exception("Error in bus_route_callback for %s", route_num)
        await safe_edit_message(
            query, t("error_load_line2", lang).format(route=escape_md(route_num)),
            reply_markup=bus_menu_keyboard(lang),
        )


async def handle_bus_text_input(update: Update,
                                 context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle text input for bus find (unified search/code). Returns True if handled.

    Signature is unchanged: ``bot/main.py`` calls this for every plain text
    message and relies on the boolean to decide whether another handler gets a
    turn. Only the duplicated legacy-flag bookkeeping was removed.
    """
    text = update.message.text.strip()

    if not pop_active_flag(context.user_data, AWAITING_BUS_FIND):
        return False

    lang = get_lang(update)

    # Auto-detect: short text containing digits is a stop code, not a name.
    if len(text) <= _MAX_STOP_CODE_LEN and any(c.isdigit() for c in text):
        await _send_stop_realtime(update.message, text.upper(), context, lang=lang)
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
        await safe_edit_reply_markup(query, None)
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
