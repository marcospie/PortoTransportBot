"""Handler for Events — today's events in Porto with transport info."""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.keyboards.inline import (
    events_today_keyboard,
    events_category_keyboard,
    events_detail_keyboard,
    events_menu_keyboard,
)
from bot.services.events import (
    get_todays_events,
    get_upcoming_events,
    get_events,
    get_event,
    EVENT_CATEGORIES,
)
from bot.utils.formatting import escape_md
from bot.utils.i18n import get_lang, t
from bot.utils.telegram import safe_edit_message, t_safe

logger = logging.getLogger(__name__)


# ===================================================================
# Command
# ===================================================================

async def events_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /eventos command — show today's events."""
    lang = get_lang(update)
    text, keyboard = _build_today_view(lang)
    await update.message.reply_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=keyboard,
    )


# ===================================================================
# Callbacks
# ===================================================================

async def events_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show today's events (from inline button)."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)
    text, keyboard = _build_today_view(lang)
    # Re-tapping the events button must not surface Telegram's
    # "Message is not modified" as an internal error.
    await safe_edit_message(query, text, reply_markup=keyboard)


async def events_categories_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show category filter menu."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)
    await safe_edit_message(query, t("events_title", lang),
                            reply_markup=events_menu_keyboard(lang))


async def events_category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show events for a category."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)

    # Parse: events:cat:<category>
    parts = query.data.split(":")
    if len(parts) < 3:
        return
    category_key = parts[2]

    if category_key == "all":
        events_list = get_events()
        cat_info = {
            "name_pt": t_safe("events_category_all", "pt",
                              pt="Todos os Eventos"),
            "name_en": t_safe("events_category_all", "en",
                              en="All Events"),
            "emoji": "📋",
        }
    else:
        events_list = get_events(category_key)
        cat_info = EVENT_CATEGORIES.get(category_key)
        if not cat_info:
            return

    if not events_list:
        await safe_edit_message(query, t("events_no_events", lang),
                                reply_markup=events_menu_keyboard(lang))
        return

    title = cat_info["name_pt"] if lang == "pt" else cat_info["name_en"]
    emoji = cat_info["emoji"]
    text = t("events_overview", lang).format(emoji=emoji, title=escape_md(title))
    await safe_edit_message(
        query, text,
        reply_markup=events_category_keyboard(events_list, lang),
    )


async def events_detail_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show detailed info for a specific event."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)

    # Parse: events:detail:<index>
    parts = query.data.split(":")
    if len(parts) < 3:
        return
    try:
        event_index = int(parts[2])
    except (ValueError, IndexError):
        return

    event = get_event(event_index)
    if not event:
        return

    name = event.name_pt if lang == "pt" else event.name_en
    venue = event.venue_pt if lang == "pt" else event.venue_en
    date_info = event.date_info_pt if lang == "pt" else event.date_info_en
    tip = event.transport_tip_pt if lang == "pt" else event.transport_tip_en

    text = t("events_detail", lang).format(
        emoji=event.emoji,
        name=escape_md(name),
        venue=escape_md(venue),
        date_info=escape_md(date_info),
        station=escape_md(event.nearest_station),
    )
    text += t("events_transport_tip", lang).format(tip=escape_md(tip))

    await safe_edit_message(
        query, text,
        reply_markup=events_detail_keyboard(event_index, event.category, lang),
    )


# ===================================================================
# Helpers
# ===================================================================

def _build_today_view(lang: str):
    """Build text + keyboard for today's events view."""
    today = get_todays_events()
    upcoming = get_upcoming_events()

    if today:
        text = t("events_today", lang)
        keyboard = events_today_keyboard(today, lang, show_more=bool(upcoming))
    elif upcoming:
        text = t("events_none_today", lang)
        keyboard = events_today_keyboard(upcoming, lang, upcoming=True)
    else:
        text = t("events_none_upcoming", lang)
        keyboard = events_menu_keyboard(lang)

    return text, keyboard
