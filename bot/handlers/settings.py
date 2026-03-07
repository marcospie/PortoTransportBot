"""Handler for user settings / preferences."""

import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from bot.database import get_user_settings, update_user_setting, DEFAULT_SETTINGS
from bot.utils.i18n import t, get_lang

logger = logging.getLogger(__name__)

# Predefined radius options (in meters)
METRO_RADIUS_OPTIONS = [200, 500, 1000, 1500]
BUS_RADIUS_OPTIONS = [100, 200, 400, 600]
MAX_RESULTS_OPTIONS = [3, 5, 8, 10]
LANGUAGE_OPTIONS = [("auto", "Automático / Auto"), ("pt", "Português"), ("en", "English")]


def _settings_menu_keyboard(settings: dict, lang: str) -> InlineKeyboardMarkup:
    """Build the main settings menu."""
    metro_r = settings["metro_radius_m"]
    bus_r = settings["bus_radius_m"]
    max_r = settings["max_results"]
    lang_val = settings["language"]
    lang_label = next((l[1] for l in LANGUAGE_OPTIONS if l[0] == lang_val), lang_val)

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            t("settings_metro_radius", lang).format(value=metro_r),
            callback_data="settings:metro_radius",
        )],
        [InlineKeyboardButton(
            t("settings_bus_radius", lang).format(value=bus_r),
            callback_data="settings:bus_radius",
        )],
        [InlineKeyboardButton(
            t("settings_max_results", lang).format(value=max_r),
            callback_data="settings:max_results",
        )],
        [InlineKeyboardButton(
            t("settings_language", lang).format(value=lang_label),
            callback_data="settings:language",
        )],
        [InlineKeyboardButton(
            t("settings_reset", lang),
            callback_data="settings:reset",
        )],
        [InlineKeyboardButton(t("back_main", lang), callback_data="menu:main")],
    ])


def _radius_options_keyboard(setting_key: str, options: list[int],
                             current: int, lang: str) -> InlineKeyboardMarkup:
    """Build a keyboard to pick a radius value."""
    buttons = []
    row = []
    for val in options:
        label = f"{val}m"
        if val == current:
            label = f"• {val}m •"
        row.append(InlineKeyboardButton(label, callback_data=f"settings:set:{setting_key}:{val}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(t("back", lang), callback_data="menu:settings")])
    return InlineKeyboardMarkup(buttons)


def _max_results_keyboard(current: int, lang: str) -> InlineKeyboardMarkup:
    """Build a keyboard to pick max results."""
    buttons = []
    row = []
    for val in MAX_RESULTS_OPTIONS:
        label = str(val)
        if val == current:
            label = f"• {val} •"
        row.append(InlineKeyboardButton(label, callback_data=f"settings:set:max_results:{val}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(t("back", lang), callback_data="menu:settings")])
    return InlineKeyboardMarkup(buttons)


def _language_keyboard(current: str, lang: str) -> InlineKeyboardMarkup:
    """Build a keyboard to pick language."""
    buttons = []
    for code, label in LANGUAGE_OPTIONS:
        if code == current:
            label = f"• {label} •"
        buttons.append([InlineKeyboardButton(label, callback_data=f"settings:set:language:{code}")])
    buttons.append([InlineKeyboardButton(t("back", lang), callback_data="menu:settings")])
    return InlineKeyboardMarkup(buttons)


# ===================================================================
# Command
# ===================================================================

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /settings command."""
    user_id = update.effective_user.id
    lang = get_lang(update)
    settings = await get_user_settings(user_id)

    await update.message.reply_text(
        t("settings_title", lang),
        parse_mode="MarkdownV2",
        reply_markup=_settings_menu_keyboard(settings, lang),
    )


# ===================================================================
# Callbacks
# ===================================================================

async def settings_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show settings menu (from inline button)."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    lang = get_lang(update)
    settings = await get_user_settings(user_id)

    await query.edit_message_text(
        t("settings_title", lang),
        parse_mode="MarkdownV2",
        reply_markup=_settings_menu_keyboard(settings, lang),
    )


async def settings_option_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show options for a specific setting."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    lang = get_lang(update)
    settings = await get_user_settings(user_id)

    setting_key = query.data.replace("settings:", "")

    if setting_key == "metro_radius":
        text = t("settings_pick_metro_radius", lang)
        kb = _radius_options_keyboard("metro_radius_m", METRO_RADIUS_OPTIONS,
                                      settings["metro_radius_m"], lang)
    elif setting_key == "bus_radius":
        text = t("settings_pick_bus_radius", lang)
        kb = _radius_options_keyboard("bus_radius_m", BUS_RADIUS_OPTIONS,
                                      settings["bus_radius_m"], lang)
    elif setting_key == "max_results":
        text = t("settings_pick_max_results", lang)
        kb = _max_results_keyboard(settings["max_results"], lang)
    elif setting_key == "language":
        text = t("settings_pick_language", lang)
        kb = _language_keyboard(settings["language"], lang)
    else:
        return

    await query.edit_message_text(text, parse_mode="MarkdownV2", reply_markup=kb)


async def settings_set_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Apply a setting value."""
    query = update.callback_query
    user_id = update.effective_user.id
    lang = get_lang(update)

    # Parse: settings:set:<key>:<value>
    parts = query.data.split(":")
    if len(parts) != 4:
        await query.answer("?")
        return

    key = parts[2]
    raw_value = parts[3]

    # Convert value to appropriate type
    if key in ("metro_radius_m", "bus_radius_m", "max_results"):
        value = int(raw_value)
    else:
        value = raw_value

    await update_user_setting(user_id, key, value)
    await query.answer(t("settings_saved", lang))

    # Refresh settings menu
    settings = await get_user_settings(user_id)
    await query.edit_message_text(
        t("settings_title", lang),
        parse_mode="MarkdownV2",
        reply_markup=_settings_menu_keyboard(settings, lang),
    )


async def settings_reset_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reset all settings to defaults."""
    query = update.callback_query
    user_id = update.effective_user.id
    lang = get_lang(update)

    for key, value in DEFAULT_SETTINGS.items():
        await update_user_setting(user_id, key, value)

    await query.answer(t("settings_reset_done", lang))

    settings = await get_user_settings(user_id)
    await query.edit_message_text(
        t("settings_title", lang),
        parse_mode="MarkdownV2",
        reply_markup=_settings_menu_keyboard(settings, lang),
    )
