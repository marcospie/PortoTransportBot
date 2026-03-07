"""Start and help command handlers."""

import logging

from telegram import KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.handlers.favorites import _load_favorites
from bot.keyboards.inline import main_menu_keyboard, favorites_keyboard
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
    context.user_data.pop("awaiting_bus_search", None)
    context.user_data.pop("awaiting_bus_code", None)
    context.user_data.pop("awaiting_metro_search", None)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command with persistent keyboard and favorites."""
    lang = get_lang(update)
    _clear_awaiting(context)

    # Send persistent reply keyboard
    await update.message.reply_text(
        "⌨️",
        reply_markup=_reply_keyboard(lang),
    )

    # Check if user has favorites (returning user)
    user_id = update.effective_user.id
    favs = _load_favorites(user_id)

    if favs:
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
            reply_markup=favorites_keyboard(favs),
        )
    else:
        await update.message.reply_text(
            t("welcome", lang),
            parse_mode="MarkdownV2",
            reply_markup=main_menu_keyboard(),
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    lang = get_lang(update)
    await update.message.reply_text(
        t("help", lang),
        parse_mode="MarkdownV2",
        reply_markup=main_menu_keyboard(),
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
        reply_markup=main_menu_keyboard(),
    )


async def help_callback(update: Update,
                         context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)
    await query.edit_message_text(
        t("help", lang),
        parse_mode="MarkdownV2",
        reply_markup=main_menu_keyboard(),
    )
