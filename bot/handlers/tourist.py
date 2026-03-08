"""Handler for Tourist Mode — curated Porto transport guide."""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.keyboards.inline import (
    tourist_menu_keyboard,
    tourist_category_keyboard,
    tourist_destination_keyboard,
    tourist_tickets_keyboard,
)
from bot.services.tourist import (
    get_category,
    get_destination,
    get_ticket_info,
    TOURIST_POIS,
)
from bot.utils.formatting import escape_md
from bot.utils.i18n import get_lang, t

logger = logging.getLogger(__name__)


# ===================================================================
# Command
# ===================================================================

async def tourist_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /tourist command — show tourist guide menu."""
    lang = get_lang(update)
    await update.message.reply_text(
        t("tourist_title", lang),
        parse_mode="MarkdownV2",
        reply_markup=tourist_menu_keyboard(lang),
    )


# ===================================================================
# Callbacks
# ===================================================================

async def tourist_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the tourist main menu (from inline button)."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)
    await query.edit_message_text(
        t("tourist_title", lang),
        parse_mode="MarkdownV2",
        reply_markup=tourist_menu_keyboard(lang),
    )


async def tourist_category_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show destinations for a tourist category with transport summary."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)

    # Parse: tourist:cat:<category_key>
    parts = query.data.split(":")
    if len(parts) < 3:
        return
    category_key = parts[2]

    # Special handling for tickets
    if category_key == "tickets":
        await _show_ticket_info(query, lang)
        return

    cat = get_category(category_key)
    if not cat:
        return

    emoji = cat["emoji"]
    title = cat["title_pt"] if lang == "pt" else cat["title_en"]

    if not cat.get("destinations"):
        await query.edit_message_text(
            t("tourist_no_destinations", lang),
            parse_mode="MarkdownV2",
            reply_markup=tourist_menu_keyboard(lang),
        )
        return

    # Build message with transport summary for each destination
    text = _format_category_with_transport(cat, emoji, title, lang)

    # Truncate if too long for Telegram
    if len(text) > 4000:
        text = text[:3950] + "\n\n\\.\\.\\. _\\(truncado\\)_"

    await query.edit_message_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=tourist_category_keyboard(category_key, lang),
    )


async def tourist_destination_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show detailed info for a specific tourist destination."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)

    # Parse: tourist:dest:<category_key>:<index>
    parts = query.data.split(":")
    if len(parts) < 4:
        return
    category_key = parts[2]
    try:
        dest_index = int(parts[3])
    except (ValueError, IndexError):
        return

    dest = get_destination(category_key, dest_index)
    if not dest:
        return

    cat = get_category(category_key)
    emoji = cat["emoji"] if cat else "📍"

    text = _format_destination(dest, emoji, lang)

    # Determine station for map button
    station = dest.get("station")
    from bot.services.metro import STATIONS
    map_station = station if station and station in STATIONS else None

    await query.edit_message_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=tourist_destination_keyboard(
            category_key, dest_index, station=map_station, lang=lang
        ),
    )


async def tourist_tickets_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show ticket/Andante information."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)
    await _show_ticket_info(query, lang)


# ===================================================================
# Helpers
# ===================================================================

def _format_category_with_transport(cat: dict, emoji: str, title: str, lang: str) -> str:
    """Format a category overview with compact transport info for each destination."""
    lines = [f"{emoji} *{escape_md(title)}*", "━━━━━━━━━━━━━━━━", ""]

    for dest in cat.get("destinations", []):
        name = dest["name_pt"] if lang == "pt" else dest["name_en"]
        station = dest.get("station", "")
        line_info = dest.get("line", "")
        line_name = dest.get("line_name", "")
        bus_alt = dest.get("bus_alt", "")
        zone = dest.get("zone", "")
        walk_min = dest.get("walk_min", 0)

        lines.append(f"📍 *{escape_md(name)}*")

        if dest.get("best_transport") == "bus":
            transport_line = f"🚌 {escape_md(line_name or line_info)}"
        else:
            transport_line = f"🚇 {escape_md(station)}"
            if line_name:
                transport_line += f" \\— {escape_md(line_name)}"

        lines.append(transport_line)

        if bus_alt and dest.get("best_transport") != "bus":
            if lang == "pt":
                lines.append(f"🚌 Autocarro: {escape_md(bus_alt)}")
            else:
                lines.append(f"🚌 Bus: {escape_md(bus_alt)}")

        extras = []
        if zone:
            extras.append(escape_md(zone))
        if walk_min and walk_min > 0:
            if lang == "pt":
                extras.append(f"~{walk_min} min a pé")
            else:
                extras.append(f"~{walk_min} min walk")
        else:
            if lang == "pt":
                extras.append("saída direta")
            else:
                extras.append("direct exit")

        if extras:
            sep = " \\| "
            lines.append(f"🎫 {sep.join(extras)}")

        # Compact tip
        tip = dest.get("tip_pt" if lang == "pt" else "tip_en", "")
        if tip:
            lines.append(f"💡 _{escape_md(tip)}_")

        lines.append("")

    return "\n".join(lines)


def _format_destination(dest: dict, emoji: str, lang: str) -> str:
    """Format a destination dict into a MarkdownV2 message."""
    name = dest["name_pt"] if lang == "pt" else dest["name_en"]
    lines = [t("tourist_dest_title", lang).format(emoji=emoji, name=escape_md(name))]

    # Best transport
    if dest.get("best_transport") == "bus":
        lines.append(t("tourist_best_transport_bus", lang))
    else:
        lines.append(t("tourist_best_transport", lang))

    # Station
    station = dest.get("station", "")
    lines.append(t("tourist_station", lang).format(station=escape_md(station)))

    # Line
    line_info = dest.get("line", "")
    line_name = dest.get("line_name", "")
    if line_info and line_name:
        lines.append(t("tourist_line", lang).format(line=escape_md(f"{line_info} ({line_name})")))
    elif line_info:
        lines.append(t("tourist_line", lang).format(line=escape_md(line_info)))

    # Bus alternatives
    bus_alt = dest.get("bus_alt", "")
    if bus_alt:
        lines.append(t("tourist_bus_alt", lang).format(buses=escape_md(bus_alt)))

    # Zone
    zone = dest.get("zone", "")
    if zone:
        lines.append(t("tourist_zone", lang).format(zone=escape_md(zone)))

    # Walking time
    walk_min = dest.get("walk_min", 0)
    if walk_min and walk_min > 0:
        lines.append(t("tourist_walk", lang).format(min=walk_min))
    else:
        lines.append(t("tourist_walk_zero", lang))

    # Tip
    tip = dest.get("tip_pt" if lang == "pt" else "tip_en", "")
    if tip:
        lines.append("")
        lines.append(t("tourist_tip", lang).format(tip=escape_md(tip)))

    return "\n".join(lines)


async def _show_ticket_info(query, lang: str) -> None:
    """Display ticket/Andante information."""
    info = get_ticket_info(lang)
    parts = [info["title"], "━━━━━━━━━━━━━━━━", ""]

    for section in info["sections"]:
        parts.append(f"*{section['heading']}*")
        parts.append(section["text"])
        parts.append("")

    text = "\n".join(parts)
    # Truncate if too long
    if len(text) > 4000:
        text = text[:3950] + "\n\n\\.\\.\\. _\\(truncado\\)_"

    await query.edit_message_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=tourist_tickets_keyboard(lang),
    )
