"""Weather handler for Porto transport."""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.keyboards.inline import weather_keyboard
from bot.services.weather import get_weather_info, get_transport_tip
from bot.utils.formatting import escape_md
from bot.utils.i18n import get_lang, t
from bot.utils.telegram import safe_edit_message

logger = logging.getLogger(__name__)


async def _format_weather_message(lang: str = "pt") -> str:
    """Format the weather overview message."""
    info = await get_weather_info()

    title = t("weather_title", lang)
    separator = "\u2501" * 16

    temp_label = t("weather_temp", lang)
    rain_label = t("weather_rain", lang)
    sunrise_label = t("weather_sunrise", lang)
    sunset_label = t("weather_sunset", lang)
    tip_label = t("weather_tip", lang)

    description = info["description_pt"] if lang == "pt" else info["description_en"]
    tip = get_transport_tip(lang)

    emoji = info["emoji"]

    text = (
        f"{emoji} *{escape_md(title)}*\n"
        f"{separator}\n\n"
        f"_{escape_md(description)}_\n\n"
        f"\U0001f321\ufe0f {escape_md(temp_label)}: *{info['temp_now']}\u00b0C* "
        f"\\({info['temp_min']}\u00b0C \\- {info['temp_max']}\u00b0C\\)\n"
        f"\U0001f327\ufe0f {escape_md(rain_label)}: *{info['rain_prob']}%*\n"
        f"\U0001f4a8 {escape_md('Vento' if lang == 'pt' else 'Wind')}: *{info['wind']} km/h*\n"
        f"\U0001f4a7 {escape_md('Humidade' if lang == 'pt' else 'Humidity')}: *{info['humidity']}%*\n"
        f"\U0001f305 {escape_md(sunrise_label)}: *{escape_md(info['sunrise'])}*\n"
        f"\U0001f307 {escape_md(sunset_label)}: *{escape_md(info['sunset'])}*\n\n"
        f"\U0001f4a1 {escape_md(tip_label)}: {escape_md(tip)}"
    )

    return text


async def weather_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /meteo command - show weather overview for Porto."""
    lang = get_lang(update)
    msg = await _format_weather_message(lang)

    await update.message.reply_text(
        msg,
        parse_mode="MarkdownV2",
        reply_markup=weather_keyboard(lang),
    )


async def weather_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle menu:weather callback - show weather from menu."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)

    msg = await _format_weather_message(lang)

    # Tapping "refresh" before the forecast changes produces an identical
    # message; Telegram calls that an error, the user must not.
    await safe_edit_message(query, msg, reply_markup=weather_keyboard(lang))
