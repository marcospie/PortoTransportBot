"""Handler for user settings / preferences."""

import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from bot.database import get_user_settings, update_user_setting, DEFAULT_SETTINGS
from bot.utils.i18n import t, resolve_lang, set_lang_preference
from bot.utils.telegram import safe_edit_message

logger = logging.getLogger(__name__)

# Predefined radius options (in meters)
METRO_RADIUS_OPTIONS = [200, 500, 1000, 1500]
BUS_RADIUS_OPTIONS = [100, 200, 400, 600]
MAX_RESULTS_OPTIONS = [3, 5, 8, 10]
LANGUAGE_OPTIONS = [("auto", "Automático / Auto"), ("pt", "Português"), ("en", "English")]
NOTIFICATION_OPTIONS = ["on", "off"]

# The `notifications` setting is owned by bot/database.py. If that key is not
# available yet we simply hide the toggle instead of offering a button that
# cannot be saved.
NOTIFICATIONS_KEY = "notifications"


def _notifications_supported(settings: dict | None = None) -> bool:
    """True when the storage layer knows about the notifications setting."""
    if NOTIFICATIONS_KEY in DEFAULT_SETTINGS:
        return True
    return bool(settings) and NOTIFICATIONS_KEY in settings


def _notifications_value(settings: dict) -> str:
    """Current notifications value, normalised to 'on'/'off'."""
    raw = settings.get(NOTIFICATIONS_KEY,
                       DEFAULT_SETTINGS.get(NOTIFICATIONS_KEY, "off"))
    if isinstance(raw, bool):
        return "on" if raw else "off"
    return "on" if str(raw).lower() in ("on", "true", "1", "yes") else "off"


def _notifications_label(value: str, lang: str) -> str:
    key = "settings_notifications_on" if value == "on" else "settings_notifications_off"
    return t(key, lang)


def _settings_menu_keyboard(settings: dict, lang: str) -> InlineKeyboardMarkup:
    """Build the main settings menu."""
    metro_r = settings["metro_radius_m"]
    bus_r = settings["bus_radius_m"]
    max_r = settings["max_results"]
    lang_val = settings["language"]
    lang_label = next((l[1] for l in LANGUAGE_OPTIONS if l[0] == lang_val), lang_val)

    rows = [
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
    ]

    if _notifications_supported(settings):
        notif_value = _notifications_value(settings)
        # One-tap toggle. Uses the already-registered `settings:set:*` route so
        # no new callback registration is required.
        rows.append([InlineKeyboardButton(
            t("settings_notifications", lang).format(
                value=_notifications_label(notif_value, lang)),
            callback_data=f"settings:set:{NOTIFICATIONS_KEY}:toggle",
        )])

    rows.append([InlineKeyboardButton(
        t("settings_reset", lang),
        callback_data="settings:reset",
    )])
    rows.append([InlineKeyboardButton(t("back_main", lang), callback_data="menu:main")])

    return InlineKeyboardMarkup(rows)


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


def _notifications_keyboard(current: str, lang: str) -> InlineKeyboardMarkup:
    """Build a keyboard to turn proactive notifications on or off."""
    row = []
    for value in NOTIFICATION_OPTIONS:
        label = _notifications_label(value, lang)
        if value == current:
            label = f"• {label} •"
        row.append(InlineKeyboardButton(
            label, callback_data=f"settings:set:{NOTIFICATIONS_KEY}:{value}"))
    buttons = [row]
    buttons.append([InlineKeyboardButton(t("back", lang), callback_data="menu:settings")])
    return InlineKeyboardMarkup(buttons)


# ===================================================================
# Command
# ===================================================================

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /settings command."""
    user_id = update.effective_user.id
    lang = await resolve_lang(update)
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
    lang = await resolve_lang(update)
    settings = await get_user_settings(user_id)

    await safe_edit_message(
        query,
        t("settings_title", lang),
        reply_markup=_settings_menu_keyboard(settings, lang),
    )


async def settings_option_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show options for a specific setting."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    lang = await resolve_lang(update)
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
    elif setting_key == NOTIFICATIONS_KEY:
        text = t("settings_pick_notifications", lang)
        kb = _notifications_keyboard(_notifications_value(settings), lang)
    else:
        return

    await safe_edit_message(query, text, reply_markup=kb)


async def settings_set_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Apply a setting value."""
    query = update.callback_query
    user_id = update.effective_user.id

    # Parse: settings:set:<key>:<value>
    parts = query.data.split(":")
    if len(parts) != 4:
        await query.answer()
        return

    key = parts[2]
    raw_value = parts[3]

    # Convert value to appropriate type
    if key in ("metro_radius_m", "bus_radius_m", "max_results"):
        try:
            value = int(raw_value)
        except ValueError:
            await query.answer()
            return
    elif key == NOTIFICATIONS_KEY and raw_value == "toggle":
        current = await get_user_settings(user_id)
        value = "off" if _notifications_value(current) == "on" else "on"
    else:
        value = raw_value

    try:
        await update_user_setting(user_id, key, value)
    except ValueError:
        # Storage layer does not know this setting (yet) - do not blow up in
        # the user's face, just fall through and redraw the menu.
        logger.warning("Setting %r not supported by storage layer", key)
    except Exception:
        logger.exception("Could not save setting %r for user %s", key, user_id)

    # Write the new language straight through to the i18n cache so the redraw
    # below (and every subsequent message) is already in the chosen language.
    if key == "language":
        set_lang_preference(user_id, value)

    lang = await resolve_lang(update)
    await query.answer(t("settings_saved", lang))

    # Refresh settings menu
    settings = await get_user_settings(user_id)
    await safe_edit_message(
        query,
        t("settings_title", lang),
        reply_markup=_settings_menu_keyboard(settings, lang),
    )


async def settings_reset_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Reset all settings to defaults."""
    query = update.callback_query
    user_id = update.effective_user.id

    for key, value in DEFAULT_SETTINGS.items():
        try:
            await update_user_setting(user_id, key, value)
        except Exception:
            logger.exception("Could not reset setting %r for user %s", key, user_id)

    # Language went back to its default ('auto') - keep the cache in sync.
    set_lang_preference(user_id, DEFAULT_SETTINGS.get("language", "auto"))

    lang = await resolve_lang(update)
    await query.answer(t("settings_reset_done", lang))

    settings = await get_user_settings(user_id)
    await safe_edit_message(
        query,
        t("settings_title", lang),
        reply_markup=_settings_menu_keyboard(settings, lang),
    )
