"""Route planning handler with multimodal trip planner."""
import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.services import stcp
from bot.services.metro import (
    STATIONS, get_line_stations, get_station_coordinates,
    get_next_departures, METRO_LINES, search_stations,
)
from bot.services.trip_planner import (
    plan_trip, plan_trip_from_coords, resolve_location, TripOption, TripStep,
)
from bot.keyboards.inline import trip_results_keyboard, trip_detail_keyboard
from bot.utils.formatting import escape_md
from bot.utils.i18n import get_lang, t
from bot.config import METRO_LINES as METRO_LINES_CONFIG

logger = logging.getLogger(__name__)

AWAITING_ROUTE_ORIGIN = "awaiting_route_origin"
AWAITING_ROUTE_DEST = "awaiting_route_dest"

# Emoji mapping for transport modes
_MODE_EMOJI = {
    "walk": "🚶",
    "metro": "🚇",
    "bus": "🚌",
    "train": "🚆",
    "metrobus": "🚍",
}


def _format_trip_option(option: TripOption, index: int, lang: str = "pt") -> str:
    """Format a single TripOption as MarkdownV2 text."""
    header = t("trip_option_header", lang).format(n=index, time=option.total_time_min)
    if option.transfers > 0:
        header += t("trip_option_transfers", lang).format(transfers=option.transfers)

    parts = [header]

    prev_mode = None
    for step in option.steps:
        emoji = _MODE_EMOJI.get(step.mode, "")

        if step.mode == "walk":
            if step.to_name:
                parts.append(t("trip_step_walk", lang).format(
                    min=step.duration_min, to=escape_md(step.to_name)))
            elif step.from_name:
                parts.append(t("trip_step_walk_from", lang).format(
                    min=step.duration_min, from_name=escape_md(step.from_name)))
        else:
            key = f"trip_step_{step.mode}"
            parts.append(t(key, lang).format(
                line=escape_md(step.line),
                **{"from": escape_md(step.from_name)},
                to=escape_md(step.to_name),
                min=step.duration_min,
            ))
            # Add transfer indicator between non-walk steps
            if prev_mode and prev_mode != "walk" and step.mode != "walk":
                # Insert transfer before this step
                parts.insert(-1, t("trip_transfer_at", lang).format(
                    station=escape_md(step.from_name)))

        prev_mode = step.mode

    if option.zones:
        parts.append(t("trip_zones", lang).format(zones=escape_md(", ".join(option.zones))))

    return "\n".join(parts)


def _format_trip_results(origin_name: str, dest_name: str,
                         options: list[TripOption], lang: str = "pt") -> str:
    """Format full trip planning results."""
    lines = [
        t("trip_results_title", lang),
        t("trip_from_to", lang).format(
            origin=escape_md(origin_name), dest=escape_md(dest_name)),
        "━━━━━━━━━━━━━━━━\n",
    ]

    for i, opt in enumerate(options, 1):
        lines.append(_format_trip_option(opt, i, lang))
        lines.append("")

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3990] + "\\.\\.\\."
    return text


async def route_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /route command - start trip planning."""
    lang = get_lang(update)
    await update.message.reply_text(
        t("trip_title", lang) + "\n\n" + t("trip_ask_origin", lang),
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t("trip_use_location", lang),
                                  callback_data="trip:use_location_origin")],
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
    context.user_data.pop("trip_options", None)
    await query.edit_message_text(
        t("trip_title", lang) + "\n\n" + t("trip_ask_origin", lang),
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t("trip_use_location", lang),
                                  callback_data="trip:use_location_origin")],
            [InlineKeyboardButton(t("kb_cancel", lang), callback_data="menu:main")],
        ]),
    )


async def handle_route_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle text input for route planning. Returns True if handled."""
    text = update.message.text.strip()
    lang = get_lang(update)

    # Check for "from X to Y" pattern
    from_to = _parse_from_to(text, lang)
    if from_to:
        origin_text, dest_text = from_to
        origin = resolve_location(origin_text)
        dest = resolve_location(dest_text)
        if origin and dest:
            options = plan_trip(origin_text, dest_text)
            if options:
                context.user_data["trip_options"] = options
                msg = _format_trip_results(origin["name"], dest["name"], options, lang)
                await update.message.reply_text(
                    msg,
                    parse_mode="MarkdownV2",
                    reply_markup=trip_results_keyboard(options, lang),
                )
            else:
                await update.message.reply_text(
                    t("trip_no_routes", lang),
                    parse_mode="MarkdownV2",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton(t("trip_new", lang), callback_data="plan:route")],
                        [InlineKeyboardButton(t("back_main", lang), callback_data="menu:main")],
                    ]),
                )
            return True

    # Check if awaiting origin
    ts_origin = context.user_data.get(AWAITING_ROUTE_ORIGIN)
    if ts_origin and isinstance(ts_origin, datetime) and (datetime.now() - ts_origin).total_seconds() < 300:
        context.user_data.pop(AWAITING_ROUTE_ORIGIN, None)

        origin = resolve_location(text)
        if not origin:
            await update.message.reply_text(
                t("trip_not_found", lang).format(query=escape_md(text)),
                parse_mode="MarkdownV2",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(t("retry", lang), callback_data="route:plan")],
                    [InlineKeyboardButton(t("back_main", lang), callback_data="menu:main")],
                ]),
            )
            return True

        context.user_data["route_origin"] = origin
        context.user_data[AWAITING_ROUTE_DEST] = datetime.now()

        origin_type_emoji = _MODE_EMOJI.get(origin["type"], "📍")

        await update.message.reply_text(
            t("trip_title", lang) + "\n\n"
            + t("trip_origin_set", lang).format(emoji=origin_type_emoji, name=escape_md(origin["name"])) + "\n\n"
            + t("trip_ask_dest", lang),
            parse_mode="MarkdownV2",
            reply_markup=InlineKeyboardMarkup([
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

        dest = resolve_location(text)
        if not dest:
            await update.message.reply_text(
                t("trip_not_found", lang).format(query=escape_md(text)),
                parse_mode="MarkdownV2",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(t("retry", lang), callback_data="route:plan")],
                    [InlineKeyboardButton(t("back_main", lang), callback_data="menu:main")],
                ]),
            )
            return True

        context.user_data.pop("route_origin", None)

        # Use the trip planner
        options = plan_trip_from_coords(
            origin["lat"], origin["lon"],
            dest["lat"], dest["lon"],
        )

        if options:
            context.user_data["trip_options"] = options
            msg = _format_trip_results(origin["name"], dest["name"], options, lang)
            await update.message.reply_text(
                msg,
                parse_mode="MarkdownV2",
                reply_markup=trip_results_keyboard(options, lang),
            )
        else:
            await update.message.reply_text(
                t("trip_no_routes", lang),
                parse_mode="MarkdownV2",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(t("trip_new", lang), callback_data="plan:route")],
                    [InlineKeyboardButton(t("back_main", lang), callback_data="menu:main")],
                ]),
            )
        return True

    return False


async def handle_route_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle location input for trip planning. Returns True if handled."""
    ts_origin = context.user_data.get(AWAITING_ROUTE_ORIGIN)
    if not ts_origin:
        return False
    if not isinstance(ts_origin, datetime):
        return False
    if (datetime.now() - ts_origin).total_seconds() > 300:
        return False

    location = update.message.location
    if not location:
        return False

    lang = get_lang(update)
    context.user_data.pop(AWAITING_ROUTE_ORIGIN, None)

    origin = {
        "name": "📍 " + ("Minha localização" if lang == "pt" else "My location"),
        "lat": location.latitude,
        "lon": location.longitude,
        "type": "location",
    }
    context.user_data["route_origin"] = origin
    context.user_data[AWAITING_ROUTE_DEST] = datetime.now()

    await update.message.reply_text(
        t("trip_title", lang) + "\n\n"
        + t("trip_origin_set", lang).format(emoji="📍", name=escape_md(origin["name"])) + "\n\n"
        + t("trip_ask_dest", lang),
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t("kb_cancel", lang), callback_data="menu:main")],
        ]),
    )
    return True


async def trip_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show detailed view of a trip option."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)

    data = query.data  # trip:detail:N
    try:
        index = int(data.split(":")[-1])
    except (ValueError, IndexError):
        return

    options = context.user_data.get("trip_options", [])
    if not options or index >= len(options):
        await query.answer("Option not available")
        return

    option = options[index]
    text = _format_trip_option(option, index + 1, lang)
    text += "\n\n"
    text += t("trip_total_time", lang).format(min=option.total_time_min)
    text += "\n"
    text += t("trip_transfers_count", lang).format(count=option.transfers)

    await query.edit_message_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=trip_detail_keyboard(index, lang),
    )


def _parse_from_to(text: str, lang: str = "pt") -> tuple[str, str] | None:
    """Parse 'from X to Y' or 'de X para Y' patterns."""
    text_lower = text.lower().strip()

    # PT patterns
    for pattern_from, pattern_to in [("de ", " para "), ("de ", " até "),
                                      ("from ", " to ")]:
        if text_lower.startswith(pattern_from) and pattern_to in text_lower:
            idx = text_lower.index(pattern_to)
            origin = text[len(pattern_from):idx].strip()
            dest = text[idx + len(pattern_to):].strip()
            if origin and dest:
                return (origin, dest)

    return None
