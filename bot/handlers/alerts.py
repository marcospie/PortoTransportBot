"""Service alerts handler for Porto transport."""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.keyboards.inline import alerts_keyboard, main_menu_keyboard
from bot.services.alerts import (
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    SEVERITY_LOW,
    TYPE_DELAY,
    TYPE_DISRUPTION,
    TYPE_ENGINEERING,
    TYPE_INFO,
    get_active_alerts,
)
from bot.utils.formatting import escape_md
from bot.utils.i18n import get_lang, t

logger = logging.getLogger(__name__)

# Emoji mappings for alert types
_TYPE_EMOJI = {
    TYPE_DELAY: "\u23f3",       # hourglass
    TYPE_DISRUPTION: "\u26a0\ufe0f",  # warning
    TYPE_ENGINEERING: "\U0001f6a7",    # construction
    TYPE_INFO: "\u2139\ufe0f",        # info
}

# Emoji mappings for severity
_SEVERITY_EMOJI = {
    SEVERITY_HIGH: "\U0001f534",    # red circle
    SEVERITY_MEDIUM: "\U0001f7e0",  # orange circle
    SEVERITY_LOW: "\U0001f7e2",     # green circle
}


def _format_alert(alert: dict, lang: str = "pt") -> str:
    """Format a single alert for display."""
    type_emoji = _TYPE_EMOJI.get(alert.get("type", TYPE_INFO), "\u2139\ufe0f")
    severity_emoji = _SEVERITY_EMOJI.get(alert.get("severity", SEVERITY_LOW), "\U0001f7e2")
    severity_label = t(f"alert_severity_{alert.get('severity', SEVERITY_LOW)}", lang)

    lines_part = ""
    affected = alert.get("affected_lines", [])
    if affected:
        lines_str = ", ".join(escape_md(l) for l in affected)
        lines_label = t("alert_lines", lang)
        lines_part = f"\n{lines_label} {lines_str}"

    title = escape_md(alert.get("title", ""))
    description = escape_md(alert.get("description", ""))

    return (
        f"{type_emoji} {severity_emoji} *{title}*\n"
        f"_{severity_label}_\n"
        f"{description}"
        f"{lines_part}"
    )


def format_alerts_message(alerts: list[dict], lang: str = "pt") -> str:
    """Format a list of alerts into a complete message."""
    if not alerts:
        return t("no_alerts", lang)

    title = t("alerts_title", lang)
    separator = "\u2501" * 16

    parts = [f"{title}\n{separator}\n"]

    for alert in alerts:
        parts.append(_format_alert(alert, lang))
        parts.append("")  # blank line between alerts

    return "\n".join(parts)


async def alertas_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /alertas command - show active service alerts."""
    lang = get_lang(update)
    alerts = await get_active_alerts()
    msg = format_alerts_message(alerts, lang)

    await update.message.reply_text(
        msg,
        parse_mode="MarkdownV2",
        reply_markup=alerts_keyboard(lang),
    )


async def alerts_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle menu:alerts callback - show alerts from menu."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)

    alerts = await get_active_alerts()
    msg = format_alerts_message(alerts, lang)

    await query.edit_message_text(
        msg,
        parse_mode="MarkdownV2",
        reply_markup=alerts_keyboard(lang),
    )


async def alerts_filter_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle alerts:filter:<type> callback - filter alerts by type."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)

    filter_type = query.data.split(":")[-1]  # e.g. "delay", "disruption", "all"

    alerts = await get_active_alerts()

    if filter_type != "all":
        alerts = [a for a in alerts if a.get("type") == filter_type]

    msg = format_alerts_message(alerts, lang)

    await query.edit_message_text(
        msg,
        parse_mode="MarkdownV2",
        reply_markup=alerts_keyboard(lang),
    )
