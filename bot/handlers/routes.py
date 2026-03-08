"""Route planning handler."""
import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.services import stcp
from bot.services.metro import (
    STATIONS, get_line_stations, get_station_coordinates,
    get_next_departures, METRO_LINES, search_stations,
)
from bot.utils.formatting import escape_md
from bot.utils.i18n import get_lang, t
from bot.config import METRO_LINES as METRO_LINES_CONFIG

logger = logging.getLogger(__name__)

AWAITING_ROUTE_ORIGIN = "awaiting_route_origin"
AWAITING_ROUTE_DEST = "awaiting_route_dest"


async def route_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /route command - start route planning."""
    lang = get_lang(update)
    await update.message.reply_text(
        t("route_title", lang) + "\n\n" + t("route_ask_origin", lang),
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Pesquisar origem..." if lang == "pt" else "🔍 Search origin...",
                                  switch_inline_query_current_chat="")],
            [InlineKeyboardButton(t("kb_cancel", lang), callback_data="menu:main")],
        ]),
    )
    context.user_data[AWAITING_ROUTE_ORIGIN] = datetime.now()


async def route_plan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start route planning from callback."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)
    context.user_data[AWAITING_ROUTE_ORIGIN] = datetime.now()
    context.user_data.pop(AWAITING_ROUTE_DEST, None)
    context.user_data.pop("route_origin", None)
    await query.edit_message_text(
        t("route_title", lang) + "\n\n" + t("route_ask_origin", lang),
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Pesquisar origem..." if lang == "pt" else "🔍 Search origin...",
                                  switch_inline_query_current_chat="")],
            [InlineKeyboardButton(t("kb_cancel", lang), callback_data="menu:main")],
        ]),
    )


async def handle_route_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle text input for route planning. Returns True if handled."""
    text = update.message.text.strip()
    lang = get_lang(update)

    # Check if awaiting origin
    ts_origin = context.user_data.get(AWAITING_ROUTE_ORIGIN)
    if ts_origin and isinstance(ts_origin, datetime) and (datetime.now() - ts_origin).total_seconds() < 300:
        context.user_data.pop(AWAITING_ROUTE_ORIGIN, None)

        # Find the origin (try metro station first, then bus stop)
        origin = await _resolve_location(text)
        if not origin:
            await update.message.reply_text(
                t("route_not_found", lang).format(query=escape_md(text)),
                parse_mode="MarkdownV2",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(t("retry", lang), callback_data="route:plan")],
                    [InlineKeyboardButton(t("back_main", lang), callback_data="menu:main")],
                ]),
            )
            return True

        context.user_data["route_origin"] = origin
        context.user_data[AWAITING_ROUTE_DEST] = datetime.now()

        origin_label = origin["name"]
        origin_type_emoji = "🚇" if origin["type"] == "metro" else "🚌"

        await update.message.reply_text(
            t("route_title", lang) + "\n\n"
            + t("route_origin_label", lang).format(emoji=origin_type_emoji, name=escape_md(origin_label)) + "\n\n"
            + t("route_ask_dest", lang),
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔍 Pesquisar destino..." if lang == "pt" else "🔍 Search destination...",
                                      switch_inline_query_current_chat="")],
                [InlineKeyboardButton(t("kb_cancel", lang), callback_data="menu:main")],
            ]),
        )
        return True

    # Check if awaiting destination
    ts_dest = context.user_data.get(AWAITING_ROUTE_DEST)
    if ts_dest and isinstance(ts_dest, datetime) and (datetime.now() - ts_dest).total_seconds() < 300:
        context.user_data.pop(AWAITING_ROUTE_DEST, None)

        origin = context.user_data.get("route_origin")
        if not origin:
            return False

        dest = await _resolve_location(text)
        if not dest:
            await update.message.reply_text(
                t("route_not_found", lang).format(query=escape_md(text)),
                parse_mode="MarkdownV2",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(t("retry", lang), callback_data="route:plan")],
                    [InlineKeyboardButton(t("back_main", lang), callback_data="menu:main")],
                ]),
            )
            return True

        context.user_data.pop("route_origin", None)

        # Find routes between origin and destination
        await _find_and_show_routes(update.message, origin, dest, lang=lang)
        return True

    return False


async def _resolve_location(query: str) -> dict | None:
    """Resolve a text query to a metro station or bus stop."""
    # Try metro station first
    stations = search_stations(query)
    if stations:
        station = stations[0]
        return {
            "type": "metro",
            "name": station["name"],
            "lines": [l["code"] for l in station["lines"]],
        }

    # Try bus stop
    stops = await stcp.search_stops(query)
    if stops:
        stop = stops[0]
        return {
            "type": "bus",
            "name": stop["name"],
            "stop_id": stop["stop_id"],
        }

    # Try as stop code
    if len(query) <= 6 and any(c.isdigit() for c in query):
        data = await stcp.get_stop_real_time(query.upper())
        if data["stop_name"] != query.upper():
            return {
                "type": "bus",
                "name": data["stop_name"],
                "stop_id": query.upper(),
            }

    return None


async def _find_and_show_routes(message, origin: dict, dest: dict, lang: str = "pt") -> None:
    """Find and display route options between origin and destination."""
    origin_emoji = "🚇" if origin["type"] == "metro" else "🚌"
    dest_emoji = "🚇" if dest["type"] == "metro" else "🚌"

    lines = [
        t("route_found", lang),
        f"📍 {origin_emoji} *{escape_md(origin['name'])}*",
        f"📍 {dest_emoji} *{escape_md(dest['name'])}*\n",
        "━━━━━━━━━━━━━━━━\n",
    ]

    options_found = False

    # Case 1: Both are metro stations
    if origin["type"] == "metro" and dest["type"] == "metro":
        options = _find_metro_route(origin["name"], dest["name"], lang=lang)
        if options:
            options_found = True
            for i, option in enumerate(options, 1):
                lines.append(t("route_option", lang).format(n=i))
                for step in option["steps"]:
                    lines.append(f"  {step}")
                lines.append("")

    # Case 2: Both are bus stops
    elif origin["type"] == "bus" and dest["type"] == "bus":
        options = await _find_bus_route(origin["stop_id"], dest["stop_id"], lang=lang)
        if options:
            options_found = True
            for i, option in enumerate(options, 1):
                lines.append(t("route_option", lang).format(n=i))
                for step in option["steps"]:
                    lines.append(f"  {step}")
                lines.append("")

    # Case 3: Mixed (bus + metro)
    else:
        lines.append(t("route_mixed", lang))
        if origin["type"] == "metro":
            lines.append(t("route_take_metro", lang).format(name=escape_md(origin['name'])))
            lines.append(t("route_then_bus", lang).format(name=escape_md(dest['name'])))
        else:
            lines.append(t("route_take_bus", lang).format(name=escape_md(origin['name'])))
            lines.append(t("route_then_metro", lang).format(name=escape_md(dest['name'])))
        lines.append("")
        lines.append(t("route_tip_nearby", lang))
        options_found = True

    if not options_found:
        lines.append(t("route_no_direct", lang))
        lines.append(t("route_tip_metro", lang))

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "\\.\\.\\."

    await message.reply_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t("route_new", lang), callback_data="route:plan")],
            [InlineKeyboardButton(t("back_main", lang), callback_data="menu:main")],
        ]),
    )


def _find_metro_route(origin_name: str, dest_name: str, lang: str = "pt") -> list[dict]:
    """Find metro route options between two stations."""
    origin_data = STATIONS.get(origin_name, {})
    dest_data = STATIONS.get(dest_name, {})

    if not origin_data or not dest_data:
        return []

    origin_lines = set(origin_data.get("lines", []))
    dest_lines = set(dest_data.get("lines", []))

    options = []

    # Direct lines (both stations on the same line)
    common_lines = origin_lines & dest_lines
    if common_lines:
        for line_code in common_lines:
            line_data = METRO_LINES.get(line_code, {})
            emoji = line_data.get("emoji", "🚇")
            name = line_data.get("name", f"Linha {line_code}")
            options.append({
                "steps": [
                    f"{emoji} Apanha a *{escape_md(name)}*" if lang == "pt" else f"{emoji} Take the *{escape_md(name)}*",
                    f"   De *{escape_md(origin_name)}* até *{escape_md(dest_name)}*" if lang == "pt" else f"   From *{escape_md(origin_name)}* to *{escape_md(dest_name)}*",
                    f"   {t('route_direct', lang)}",
                ],
                "transfers": 0,
            })
        return options[:3]

    # One transfer needed - find common transfer stations
    for transfer_name, transfer_data in STATIONS.items():
        transfer_lines = set(transfer_data.get("lines", []))

        # Find lines from origin to transfer and from transfer to dest
        origin_to_transfer = origin_lines & transfer_lines
        transfer_to_dest = transfer_lines & dest_lines

        if origin_to_transfer and transfer_to_dest:
            # Ensure we use different lines (actual transfer)
            for line1 in origin_to_transfer:
                for line2 in transfer_to_dest:
                    if line1 != line2 or (line1 == line2 and transfer_name != origin_name and transfer_name != dest_name):
                        l1_data = METRO_LINES.get(line1, {})
                        l2_data = METRO_LINES.get(line2, {})
                        take_text = "Apanha a" if lang == "pt" else "Take the"
                        from_to = "De" if lang == "pt" else "From"
                        to_word = "até" if lang == "pt" else "to"
                        options.append({
                            "steps": [
                                f"{l1_data.get('emoji', '🚇')} {take_text} *{escape_md(l1_data.get('name', f'Linha {line1}'))}*",
                                f"   {from_to} *{escape_md(origin_name)}* {to_word} *{escape_md(transfer_name)}*",
                                t("route_transfer", lang).format(station=escape_md(transfer_name)),
                                f"{l2_data.get('emoji', '🚇')} {take_text} *{escape_md(l2_data.get('name', f'Linha {line2}'))}*",
                                f"   {from_to} *{escape_md(transfer_name)}* {to_word} *{escape_md(dest_name)}*",
                            ],
                            "transfers": 1,
                            "transfer_station": transfer_name,
                        })

    # Deduplicate by transfer station and sort by transfers
    seen = set()
    unique_options = []
    for opt in options:
        key = opt.get("transfer_station", "") + str(opt.get("transfers", 0))
        if key not in seen:
            seen.add(key)
            unique_options.append(opt)

    unique_options.sort(key=lambda x: x["transfers"])
    return unique_options[:3]


async def _find_bus_route(origin_id: str, dest_id: str, lang: str = "pt") -> list[dict]:
    """Find bus route options between two stops."""
    try:
        # Get info for both stops to find common routes
        origin_info = await stcp.get_stop_info(origin_id)
        dest_info = await stcp.get_stop_info(dest_id)

        origin_routes = {r["number"] for r in origin_info.get("routes", [])}
        dest_routes = {r["number"] for r in dest_info.get("routes", [])}

        common_routes = origin_routes & dest_routes

        options = []
        if common_routes:
            take_line = "Apanha a linha" if lang == "pt" else "Take line"
            from_word = "De" if lang == "pt" else "From"
            to_word = "até" if lang == "pt" else "to"
            for route_num in list(common_routes)[:3]:
                options.append({
                    "steps": [
                        f"🚌 {take_line} *{escape_md(route_num)}*",
                        f"   {from_word} *{escape_md(origin_info.get('name', origin_id))}* {to_word} *{escape_md(dest_info.get('name', dest_id))}*",
                        f"   {t('route_direct', lang)}",
                    ],
                    "transfers": 0,
                })

        if not options:
            options.append({
                "steps": [
                    t("route_no_direct_bus", lang),
                    t("route_tip_via_metro", lang),
                ],
                "transfers": -1,
            })

        return options
    except Exception:
        logger.exception("Error finding bus route")
        return []
