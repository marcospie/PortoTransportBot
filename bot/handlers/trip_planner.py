"""Handler for Trip Planning A→B feature."""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.services.trip_planner import plan_trip, resolve_location, TripOption
from bot.utils.i18n import t, get_lang
from bot.utils.formatting import escape_md

logger = logging.getLogger(__name__)

# Mode emoji map
_MODE_EMOJI = {
    "walk": "🚶",
    "metro": "🚇",
    "bus": "🚌",
    "train": "🚆",
    "metrobus": "🚍",
}


def _format_trip_option(option: TripOption, n: int, lang: str) -> str:
    """Format a single trip option for display."""
    lines = [t("route_option", lang).format(n=n)]
    lines.append(f"⏱ ~{option.total_time_min} min")
    if option.transfers > 0:
        lines.append(f"🔄 {option.transfers} transbordo{'s' if option.transfers > 1 else ''}")
    if option.zones:
        lines.append(f"🎫 Zonas: {', '.join(option.zones)}")
    lines.append("")

    for step in option.steps:
        emoji = _MODE_EMOJI.get(step.mode, "➡️")
        if step.mode == "walk":
            if step.to_name and step.from_name:
                lines.append(f"{emoji} Andar de *{escape_md(step.from_name)}* para *{escape_md(step.to_name)}* \\(~{step.duration_min} min\\)")
            elif step.to_name:
                lines.append(f"{emoji} Andar até *{escape_md(step.to_name)}* \\(~{step.duration_min} min\\)")
            else:
                lines.append(f"{emoji} Andar até ao destino \\(~{step.duration_min} min\\)")
        else:
            line_info = f" \\- {escape_md(step.line)}" if step.line else ""
            direction = f" → {escape_md(step.direction)}" if step.direction else ""
            lines.append(
                f"{emoji} *{escape_md(step.from_name)}* → *{escape_md(step.to_name)}*{line_info}{direction} \\(~{step.duration_min} min\\)"
            )

    return "\n".join(lines)


# ===================================================================
# Enhanced route handler (replaces basic route planning)
# ===================================================================

async def handle_trip_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle text input during trip planning. Returns True if handled."""
    step = context.user_data.get("route_step")
    if not step:
        return False

    text = update.message.text.strip()
    lang = get_lang(update)

    if step == "origin":
        location = resolve_location(text)
        if not location:
            await update.message.reply_text(
                t("route_not_found", lang).format(query=escape_md(text)),
                parse_mode="MarkdownV2",
            )
            return True

        context.user_data["route_origin"] = location
        context.user_data["route_step"] = "dest"

        emoji = _MODE_EMOJI.get(location.get("type", ""), "📍")
        await update.message.reply_text(
            t("route_origin_label", lang).format(
                emoji=emoji,
                name=escape_md(location["name"]),
            ) + "\n\n" + t("route_ask_dest", lang),
            parse_mode="MarkdownV2",
        )
        return True

    elif step == "dest":
        origin = context.user_data.get("route_origin")
        if not origin:
            context.user_data.pop("route_step", None)
            return False

        dest = resolve_location(text)
        if not dest:
            await update.message.reply_text(
                t("route_not_found", lang).format(query=escape_md(text)),
                parse_mode="MarkdownV2",
            )
            return True

        # Clear state
        context.user_data.pop("route_step", None)
        context.user_data.pop("route_origin", None)

        # Plan the trip
        options = plan_trip(origin["name"], text)

        if not options:
            from bot.keyboards.inline import main_menu_keyboard
            await update.message.reply_text(
                t("route_no_direct", lang) + "\n\n" + t("route_tip_metro", lang),
                parse_mode="MarkdownV2",
                reply_markup=main_menu_keyboard(lang),
            )
            return True

        # Format results
        header = t("route_found", lang)
        header += f"\n📍 *{escape_md(origin['name'])}* → *{escape_md(dest['name'])}*\n"

        option_texts = []
        for i, opt in enumerate(options[:3], 1):
            option_texts.append(_format_trip_option(opt, i, lang))

        text_msg = header + "\n" + "\n\n".join(option_texts)

        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(t("route_new", lang), callback_data="plan:route")],
            [InlineKeyboardButton(t("back_main", lang), callback_data="menu:main")],
        ])

        await update.message.reply_text(
            text_msg,
            parse_mode="MarkdownV2",
            reply_markup=keyboard,
        )
        return True

    return False
