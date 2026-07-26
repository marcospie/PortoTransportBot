"""Route planning handler with multimodal trip planner."""
import logging
import re
from datetime import datetime

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
from telegram.ext import ContextTypes

from bot.services.trip_planner import (
    plan_trip_from_coords_async, resolve_location, TripOption,
)
from bot.keyboards.inline import trip_results_keyboard, trip_detail_keyboard
from bot.utils.formatting import escape_md
from bot.utils.i18n import get_lang, t
from bot.utils.telegram import safe_edit_message

logger = logging.getLogger(__name__)

AWAITING_ROUTE_ORIGIN = "awaiting_route_origin"
AWAITING_ROUTE_DEST = "awaiting_route_dest"

# How long a pending origin/destination prompt stays valid (seconds).
ROUTE_STATE_TTL_S = 300

# Emoji mapping for transport modes
_MODE_EMOJI = {
    "walk": "🚶",
    "metro": "🚇",
    "bus": "🚌",
    "train": "🚆",
    "metrobus": "🚍",
}

# ---------------------------------------------------------------------------
# Localisation helpers
# ---------------------------------------------------------------------------
# bot/utils/i18n.py is owned by another change; ``t()`` returns the key itself
# for anything it does not know.  ``tf()`` keeps user-visible text correct in
# both languages today and automatically starts using the shared catalogue the
# moment the key lands there.
_LOCAL_STRINGS: dict[str, dict[str, str]] = {
    "trip_share_location_prompt": {
        "pt": "📍 Toca no botão abaixo para partilhar a tua localização como *origem*\\.",
        "en": "📍 Tap the button below to share your location as the *origin*\\.",
    },
    "trip_share_location_button": {
        "pt": "📍 Partilhar localização",
        "en": "📍 Share location",
    },
    "trip_times_window": {
        "pt": "🕐 Partida *{start}* → chegada *{end}*",
        "en": "🕐 Departs *{start}* → arrives *{end}*",
    },
    "trip_step_wait": {
        "pt": "⏳ Espera {min} min",
        "en": "⏳ Wait {min} min",
    },
    "trip_step_towards": {
        "pt": "     ↳ direção *{direction}*",
        "en": "     ↳ towards *{direction}*",
    },
    "my_location": {
        "pt": "A minha localização",
        "en": "My location",
    },
    "train_stations": {
        "pt": "Estações de comboio",
        "en": "Train stations",
    },
    "commuter_share_location_button": {
        "pt": "📍 Enviar a minha localização",
        "en": "📍 Send my location",
    },
    "commuter_location_hint": {
        "pt": "_Podes também enviar a tua 📍 localização \\(ou qualquer paragem\\)\\._",
        "en": "_You can also send your 📍 location \\(or any stop\\)\\._",
    },
    "commuter_invalid_coords": {
        "pt": ("❌ Essas coordenadas não são válidas para a região do Porto\\.\n"
               "Envia a tua 📍 localização ou o nome de uma paragem\\."),
        "en": ("❌ Those coordinates are not valid for the Porto region\\.\n"
               "Send your 📍 location or the name of a stop\\."),
    },
    "commuter_profile_incomplete": {
        "pt": ("⚠️ O teu perfil não tem coordenadas válidas\\.\n"
               "Volta a configurar para poder planear o trajeto\\."),
        "en": ("⚠️ Your profile has no valid coordinates\\.\n"
               "Please set it up again so the route can be planned\\."),
    },
    "notif_commute_body": {
        "pt": "🏠→🏢 O teu trajeto habitual parte por volta das *{time}*\\.",
        "en": "🏠→🏢 Your usual trip leaves around *{time}*\\.",
    },
    "notif_next_departure": {
        "pt": "🚇 Próxima partida em *{min} min* \\({line}\\)",
        "en": "🚇 Next departure in *{min} min* \\({line}\\)",
    },
}

_MD_ESCAPE_RE = re.compile(r"\\([_*\[\]()~`>#+\-=|{}.!])")


def tf(key: str, lang: str = "pt") -> str:
    """``t()`` with a local fallback for keys not yet in the shared catalogue."""
    value = t(key, lang)
    if value != key:
        return value
    local = _LOCAL_STRINGS.get(key)
    if not local:
        return value
    return local.get(lang) or local.get("pt", key)


def plain(text: str) -> str:
    """Strip MarkdownV2 escaping, for places that take plain text.

    ``callback_query.answer()`` toasts are *not* parsed as Markdown, so feeding
    them an escaped catalogue string shows raw backslashes to the user.
    """
    return _MD_ESCAPE_RE.sub(r"\1", text)


def _state_is_fresh(value) -> bool:
    """True when a stored awaiting-state timestamp is still valid."""
    if not isinstance(value, datetime):
        return False
    return (datetime.now() - value).total_seconds() <= ROUTE_STATE_TTL_S


def is_awaiting_route_origin(context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Whether the user is currently being asked for a trip origin."""
    try:
        user_data = context.user_data
    except AttributeError:
        return False
    if not isinstance(user_data, dict):
        return False
    return _state_is_fresh(user_data.get(AWAITING_ROUTE_ORIGIN))


def _cancel_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("kb_cancel", lang), callback_data="menu:main")],
    ])


def _origin_prompt_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("trip_use_location", lang),
                              callback_data="trip:use_location_origin")],
        [InlineKeyboardButton(t("kb_cancel", lang), callback_data="menu:main")],
    ])


def _retry_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("trip_new", lang), callback_data="plan:route")],
        [InlineKeyboardButton(t("back_main", lang), callback_data="menu:main")],
    ])


# ===================================================================
# Formatting
# ===================================================================

def _format_trip_option(option: TripOption, index: int, lang: str = "pt") -> str:
    """Format a single TripOption as MarkdownV2 text."""
    header = t("trip_option_header", lang).format(n=index, time=option.total_time_min)
    if option.transfers > 0:
        header += t("trip_option_transfers", lang).format(transfers=option.transfers)

    parts = [header]

    if option.departure_time and option.arrival_time:
        parts.append(tf("trip_times_window", lang).format(
            start=escape_md(option.departure_time),
            end=escape_md(option.arrival_time),
        ))

    prev_mode = None
    for step in option.steps:
        if step.mode == "walk":
            if step.to_name:
                parts.append(t("trip_step_walk", lang).format(
                    min=step.duration_min, to=escape_md(step.to_name)))
            elif step.from_name:
                parts.append(t("trip_step_walk_from", lang).format(
                    min=step.duration_min, from_name=escape_md(step.from_name)))
        else:
            if step.wait_min:
                parts.append(tf("trip_step_wait", lang).format(min=step.wait_min))
            key = f"trip_step_{step.mode}"
            template = t(key, lang)
            if template == key:  # unknown mode -> fall back to the bus layout
                template = t("trip_step_bus", lang)
            parts.append(template.format(
                line=escape_md(step.line),
                **{"from": escape_md(step.from_name)},
                to=escape_md(step.to_name),
                min=step.duration_min,
            ))
            if step.departure_time:
                parts[-1] += f" `{escape_md(step.departure_time)}`"
            if step.direction:
                parts.append(tf("trip_step_towards", lang).format(
                    direction=escape_md(step.direction)))
            # Add transfer indicator between non-walk steps
            if prev_mode and prev_mode != "walk" and step.mode != "walk":
                parts.insert(-1, t("trip_transfer_at", lang).format(
                    station=escape_md(step.from_name)))

        prev_mode = step.mode

    if option.zones:
        parts.append(t("trip_zones", lang).format(zones=escape_md(", ".join(option.zones))))

    if option.estimated:
        parts.append(t("data_estimated", lang))

    return "\n".join(parts)


def format_trip_option(option: TripOption, index: int, lang: str = "pt") -> str:
    """Public alias of :func:`_format_trip_option` for other handlers."""
    return _format_trip_option(option, index, lang)


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


# ===================================================================
# Entry points
# ===================================================================

async def route_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /route command - start trip planning."""
    lang = get_lang(update)
    await update.message.reply_text(
        t("trip_title", lang) + "\n\n" + t("trip_ask_origin", lang),
        parse_mode="MarkdownV2",
        reply_markup=_origin_prompt_keyboard(lang),
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
    await safe_edit_message(
        query,
        t("trip_title", lang) + "\n\n" + t("trip_ask_origin", lang),
        reply_markup=_origin_prompt_keyboard(lang),
    )


async def trip_use_location_callback(update: Update,
                                     context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the 'Use my location' button in the trip planner.

    This used to be a dead button: the callback data was never registered, so
    every tap fell through to the catch-all handler which told the user the
    button was invalid and stripped the keyboard.
    """
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)

    # Arm the origin state so the incoming location is consumed as the origin.
    context.user_data[AWAITING_ROUTE_ORIGIN] = datetime.now()
    context.user_data.pop(AWAITING_ROUTE_DEST, None)
    context.user_data.pop("route_origin", None)

    await safe_edit_message(
        query,
        t("trip_title", lang) + "\n\n" + tf("trip_share_location_prompt", lang),
        reply_markup=_cancel_keyboard(lang),
    )

    # Inline keyboards cannot request a location, so offer a one-time reply
    # keyboard button that can.
    try:
        await query.message.reply_text(
            tf("trip_share_location_prompt", lang),
            parse_mode="MarkdownV2",
            reply_markup=ReplyKeyboardMarkup(
                [[KeyboardButton(tf("trip_share_location_button", lang),
                                 request_location=True)]],
                resize_keyboard=True,
                one_time_keyboard=True,
            ),
        )
    except Exception:
        logger.debug("Could not attach the location request keyboard", exc_info=True)


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
            options = await plan_trip_from_coords_async(
                origin["lat"], origin["lon"], dest["lat"], dest["lon"])
            await _send_results(update, context, origin["name"], dest["name"],
                                options, lang)
            return True

    # Check if awaiting origin
    ts_origin = context.user_data.get(AWAITING_ROUTE_ORIGIN)
    if _state_is_fresh(ts_origin):
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

        await _set_origin_and_ask_dest(update, context, origin, lang)
        return True

    # Check if awaiting destination
    ts_dest = context.user_data.get(AWAITING_ROUTE_DEST)
    if _state_is_fresh(ts_dest):
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

        options = await plan_trip_from_coords_async(
            origin["lat"], origin["lon"], dest["lat"], dest["lon"],
        )
        await _send_results(update, context, origin["name"], dest["name"],
                            options, lang)
        return True

    return False


async def _set_origin_and_ask_dest(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                   origin: dict, lang: str) -> None:
    """Store *origin* and prompt for the destination."""
    context.user_data["route_origin"] = origin
    context.user_data[AWAITING_ROUTE_DEST] = datetime.now()

    emoji = _MODE_EMOJI.get(origin.get("type", ""), "📍")

    await update.message.reply_text(
        t("trip_title", lang) + "\n\n"
        + t("trip_origin_set", lang).format(emoji=emoji, name=escape_md(origin["name"]))
        + "\n\n" + t("trip_ask_dest", lang),
        parse_mode="MarkdownV2",
        reply_markup=_cancel_keyboard(lang),
    )


async def _send_results(update: Update, context: ContextTypes.DEFAULT_TYPE,
                        origin_name: str, dest_name: str,
                        options: list[TripOption], lang: str) -> None:
    """Render trip options (or the "nothing found" screen)."""
    if options:
        context.user_data["trip_options"] = options
        msg = _format_trip_results(origin_name, dest_name, options, lang)
        await update.message.reply_text(
            msg,
            parse_mode="MarkdownV2",
            reply_markup=trip_results_keyboard(options, lang),
        )
    else:
        await update.message.reply_text(
            t("trip_no_routes", lang),
            parse_mode="MarkdownV2",
            reply_markup=_retry_keyboard(lang),
        )


async def handle_route_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Consume a shared location as the trip origin. Returns True if handled.

    Called from :func:`bot.handlers.location.location_handler` *before* the
    nearby-stops screen, so that a location sent while planning a trip actually
    sets the origin instead of showing an unrelated screen.
    """
    if not is_awaiting_route_origin(context):
        return False

    location = getattr(update.message, "location", None)
    if not location:
        return False

    lang = get_lang(update)
    context.user_data.pop(AWAITING_ROUTE_ORIGIN, None)

    origin = {
        "name": "📍 " + tf("my_location", lang),
        "lat": location.latitude,
        "lon": location.longitude,
        "type": "location",
    }

    await _set_origin_and_ask_dest(update, context, origin, lang)
    return True


async def trip_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show detailed view of a trip option."""
    query = update.callback_query
    lang = get_lang(update)

    data = query.data  # trip:detail:N
    try:
        index = int(data.split(":")[-1])
    except (ValueError, IndexError):
        await query.answer(plain(t("option_not_available", lang)))
        return

    options = context.user_data.get("trip_options", [])
    if not options or index >= len(options):
        # A single, localized answer (the old code answered twice, so this
        # feedback never reached the user, and the second message was
        # hardcoded English).
        await query.answer(plain(t("option_not_available", lang)))
        await safe_edit_message(
            query,
            t("option_not_available", lang),
            reply_markup=_retry_keyboard(lang),
        )
        return

    await query.answer()

    option = options[index]
    text = _format_trip_option(option, index + 1, lang)
    text += "\n\n"
    text += t("trip_total_time", lang).format(min=option.total_time_min)
    text += "\n"
    text += t("trip_transfers_count", lang).format(count=option.transfers)

    await safe_edit_message(query, text, reply_markup=trip_detail_keyboard(index, lang))


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
