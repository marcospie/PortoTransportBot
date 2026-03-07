"""Handler for user-sent locations to find nearby stops/stations."""

import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from bot.keyboards.inline import main_menu_keyboard
from bot.services import metro
from bot.utils.formatting import escape_md

logger = logging.getLogger(__name__)

NEARBY_RADIUS_KM = 0.75  # 750 meters


async def location_handler(update: Update,
                           context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle user-sent location to find nearby stops and stations."""
    loc = update.message.location
    lat = loc.latitude
    lon = loc.longitude

    # Find nearby metro stations
    nearby_stations = metro.get_nearby_stations(lat, lon, NEARBY_RADIUS_KM)

    if not nearby_stations:
        await update.message.reply_text(
            f"📍 Não encontrei paragens ou estações num raio de "
            f"{int(NEARBY_RADIUS_KM * 1000)}m da tua localização\\.\n\n"
            "Tenta pesquisar por nome no menu\\.",
            parse_mode="MarkdownV2",
            reply_markup=main_menu_keyboard(),
        )
        return

    lines = [
        f"📍 *Estações de metro perto de ti* "
        f"\\(raio {int(NEARBY_RADIUS_KM * 1000)}m\\)\n",
    ]

    buttons = []
    for station in nearby_stations:
        name = station["name"]
        dist = station["distance_m"]
        lines_emojis = " ".join(l["emoji"] for l in station["lines"])
        lines.append(
            f"  🚇 *{escape_md(name)}* \\- {dist}m\n"
            f"      {lines_emojis}"
        )
        label = f"🚇 {name} ({dist}m)"
        if len(label) > 50:
            label = f"🚇 {name[:30]}... ({dist}m)"
        buttons.append([
            InlineKeyboardButton(label, callback_data=f"metro:station:{name}")
        ])

    buttons.append([InlineKeyboardButton("🔙 Menu principal", callback_data="menu:main")])

    text = "\n\n".join(lines)
    await update.message.reply_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
