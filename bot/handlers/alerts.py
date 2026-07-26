"""Service alerts handler for Porto transport."""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.keyboards.inline import alerts_keyboard
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
from bot.utils.telegram import mark_active_button, safe_edit_message

logger = logging.getLogger(__name__)

# Emoji mappings for alert types
_TYPE_EMOJI = {
    TYPE_DELAY: "⏳",       # hourglass
    TYPE_DISRUPTION: "⚠️",  # warning
    TYPE_ENGINEERING: "\U0001f6a7",    # construction
    TYPE_INFO: "ℹ️",        # info
}

# Emoji mappings for severity
_SEVERITY_EMOJI = {
    SEVERITY_HIGH: "\U0001f534",    # red circle
    SEVERITY_MEDIUM: "\U0001f7e0",  # orange circle
    SEVERITY_LOW: "\U0001f7e2",     # green circle
}

#: The filter shown when the user has not narrowed anything down.
_DEFAULT_FILTER = "all"


def _format_alert(alert: dict, lang: str = "pt") -> str:
    """Format a single alert for display."""
    type_emoji = _TYPE_EMOJI.get(alert.get("type", TYPE_INFO), "ℹ️")
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


def format_alerts_message(alerts: list[dict], lang: str = "pt",
                          filter_type: str | None = None,
                          source_available: bool = True) -> str:
    """Format a list of alerts into a complete message.

    Three empty states are deliberately distinguished, because conflating them
    told users things that were not true:

    * ``source_available=False`` -> we could not check. Never claim "all
      normal" when nothing could be consulted.
    * empty *and* a type filter is applied -> "no alerts of this type". Saying
      "all services running normally" while three disruptions of another type
      are one tap away is simply wrong.
    * empty with no filter -> genuinely no alerts reported.
    """
    if not source_available:
        return t("alerts_source_unavailable", lang)

    if not alerts:
        if filter_type and filter_type != _DEFAULT_FILTER:
            return t("no_alerts_of_type", lang)
        return t("no_alerts", lang)

    title = t("alerts_title", lang)
    separator = "━" * 16

    parts = [f"{title}\n{separator}\n"]

    for alert in alerts:
        parts.append(_format_alert(alert, lang))
        parts.append("")  # blank line between alerts

    return "\n".join(parts)


def _filtered_keyboard(lang: str, filter_type: str = _DEFAULT_FILTER):
    """Alerts keyboard with the active filter visibly marked."""
    return mark_active_button(alerts_keyboard(lang),
                              f"alerts:filter:{filter_type}")


async def _load_alerts() -> tuple[list[dict], bool]:
    """Fetch alerts, returning ``(alerts, source_available)``.

    ``bot.services.alerts.get_active_alerts`` returns an ``AlertsResult`` (a
    list subclass carrying ``source_available``). Plain lists and dict-shaped
    results are also accepted so this handler keeps working whichever contract
    the service exposes, and a service-level crash degrades to "could not
    check" rather than "Erro interno".
    """
    try:
        result = await get_active_alerts()
    except Exception:
        logger.exception("Could not load service alerts")
        return [], False

    if isinstance(result, dict):
        alerts = list(result.get("alerts") or [])
        available = result.get("source_available")
        if available is None:
            available = not (result.get("error") or result.get("unavailable"))
        return alerts, bool(available)

    alerts = list(result or [])
    # Plain lists (including test doubles) are assumed to have come from a
    # reachable source; only an explicit flag says otherwise.
    return alerts, bool(getattr(result, "source_available", True))


async def alertas_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /alertas command - show active service alerts."""
    lang = get_lang(update)
    alerts, available = await _load_alerts()
    msg = format_alerts_message(alerts, lang, source_available=available)

    await update.message.reply_text(
        msg,
        parse_mode="MarkdownV2",
        reply_markup=_filtered_keyboard(lang),
    )


async def alerts_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle menu:alerts callback - show alerts from menu (also the refresh)."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)

    alerts, available = await _load_alerts()
    msg = format_alerts_message(alerts, lang, source_available=available)

    await safe_edit_message(query, msg, reply_markup=_filtered_keyboard(lang))


async def alerts_filter_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle alerts:filter:<type> callback - filter alerts by type."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)

    filter_type = query.data.split(":")[-1]  # e.g. "delay", "disruption", "all"

    alerts, available = await _load_alerts()

    if filter_type != _DEFAULT_FILTER:
        alerts = [a for a in alerts if a.get("type") == filter_type]

    msg = format_alerts_message(alerts, lang, filter_type=filter_type,
                                source_available=available)

    await safe_edit_message(query, msg,
                            reply_markup=_filtered_keyboard(lang, filter_type))
