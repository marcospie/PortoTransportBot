"""Start and help command handlers."""

import logging

from telegram import KeyboardButton, MenuButtonCommands, ReplyKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.database import get_favorites
from bot.keyboards.inline import main_menu_keyboard, favorites_keyboard, onboarding_keyboard
from bot.utils.formatting import escape_md
from bot.utils.i18n import get_lang, t

logger = logging.getLogger(__name__)


def _reply_keyboard(lang: str = "pt") -> ReplyKeyboardMarkup:
    """Build persistent reply keyboard with location button."""
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(t("kb_nearby", lang), request_location=True)],
            [
                KeyboardButton(t("kb_favorites", lang)),
                KeyboardButton(t("kb_help", lang)),
            ],
        ],
        resize_keyboard=True,
    )


def _clear_awaiting(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Clear all AWAITING_* flags from user data."""
    for key in list(context.user_data.keys()):
        if key.startswith("awaiting_"):
            context.user_data.pop(key, None)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command with persistent keyboard, deep links, and onboarding."""
    lang = get_lang(update)
    _clear_awaiting(context)

    # Ensure this chat has the commands menu button active
    try:
        chat_id = update.effective_chat.id
        await context.bot.set_chat_menu_button(
            chat_id=chat_id, menu_button=MenuButtonCommands()
        )
    except Exception:
        pass

    # --- Deep link support ---
    if context.args:
        payload = context.args[0]
        if payload.startswith("stop_"):
            stop_id = payload[5:].upper()
            from bot.handlers.bus import _send_stop_realtime
            await _send_stop_realtime(update.message, stop_id, context, lang=lang)
            return
        if payload.startswith("station_"):
            station_name = payload[8:]
            from bot.handlers.metro import _search_and_show_stations
            await _search_and_show_stations(update.message, station_name, context, lang=lang)
            return

    # Send persistent reply keyboard
    await update.message.reply_text(
        "⌨️",
        reply_markup=_reply_keyboard(lang),
    )

    # Check if user has favorites (returning user)
    user_id = update.effective_user.id

    # Load onboarding state from database if not already in session
    if not context.user_data.get("onboarded"):
        try:
            from bot.database import is_user_onboarded
            if await is_user_onboarded(user_id):
                context.user_data["onboarded"] = True
        except Exception:
            pass

    favs = await get_favorites(user_id)

    if favs:
        # Returning user with favorites
        fav_lines = [t("welcome_with_favs", lang)]
        for fav in favs[:5]:
            if fav["type"] == "bus":
                fav_lines.append(f"  🚌 {escape_md(fav.get('name', fav['id']))} \\(`{escape_md(fav['id'])}`\\)")
            else:
                fav_lines.append(f"  🚇 {escape_md(fav.get('name', fav['id']))}")
        text = "\n".join(fav_lines)
        await update.message.reply_text(
            text,
            parse_mode="MarkdownV2",
            reply_markup=favorites_keyboard(favs, lang=lang),
        )
    elif not context.user_data.get("onboarded"):
        # First-time user - show onboarding
        context.user_data["onboarded"] = True
        await update.message.reply_text(
            t("onboard_welcome", lang),
            parse_mode="MarkdownV2",
            reply_markup=onboarding_keyboard(lang),
        )
    else:
        # Returning user without favorites
        await update.message.reply_text(
            t("welcome", lang),
            parse_mode="MarkdownV2",
            reply_markup=main_menu_keyboard(lang),
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    lang = get_lang(update)
    await update.message.reply_text(
        t("help", lang),
        parse_mode="MarkdownV2",
        reply_markup=main_menu_keyboard(lang),
    )


async def main_menu_callback(update: Update,
                              context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)
    _clear_awaiting(context)
    await query.edit_message_text(
        t("welcome", lang),
        parse_mode="MarkdownV2",
        reply_markup=main_menu_keyboard(lang),
    )


async def help_callback(update: Update,
                         context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)
    await query.edit_message_text(
        t("help", lang),
        parse_mode="MarkdownV2",
        reply_markup=main_menu_keyboard(lang),
    )
