"""Handler for Accessibility (Acessibilidade) feature."""

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.services import accessibility as accessibility_service
from bot.services.accessibility import (
    get_station_accessibility,
    get_accessible_stations,
    search_accessible_features,
)
from bot.keyboards.inline import (
    accessibility_menu_keyboard,
    accessibility_station_keyboard,
    cancel_keyboard,
)
from bot.utils.i18n import t, get_lang
from bot.utils.formatting import escape_md
from bot.utils.telegram import (
    rows_of,
    safe_callback_button,
    safe_edit_message,
    t_safe,
    truncate_label,
)

logger = logging.getLogger(__name__)

#: How many "did you mean?" buttons to offer when a search finds nothing.
_MAX_SUGGESTIONS = 3


def _status_text(value: bool, lang: str) -> str:
    """Return a translated status string for a boolean accessibility feature."""
    return escape_md(t("accessibility_status_ok", lang)) if value else escape_md(t("accessibility_status_out", lang))


def _live_status_available() -> bool:
    """Whether the service has a real, live lift-status source.

    Read defensively: older revisions of the service exposed no such helper.
    """
    checker = getattr(accessibility_service, "has_live_elevator_status", None)
    if callable(checker):
        try:
            return bool(checker())
        except Exception:  # pragma: no cover - defensive
            logger.debug("has_live_elevator_status() failed", exc_info=True)
    return bool(getattr(accessibility_service,
                        "LIVE_ELEVATOR_STATUS_AVAILABLE", True))


def _elevator_status_text(data: dict, lang: str) -> str:
    """Return a translated elevator status string.

    When there is no live lift-status feed, the value describes the network's
    step-free *design standard*, not a current reading — so it is labelled as
    unverified instead of being presented as fact.
    """
    status = data.get("elevator_status", "operational")
    live = data.get("live_status_available")
    if live is None:
        live = _live_status_available()

    if status == "operational" and not live:
        return escape_md(t_safe(
            "accessibility_status_unverified", lang,
            pt="Existe (estado em tempo real não verificado)",
            en="Provided (live status not verified)",
        ))
    if status == "operational":
        return escape_md(t("accessibility_status_ok", lang))
    if status == "maintenance":
        return escape_md(t("accessibility_status_maintenance", lang))
    return escape_md(t("accessibility_status_out", lang))


def _provenance_line(data: dict, lang: str, notes: str = "") -> str:
    """A short "source · date" footer, honest about where the data came from.

    Skipped when the service's own notes already name the source, so the user
    is not told the same thing twice.
    """
    source = data.get("data_source") or getattr(accessibility_service, "DATA_SOURCE", "")
    date = (data.get("data_date")
            or getattr(accessibility_service, "DATA_SOURCE_DATE", "")
            or getattr(accessibility_service, "DATA_DATE", ""))
    if not source:
        return ""
    if notes and source in notes:
        return ""

    label = t_safe("accessibility_data_source", lang,
                   pt="Fonte", en="Source")
    parts = f"{label}: {source}"
    if date:
        parts += f" · {date}"
    # escape_md handles MarkdownV2 reserved characters; never hand-escape here
    # (escaping a non-reserved char is itself a parse error).
    return f"📄 _{escape_md(parts)}_"


def _format_station_info(data: dict, lang: str) -> str:
    """Format accessibility info for a station into a MarkdownV2 message."""
    station_name = data["name"]

    elevator_line = t("accessibility_elevator", lang).format(
        status=_elevator_status_text(data, lang),
    )
    ramp_line = t("accessibility_ramp", lang).format(
        status=_status_text(data["ramp"], lang),
    )
    tactile_line = t("accessibility_tactile", lang).format(
        status=_status_text(data["tactile"], lang),
    )
    audio_line = t("accessibility_audio", lang).format(
        status=_status_text(data["audio"], lang),
    )
    machines_line = t("accessibility_machines", lang).format(
        status=_status_text(data["accessible_machines"], lang),
    )
    wheelchair_line = t("accessibility_wheelchair", lang).format(
        status=_status_text(data["wheelchair_spaces"], lang),
    )

    text = t("accessibility_station_info", lang).format(
        station=escape_md(station_name),
        elevator=elevator_line,
        ramp=ramp_line,
        tactile=tactile_line,
        audio=audio_line,
        machines=machines_line,
        wheelchair=wheelchair_line,
    )

    notes_key = "notes_pt" if lang == "pt" else "notes_en"
    notes = data.get(notes_key, "")
    if notes:
        text += "\n" + t("accessibility_notes", lang).format(notes=escape_md(notes))

    provenance = _provenance_line(data, lang, notes)
    if provenance:
        text += "\n\n" + provenance

    return text


def _suggestions(name: str) -> list[str]:
    """Closest station names for a query that matched nothing exactly."""
    from bot.utils.search import fuzzy_search

    try:
        candidates = [s["name"] for s in get_accessible_stations()]
    except Exception:  # pragma: no cover - defensive
        logger.exception("Could not list stations for suggestions")
        return []
    matches = fuzzy_search(name, candidates, min_score=15,
                           max_results=_MAX_SUGGESTIONS)
    return [n for n, _score in matches]


def _not_found_view(name: str, lang: str) -> tuple[str, InlineKeyboardMarkup]:
    """Text + keyboard for "station not found", offering the closest matches."""
    text = t("accessibility_not_found", lang).format(name=escape_md(name))

    suggestions = _suggestions(name)
    if not suggestions:
        return text, accessibility_menu_keyboard(lang)

    text += "\n\n" + escape_md(t_safe(
        "accessibility_did_you_mean", lang,
        pt="Será que queres dizer:", en="Did you mean:",
    ))

    buttons = []
    for station in suggestions:
        button = safe_callback_button(
            truncate_label(f"♿ {station}", 32),
            f"access:station:{station}",
        )
        if button is not None:
            buttons.append(button)

    rows = rows_of(buttons, per_row=1)
    rows.append([InlineKeyboardButton(t("kb_accessibility_search", lang),
                                      callback_data="access:search")])
    rows.append([InlineKeyboardButton(t("kb_back", lang),
                                      callback_data="menu:accessibility")])
    return text, InlineKeyboardMarkup(rows)


async def accessibility_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /acessibilidade command."""
    lang = get_lang(update)

    await update.message.reply_text(
        t("accessibility_title", lang),
        parse_mode="MarkdownV2",
        reply_markup=accessibility_menu_keyboard(lang),
    )


async def accessibility_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show accessibility menu."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)
    context.user_data.pop("accessibility_step", None)
    await safe_edit_message(query, t("accessibility_title", lang),
                            reply_markup=accessibility_menu_keyboard(lang))


async def accessibility_station_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show accessibility info for a specific station."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)

    # Extract station name from callback data: access:station:StationName
    station_name = query.data.split(":", 2)[-1]
    data = get_station_accessibility(station_name)

    if not data:
        text, keyboard = _not_found_view(station_name, lang)
        await safe_edit_message(query, text, reply_markup=keyboard)
        return

    text = _format_station_info(data, lang)
    await safe_edit_message(
        query, text,
        reply_markup=accessibility_station_keyboard(data["name"], lang),
    )


async def accessibility_search_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start station search for accessibility info."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)
    context.user_data["accessibility_step"] = "search"
    # The prompt used to have no keyboard at all, leaving the user stuck with
    # no way back other than typing something.
    await safe_edit_message(
        query,
        t("accessibility_search_prompt", lang),
        reply_markup=cancel_keyboard("menu:accessibility", lang),
    )


async def accessibility_elevators_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show what is actually known about lifts across the network."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)

    all_stations = get_accessible_stations()
    maintenance = search_accessible_features("elevator_maintenance")

    total = len(all_stations)
    maint_count = len(maintenance)

    text = t("accessibility_overview", lang).format(
        total=escape_md(str(total)),
        maintenance=escape_md(str(maint_count)),
    )

    if maintenance:
        heading = t_safe("accessibility_elevators_maintenance_heading", lang,
                         pt="Elevadores em manutenção:",
                         en="Elevators under maintenance:")
        text += "\n\n🔧 *" + escape_md(heading) + "*\n"
        for station in maintenance:
            text += f"• {escape_md(station['name'])}\n"
    elif not _live_status_available():
        # No live feed exists: "zero lifts out of service" would be a claim we
        # cannot support, so say what we actually know and where to check.
        text += "\n\n" + escape_md(t_safe(
            "accessibility_no_live_status", lang,
            pt=("Não existe fonte pública com o estado dos elevadores em "
                "tempo real, por isso este bot não o consegue confirmar."),
            en=("There is no public live lift-status feed, so this bot cannot "
                "confirm current lift availability."),
        ))
        note = _source_note(lang)
        if note:
            text += "\n\n" + note

    await safe_edit_message(query, text,
                            reply_markup=accessibility_menu_keyboard(lang))


def _source_note(lang: str) -> str:
    """The service's own provenance note, escaped, when it exposes one."""
    getter = getattr(accessibility_service, "get_data_source_note", None)
    if not callable(getter):
        return ""
    try:
        note = getter(lang)
    except Exception:  # pragma: no cover - defensive
        logger.debug("get_data_source_note() failed", exc_info=True)
        return ""
    return f"📄 _{escape_md(note)}_" if note else ""


async def handle_accessibility_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle text input during accessibility station search. Returns True if handled."""
    step = context.user_data.get("accessibility_step")
    if not step:
        return False

    text = update.message.text.strip()
    lang = get_lang(update)

    if step == "search":
        context.user_data.pop("accessibility_step", None)
        data = get_station_accessibility(text)

        if not data:
            msg, keyboard = _not_found_view(text, lang)
            await update.message.reply_text(
                msg,
                parse_mode="MarkdownV2",
                reply_markup=keyboard,
            )
            return True

        msg = _format_station_info(data, lang)
        await update.message.reply_text(
            msg,
            parse_mode="MarkdownV2",
            reply_markup=accessibility_station_keyboard(data["name"], lang),
        )
        return True

    return False
