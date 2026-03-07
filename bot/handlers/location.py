"""Handler for user-sent locations to find nearby stops/stations."""

import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from bot.database import get_user_settings
from bot.keyboards.inline import main_menu_keyboard
from bot.services import metro, stcp
from bot.utils.formatting import escape_md
from bot.utils.i18n import t, get_lang

logger = logging.getLogger(__name__)

# Defaults (used when settings are not available)
NEARBY_RADIUS_KM = 0.5  # 500 meters for metro
BUS_NEARBY_RADIUS_KM = 0.2  # 200 meters for bus stops


async def location_handler(update: Update,
                           context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle user-sent location to find nearby stops and stations."""
    loc = update.message.location
    lat = loc.latitude
    lon = loc.longitude
    lang = get_lang(update)
    user_id = update.effective_user.id

    # Load user settings for radius (fall back to defaults on error)
    try:
        user_settings = await get_user_settings(user_id)
    except Exception:
        logger.debug("Could not load user settings, using defaults")
        from bot.database import DEFAULT_SETTINGS
        user_settings = DEFAULT_SETTINGS
    metro_radius_km = user_settings["metro_radius_m"] / 1000
    bus_radius_km = user_settings["bus_radius_m"] / 1000
    max_results = user_settings["max_results"]

    # Find nearby metro stations
    nearby_stations = metro.get_nearby_stations(lat, lon, metro_radius_km)

    # Try to find nearby bus stops via STCP API
    nearby_bus = await _get_nearby_bus_stops(lat, lon, bus_radius_km)

    if not nearby_stations and not nearby_bus:
        radius_display = max(user_settings["metro_radius_m"], user_settings["bus_radius_m"])
        await update.message.reply_text(
            t("nearby_empty", lang).format(radius=radius_display),
            parse_mode="MarkdownV2",
            reply_markup=main_menu_keyboard(),
        )
        return

    radius_display = max(user_settings["metro_radius_m"], user_settings["bus_radius_m"])
    lines = [t("nearby_title", lang).format(radius=radius_display)]
    buttons = []

    # Metro stations
    if nearby_stations:
        lines.append(f"\n🚇 *{t('metro_stations', lang)}:*\n")
        for station in nearby_stations[:max_results]:
            name = station["name"]
            dist = station["distance_m"]
            lines_emojis = " ".join(l_["emoji"] for l_ in station["lines"])
            lines_names = " ".join(f'{l_["emoji"]}{l_["code"]}' for l_ in station["lines"])
            lines.append(
                f"  🚇 *{escape_md(name)}* \\- {dist}m\n"
                f"      {lines_names}"
            )
            label = f"🚇 {name} ({dist}m)"
            if len(label) > 50:
                label = f"🚇 {name[:30]}... ({dist}m)"
            buttons.append([
                InlineKeyboardButton(label, callback_data=f"metro:station:{name}")
            ])

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
            buttons.append([
                InlineKeyboardButton(label, callback_data=f"bus:stop:{stop_id}")
            ])

    buttons.append([InlineKeyboardButton(
        t("back_main", lang), callback_data="menu:main"
    )])

    text = "\n".join(lines)
    await update.message.reply_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def _get_nearby_bus_stops(lat: float, lon: float,
                                radius_km: float) -> list[dict]:
    """Try to find nearby bus stops using STCP API."""
    try:
        stops = await stcp.search_nearby_stops(lat, lon, radius_km)
        return stops
    except Exception:
        logger.debug("Nearby bus stop search not available")
        return []
