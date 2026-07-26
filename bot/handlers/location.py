"""Handler for user-sent locations to find nearby stops/stations."""

import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from bot.database import get_user_settings
from bot.keyboards.inline import main_menu_keyboard
from bot.handlers import routes as routes_handler
from bot.services import cp, metro, metrobus, stcp
from bot.utils.formatting import escape_md
from bot.utils.i18n import t, get_lang
from bot.utils.telegram import safe_edit_message

logger = logging.getLogger(__name__)

# Defaults (used when settings are not available)
NEARBY_RADIUS_KM = 0.5  # 500 meters for metro
BUS_NEARBY_RADIUS_KM = 0.2  # 200 meters for bus stops

# CP stations are far more spread out than metro stops, so a slightly wider
# radius is used for trains (still derived from the user's metro radius).
TRAIN_RADIUS_MULTIPLIER = 2.0


async def _load_settings(user_id: int) -> dict:
    try:
        return await get_user_settings(user_id)
    except Exception:
        logger.debug("Could not load user settings, using defaults")
        from bot.database import DEFAULT_SETTINGS
        return DEFAULT_SETTINGS


def _get_nearby_trains(lat: float, lon: float, radius_km: float) -> list[dict]:
    """Find nearby CP train stations (Campanhã, São Bento, Contumil, ...)."""
    try:
        stations = cp.get_nearby_stations(lat, lon, radius_km)
    except Exception:
        logger.debug("CP nearby station search failed", exc_info=True)
        return []
    return [s for s in stations if s.get("distance_m") is not None
            and s["distance_m"] <= radius_km * 1000]


def _render_nearby(lang: str, user_settings: dict,
                   nearby_stations: list[dict],
                   nearby_metrobus: list[dict],
                   nearby_trains: list[dict],
                   nearby_bus: list[dict]) -> tuple[str, InlineKeyboardMarkup]:
    """Build the nearby-transport message and keyboard."""
    max_results = user_settings["max_results"]
    radius_display = max(user_settings["metro_radius_m"], user_settings["bus_radius_m"])

    lines = [t("nearby_title", lang).format(radius=radius_display)]
    buttons: list[list[InlineKeyboardButton]] = []

    # Metro stations
    if nearby_stations:
        lines.append(f"\n🚇 *{t('metro_stations', lang)}:*\n")
        for station in nearby_stations[:max_results]:
            name = station["name"]
            dist = station["distance_m"]
            lines_names = " ".join(f'{l_["emoji"]}{l_["code"]}' for l_ in station["lines"])
            lines.append(
                f"  🚇 *{escape_md(name)}* \\- {dist}m\n"
                f"      {lines_names}"
            )
            label = f"🚇 {name} ({dist}m)"
            if len(label) > 50:
                label = f"🚇 {name[:30]}... ({dist}m)"
            cb_data = f"metro:station:{name}"
            if len(cb_data.encode("utf-8")) <= 64:
                buttons.append([InlineKeyboardButton(label, callback_data=cb_data)])

    # CP train stations
    if nearby_trains:
        lines.append(f"\n🚆 *{routes_handler.tf('train_stations', lang)}:*\n")
        for station in nearby_trains[:max_results]:
            name = station["name"]
            dist = station["distance_m"]
            lines_names = " ".join(
                f'{l_.get("emoji", "🚆")}{escape_md(l_.get("name", l_.get("id", "")))}'
                for l_ in station.get("lines", [])
            )
            lines.append(
                f"  🚆 *{escape_md(name)}* \\- {dist}m\n"
                f"      {lines_names}"
            )
            label = f"🚆 {name} ({dist}m)"
            if len(label) > 50:
                label = f"🚆 {name[:30]}... ({dist}m)"
            cb_data = f"train:station:{name}"
            if len(cb_data.encode("utf-8")) <= 64:
                buttons.append([InlineKeyboardButton(label, callback_data=cb_data)])

    # MetroBus stops
    if nearby_metrobus:
        lines.append(f"\n\U0001f68d *{t('metrobus_stops', lang)}:*\n")
        for stop in nearby_metrobus[:max_results]:
            name = stop["name"]
            dist = stop["distance_m"]
            lines_names = " ".join(f'{l_["emoji"]}{l_["code"]}' for l_ in stop["lines"])
            lines.append(
                f"  \U0001f68d *{escape_md(name)}* \\- {dist}m\n"
                f"      {lines_names}"
            )
            label = f"\U0001f68d {name} ({dist}m)"
            if len(label) > 50:
                label = f"\U0001f68d {name[:30]}... ({dist}m)"
            cb_data = f"metrobus:stop:{name}"
            if len(cb_data.encode("utf-8")) <= 64:
                buttons.append([InlineKeyboardButton(label, callback_data=cb_data)])

    # Bus stops
    if nearby_bus:
        lines.append(f"\n🚌 *{t('bus_stops', lang)}:*\n")
        for stop in nearby_bus[:max_results]:
            name = stop["name"]
            dist = stop["distance_m"]
            stop_id = stop["stop_id"]
            lines.append(f"  🚏 *{escape_md(name)}* \\(`{escape_md(stop_id)}`\\) \\- {dist}m")
            label = f"🚏 {name} ({dist}m)"
            if len(label) > 50:
                label = f"🚏 {name[:30]}... ({dist}m)"
            cb_data = f"bus:stop:{stop_id}"
            if len(cb_data.encode("utf-8")) <= 64:
                buttons.append([InlineKeyboardButton(label, callback_data=cb_data)])

    buttons.append([
        InlineKeyboardButton(t("kb_refresh", lang), callback_data="nearby:refresh"),
    ])
    buttons.append([InlineKeyboardButton(
        t("back_main", lang), callback_data="menu:main"
    )])

    return "\n".join(lines), InlineKeyboardMarkup(buttons)


async def _collect_nearby(lat: float, lon: float,
                          user_settings: dict) -> tuple[list, list, list, list]:
    """Gather nearby metro / MetroBus / CP train / STCP bus results."""
    metro_radius_km = user_settings["metro_radius_m"] / 1000
    bus_radius_km = user_settings["bus_radius_m"] / 1000

    nearby_stations = metro.get_nearby_stations(lat, lon, metro_radius_km)
    nearby_metrobus = metrobus.get_nearby_stops(lat, lon, metro_radius_km)
    nearby_trains = _get_nearby_trains(
        lat, lon, metro_radius_km * TRAIN_RADIUS_MULTIPLIER)
    nearby_bus = await _get_nearby_bus_stops(lat, lon, bus_radius_km)

    return nearby_stations, nearby_metrobus, nearby_trains, nearby_bus


async def location_handler(update: Update,
                           context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle user-sent location.

    A location shared while the trip planner is waiting for an origin belongs to
    the trip planner, not to the nearby-stops screen; that flow gets first
    refusal here.  Anything else falls through to nearby transport.
    """
    # Trip planning and commuter setup take priority over the nearby screen.
    try:
        if await routes_handler.handle_route_location(update, context):
            return
    except Exception:
        logger.exception("Route-location delegation failed; showing nearby stops")

    try:
        from bot.handlers import commuter as commuter_handler
        if await commuter_handler.handle_commuter_location(update, context):
            return
    except Exception:
        logger.exception("Commuter-location delegation failed; showing nearby stops")

    loc = update.message.location
    lat = loc.latitude
    lon = loc.longitude
    lang = get_lang(update)
    user_id = update.effective_user.id

    user_settings = await _load_settings(user_id)

    # Store location for refresh
    context.user_data["last_location"] = {"lat": lat, "lon": lon}

    (nearby_stations, nearby_metrobus,
     nearby_trains, nearby_bus) = await _collect_nearby(lat, lon, user_settings)

    if not any((nearby_stations, nearby_metrobus, nearby_trains, nearby_bus)):
        radius_display = max(user_settings["metro_radius_m"], user_settings["bus_radius_m"])
        await update.message.reply_text(
            t("nearby_empty", lang).format(radius=radius_display),
            parse_mode="MarkdownV2",
            reply_markup=main_menu_keyboard(lang),
        )
        return

    # Remember context so station/stop detail can navigate back here
    context.user_data["metro_back"] = "nearby:refresh"
    context.user_data["bus_back"] = "nearby:refresh"
    context.user_data["metrobus_back"] = "nearby:refresh"
    context.user_data["train_back"] = "nearby:refresh"

    text, keyboard = _render_nearby(
        lang, user_settings, nearby_stations, nearby_metrobus,
        nearby_trains, nearby_bus,
    )
    await update.message.reply_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=keyboard,
    )


async def nearby_refresh_callback(update: Update,
                                   context: ContextTypes.DEFAULT_TYPE) -> None:
    """Refresh nearby results using last known location."""
    query = update.callback_query
    lang = get_lang(update)
    await query.answer(t("loading", lang) if lang == "en" else "A atualizar...")

    last_loc = context.user_data.get("last_location")
    if not last_loc:
        send_loc_msg = ("📍 Envia a tua localização novamente\\." if lang == "pt"
                        else "📍 Send your location again\\.")
        await safe_edit_message(
            query,
            send_loc_msg,
            reply_markup=main_menu_keyboard(lang),
        )
        return

    lat, lon = last_loc["lat"], last_loc["lon"]
    user_id = update.effective_user.id

    user_settings = await _load_settings(user_id)

    (nearby_stations, nearby_metrobus,
     nearby_trains, nearby_bus) = await _collect_nearby(lat, lon, user_settings)

    if not any((nearby_stations, nearby_metrobus, nearby_trains, nearby_bus)):
        radius_display = max(user_settings["metro_radius_m"], user_settings["bus_radius_m"])
        await safe_edit_message(
            query,
            t("nearby_empty", lang).format(radius=radius_display),
            reply_markup=main_menu_keyboard(lang),
        )
        return

    # Remember context so station/stop detail can navigate back here
    context.user_data["metro_back"] = "nearby:refresh"
    context.user_data["bus_back"] = "nearby:refresh"
    context.user_data["metrobus_back"] = "nearby:refresh"
    context.user_data["train_back"] = "nearby:refresh"

    text, keyboard = _render_nearby(
        lang, user_settings, nearby_stations, nearby_metrobus,
        nearby_trains, nearby_bus,
    )
    await safe_edit_message(query, text, reply_markup=keyboard)


async def _get_nearby_bus_stops(lat: float, lon: float,
                                radius_km: float) -> list[dict]:
    """Try to find nearby bus stops using STCP API."""
    try:
        stops = await stcp.search_nearby_stops(lat, lon, radius_km)
        return stops
    except Exception:
        logger.debug("Nearby bus stop search not available")
        return []
