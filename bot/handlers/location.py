"""Handler for user-sent locations to find nearby stops/stations."""

import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from bot.keyboards.inline import main_menu_keyboard
from bot.services import metro, stcp
from bot.utils.formatting import escape_md
from bot.utils.i18n import t, get_lang

logger = logging.getLogger(__name__)

NEARBY_RADIUS_KM = 0.75  # 750 meters for metro
BUS_NEARBY_RADIUS_KM = 0.4  # 400 meters for bus stops


async def location_handler(update: Update,
                           context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle user-sent location to find nearby stops and stations."""
    loc = update.message.location
    lat = loc.latitude
    lon = loc.longitude
    lang = get_lang(update)

    # Find nearby metro stations
    nearby_stations = metro.get_nearby_stations(lat, lon, NEARBY_RADIUS_KM)

    # Try to find nearby bus stops via STCP API
    nearby_bus = await _get_nearby_bus_stops(lat, lon, BUS_NEARBY_RADIUS_KM)

    if not nearby_stations and not nearby_bus:
        await update.message.reply_text(
            t("nearby_empty", lang).format(radius=int(NEARBY_RADIUS_KM * 1000)),
            parse_mode="MarkdownV2",
            reply_markup=main_menu_keyboard(),
        )
        return

    lines = [t("nearby_title", lang).format(radius=int(NEARBY_RADIUS_KM * 1000))]
    buttons = []

    # Metro stations
    if nearby_stations:
        lines.append(f"\n🚇 *{t('metro_stations', lang)}:*\n")
        for station in nearby_stations[:5]:
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
        for stop in nearby_bus[:5]:
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
