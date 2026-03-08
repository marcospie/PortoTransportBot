"""Handler for Accessibility (Acessibilidade) feature."""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.services.accessibility import (
    get_station_accessibility,
    get_accessible_stations,
    search_accessible_features,
)
from bot.keyboards.inline import (
    accessibility_menu_keyboard,
    accessibility_station_keyboard,
)
from bot.utils.i18n import t, get_lang
from bot.utils.formatting import escape_md

logger = logging.getLogger(__name__)


def _status_text(value: bool, lang: str) -> str:
    """Return a translated status string for a boolean accessibility feature."""
    return escape_md(t("accessibility_status_ok", lang)) if value else escape_md(t("accessibility_status_out", lang))


def _elevator_status_text(data: dict, lang: str) -> str:
    """Return a translated elevator status string."""
    status = data.get("elevator_status", "operational")
    if status == "operational":
        return escape_md(t("accessibility_status_ok", lang))
    elif status == "maintenance":
        return escape_md(t("accessibility_status_maintenance", lang))
    return escape_md(t("accessibility_status_out", lang))


def _format_station_info(data: dict, lang: str) -> str:
    """Format accessibility info for a station into a MarkdownV2 message."""
    station_name = data["name"]

    elevator_line = t("accessibility_elevator", lang).format(
        status=_elevator_status_text(data, lang),
    )
    ramp_line = t("accessibility_ramp", lang).format(
        status=_status_text(data["ramp"], lang),
    )
    tactile_line = t("accessibility_tactile", lang).format(
        status=_status_text(data["tactile"], lang),
    )
    audio_line = t("accessibility_audio", lang).format(
        status=_status_text(data["audio"], lang),
    )
    machines_line = t("accessibility_machines", lang).format(
        status=_status_text(data["accessible_machines"], lang),
    )
    wheelchair_line = t("accessibility_wheelchair", lang).format(
        status=_status_text(data["wheelchair_spaces"], lang),
    )

    text = t("accessibility_station_info", lang).format(
        station=escape_md(station_name),
        elevator=elevator_line,
        ramp=ramp_line,
        tactile=tactile_line,
        audio=audio_line,
        machines=machines_line,
        wheelchair=wheelchair_line,
    )

    notes_key = "notes_pt" if lang == "pt" else "notes_en"
    notes = data.get(notes_key, "")
    if notes:
        text += "\n" + t("accessibility_notes", lang).format(notes=escape_md(notes))

    return text


async def accessibility_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /acessibilidade command."""
    lang = get_lang(update)

    await update.message.reply_text(
        t("accessibility_title", lang),
        parse_mode="MarkdownV2",
        reply_markup=accessibility_menu_keyboard(lang),
    )


async def accessibility_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show accessibility menu."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)
    context.user_data.pop("accessibility_step", None)
    await query.edit_message_text(
        t("accessibility_title", lang),
        parse_mode="MarkdownV2",
        reply_markup=accessibility_menu_keyboard(lang),
    )


async def accessibility_station_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show accessibility info for a specific station."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)

    # Extract station name from callback data: access:station:StationName
    station_name = query.data.split(":", 2)[-1]
    data = get_station_accessibility(station_name)

    if not data:
        await query.edit_message_text(
            t("accessibility_not_found", lang).format(name=escape_md(station_name)),
            parse_mode="MarkdownV2",
            reply_markup=accessibility_menu_keyboard(lang),
        )
        return

    text = _format_station_info(data, lang)
    await query.edit_message_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=accessibility_station_keyboard(data["name"], lang),
    )


async def accessibility_search_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start station search for accessibility info."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)
    context.user_data["accessibility_step"] = "search"
    await query.edit_message_text(
        t("accessibility_search_prompt", lang),
        parse_mode="MarkdownV2",
    )


async def accessibility_elevators_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show elevator status overview."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)

    all_stations = get_accessible_stations()
    maintenance = search_accessible_features("elevator_maintenance")

    total = len(all_stations)
    maint_count = len(maintenance)

    text = t("accessibility_overview", lang).format(
        total=escape_md(str(total)),
        maintenance=escape_md(str(maint_count)),
    )

    if maintenance:
        text += "\n\n🔧 *" + escape_md(
            "Elevadores em manutenção:" if lang == "pt" else "Elevators under maintenance:"
        ) + "*\n"
        for station in maintenance:
            text += f"• {escape_md(station['name'])}\n"

    await query.edit_message_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=accessibility_menu_keyboard(lang),
    )


async def handle_accessibility_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle text input during accessibility station search. Returns True if handled."""
    step = context.user_data.get("accessibility_step")
    if not step:
        return False

    text = update.message.text.strip()
    lang = get_lang(update)

    if step == "search":
        context.user_data.pop("accessibility_step", None)
        data = get_station_accessibility(text)

        if not data:
            await update.message.reply_text(
                t("accessibility_not_found", lang).format(name=escape_md(text)),
                parse_mode="MarkdownV2",
                reply_markup=accessibility_menu_keyboard(lang),
            )
            return True

        msg = _format_station_info(data, lang)
        await update.message.reply_text(
            msg,
            parse_mode="MarkdownV2",
            reply_markup=accessibility_station_keyboard(data["name"], lang),
        )
        return True

    return False
