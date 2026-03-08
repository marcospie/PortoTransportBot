"""Handler for Events — upcoming events in Porto with transport info."""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.keyboards.inline import (
    events_menu_keyboard,
    events_category_keyboard,
    events_detail_keyboard,
)
from bot.services.events import (
    get_events,
    get_event,
    EVENT_CATEGORIES,
)
from bot.utils.formatting import escape_md
from bot.utils.i18n import get_lang, t

logger = logging.getLogger(__name__)


# ===================================================================
# Command
# ===================================================================

async def events_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /eventos command — show events menu."""
    lang = get_lang(update)
    await update.message.reply_text(
        t("events_title", lang),
        parse_mode="MarkdownV2",
        reply_markup=events_menu_keyboard(lang),
    )


# ===================================================================
# Callbacks
# ===================================================================

async def events_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the events main menu (from inline button)."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)
    await query.edit_message_text(
        t("events_title", lang),
        parse_mode="MarkdownV2",
        reply_markup=events_menu_keyboard(lang),
    )


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
        cat_info = {"name_pt": "Todos os Eventos", "name_en": "All Events", "emoji": "📋"}
    else:
        events_list = get_events(category_key)
        cat_info = EVENT_CATEGORIES.get(category_key)
        if not cat_info:
            return

    if not events_list:
        await query.edit_message_text(
            t("events_no_events", lang),
            parse_mode="MarkdownV2",
            reply_markup=events_menu_keyboard(lang),
        )
        return

    title = cat_info["name_pt"] if lang == "pt" else cat_info["name_en"]
    emoji = cat_info["emoji"]
    text = t("events_overview", lang).format(emoji=emoji, title=escape_md(title))
    await query.edit_message_text(
        text,
        parse_mode="MarkdownV2",
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

    await query.edit_message_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=events_detail_keyboard(event_index, event.category, lang),
    )
