"""CP Comboios (trains) related handlers."""

import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.database import is_favorite
from bot.handlers.start import _clear_awaiting
from bot.keyboards.inline import (
    trains_menu_keyboard,
    train_station_results_keyboard,
    train_station_actions_keyboard,
    train_lines_keyboard,
)
from bot.services import cp
from bot.services.cp import CP_LINES, STATIONS
from bot.utils.formatting import escape_md, format_metro_schedule
from bot.utils.i18n import get_lang, t
from bot.utils.telegram import safe_edit_message

logger = logging.getLogger(__name__)

AWAITING_TRAIN_SEARCH = "awaiting_train_search"

#: Callback data for the "Frequências" view.  It deliberately reuses the
#: already-registered ``^train:line:.+$`` pattern (see bot/main.py) so the
#: button works without touching the router; ``train_line_callback`` routes it.
FREQ_CALLBACK = "train:line:freq"

# Fallback copy for i18n keys that may not exist yet.  ``t()`` returns the raw
# key when a string is missing, which would leak "trains_realtime_note" into a
# message, so every new key goes through :func:`_t` with a safe default.
_FALLBACK_STRINGS: dict[str, dict[str, str]] = {
    "trains_realtime_note": {
        "pt": "_\U0001f7e2 Horário oficial CP \\(via GTFS da CP\\)_",
        "en": "_\U0001f7e2 Official CP timetable \\(from CP's GTFS feed\\)_",
    },
    "trains_frequency_disclaimer": {
        "pt": ("_⚠️ Frequência típica — não é horário real\\. "
               "Horário da CP indisponível neste momento\\._"),
        "en": ("_⚠️ Typical frequency — not a real timetable\\. "
               "CP's schedule is unavailable right now\\._"),
    },
    "trains_every_n_min": {
        "pt": "a cada ~{n} min",
        "en": "every ~{n} min",
    },
    "kb_frequencies": {
        "pt": "\U0001f550 Frequências",
        "en": "\U0001f550 Frequencies",
    },
    "trains_freq_title": {
        "pt": "\U0001f550 *Frequências CP*",
        "en": "\U0001f550 *CP Frequencies*",
    },
    "trains_peak": {"pt": "Hora de ponta", "en": "Peak"},
    "trains_offpeak": {"pt": "Fora de ponta", "en": "Off\\-peak"},
    "trains_weekend": {"pt": "Fim de semana", "en": "Weekend"},
    "trains_schedule": {"pt": "\U0001f552 Horário:", "en": "\U0001f552 Hours:"},
    "trains_stations_label": {"pt": "estações", "en": "stations"},
    "trains_type_label": {"pt": "Tipo", "en": "Type"},
    "trains_closed": {
        "pt": "\U0001f31a *Serviço encerrado*",
        "en": "\U0001f31a *Service closed*",
    },
    "trains_closed_hours": {
        "pt": "Os comboios funcionam das {start} às {end}\\.",
        "en": "Trains run from {start} to {end}\\.",
    },
}


def _t(key: str, lang: str = "pt", **kwargs) -> str:
    """Translate ``key``, falling back to a local default if it is missing.

    ``bot.utils.i18n.t()`` returns the raw key for unknown keys.  New keys are
    listed in :data:`_FALLBACK_STRINGS` so the UI still reads correctly until
    they are added to i18n.
    """
    value = t(key, lang)
    if value == key:
        fallbacks = _FALLBACK_STRINGS.get(key, {})
        value = fallbacks.get(lang) or fallbacks.get("pt") or key
    if kwargs:
        try:
            value = value.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            pass
    return value


def _trains_menu_keyboard(lang: str = "pt") -> InlineKeyboardMarkup:
    """Trains menu with the "Frequências" entry metro/metrobus already have.

    Built locally because bot/keyboards/inline.py is owned elsewhere; it mirrors
    ``trains_menu_keyboard()`` and appends the frequencies button.
    """
    try:
        base = list(trains_menu_keyboard(lang).inline_keyboard)
    except Exception:  # pragma: no cover - defensive
        logger.exception("Falling back to a minimal trains menu keyboard")
        base = [[InlineKeyboardButton(t("kb_train_lines", lang),
                                      callback_data="train:lines")]]

    freq_button = InlineKeyboardButton(_t("kb_frequencies", lang),
                                       callback_data=FREQ_CALLBACK)
    rows = [list(row) for row in base]
    # Insert just above the trailing "back to main menu" row.
    insert_at = max(0, len(rows) - 1)
    rows.insert(insert_at, [freq_button])
    return InlineKeyboardMarkup(rows)


def _line_stations_label(count: int, lang: str) -> str:
    return f"{count} " + _t("trains_stations_label", lang)


def _localize_estimates(departures: list[dict], lang: str) -> None:
    """Rewrite frequency-estimate times through i18n (in place)."""
    for dep in departures:
        interval = dep.get("interval_min")
        if interval:
            dep["time"] = _t("trains_every_n_min", lang, n=interval)


def _departures_note(departures: list[dict], lang: str) -> str:
    """Honest one-line provenance note for a departures list."""
    if not departures:
        return ""
    if any(d.get("closed") for d in departures):
        return ""
    if any(d.get("estimated") for d in departures):
        return _t("trains_frequency_disclaimer", lang)
    return _t("trains_realtime_note", lang)


def _closed_text(lang: str) -> str:
    return (
        _t("trains_closed", lang) + "\n\n"
        + _t(
            "trains_closed_hours", lang,
            start=escape_md(cp.OPERATING_HOURS["start"].strftime("%H:%M")),
            end=escape_md(cp.OPERATING_HOURS["end"].strftime("%H:%M")),
        )
    )


def _format_station_text(station_name: str, line_info_str: str,
                         departures: list[dict], lang: str) -> str:
    """Render a station's departure board with an honest provenance note."""
    if departures and any(d.get("closed") for d in departures):
        return _closed_text(lang)

    _localize_estimates(departures, lang)
    text = format_metro_schedule(cp.display_name(station_name),
                                 line_info_str, departures)
    # Replace the metro emoji with a train emoji in the header
    text = text.replace("\U0001f687 *", "\U0001f686 *", 1)

    note = _departures_note(departures, lang)
    if note:
        text += f"\n\n{note}"
    return text


async def _fetch_departures(station_name: str, line_id: str | None = None,
                            count: int = 6) -> list[dict]:
    """Real CP timetable with a graceful fallback to frequency estimates."""
    try:
        return await cp.get_next_departures_async(station_name, line_id, count)
    except Exception:
        logger.exception("Failed to load departures for %s", station_name)
        try:
            return cp.get_next_departures(station_name, line_id, count)
        except Exception:
            logger.exception("Frequency fallback also failed for %s",
                             station_name)
            return []


async def trains_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /comboios command."""
    lang = get_lang(update)
    await update.message.reply_text(
        t("trains_title", lang),
        parse_mode="MarkdownV2",
        reply_markup=_trains_menu_keyboard(lang),
    )


async def estacao_command(update: Update,
                          context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /estacao <name> command for quick station lookup."""
    lang = get_lang(update)
    if not context.args:
        await update.message.reply_text(
            t("trains_station_usage", lang),
            parse_mode="MarkdownV2",
        )
        return

    query = " ".join(context.args)
    await _search_and_show_stations(update.message, query, context, lang=lang)


async def trains_menu_callback(update: Update,
                                context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show trains menu."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)
    _clear_awaiting(context)
    context.user_data.pop("train_back", None)
    await safe_edit_message(
        query,
        t("trains_title", lang),
        reply_markup=_trains_menu_keyboard(lang),
    )


async def train_search_callback(update: Update,
                                 context: ContextTypes.DEFAULT_TYPE) -> None:
    """Redirect user to inline mode for live station autocomplete."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)
    _clear_awaiting(context)
    await safe_edit_message(
        query,
        t("trains_search_title", lang),
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton(t("trains_search_button", lang),
                                  switch_inline_query_current_chat="train ")],
            [InlineKeyboardButton(t("kb_back", lang), callback_data="menu:trains")],
        ]),
    )


def _lines_list_keyboard(lang: str = "pt") -> InlineKeyboardMarkup:
    """Lines keyboard plus a "Frequências" shortcut (inline.py is not ours)."""
    try:
        base = [list(row) for row in train_lines_keyboard(lang).inline_keyboard]
    except Exception:  # pragma: no cover - defensive
        logger.exception("Falling back to a minimal train lines keyboard")
        base = [[InlineKeyboardButton(t("kb_back", lang),
                                      callback_data="menu:trains")]]
    freq_button = InlineKeyboardButton(_t("kb_frequencies", lang),
                                       callback_data=FREQ_CALLBACK)
    base.insert(max(0, len(base) - 1), [freq_button])
    return InlineKeyboardMarkup(base)


async def train_lines_callback(update: Update,
                                context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show all CP train lines."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)

    all_lines = cp.get_all_lines()
    lines_text = []
    for line in all_lines:
        type_label = f"\\({escape_md(line['type'])}\\)"
        lines_text.append(
            f"{line['emoji']} *{escape_md(line['name'])}* {type_label}\n"
            f"   \U0001f4cd {escape_md(line['route'])}\n"
            f"   \\({escape_md(_line_stations_label(line['station_count'], lang))}\\)"
        )

    lines_joined = "\n\n".join(lines_text)
    text = t("trains_lines_title", lang).format(lines=lines_joined)

    await safe_edit_message(query, text, reply_markup=_lines_list_keyboard(lang))


async def train_freq_callback(update: Update,
                               context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show typical frequency information for every CP line.

    These numbers are estimates, so the view says so explicitly instead of
    pretending to be a timetable.
    """
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)

    blocks = []
    for line_id, data in CP_LINES.items():
        freq = cp.get_frequency_info(line_id)
        blocks.append(
            f"{data['emoji']} *{escape_md(data['name'])}*\n"
            f"   {escape_md(_t('trains_peak', lang))}: {escape_md(freq['peak'])}\n"
            f"   {escape_md(_t('trains_offpeak', lang))}: {escape_md(freq['off_peak'])}\n"
            f"   {escape_md(_t('trains_weekend', lang))}: {escape_md(freq['weekend'])}"
        )

    hours = cp.get_frequency_info("aveiro")["hours"]
    text = (
        _t("trains_freq_title", lang) + "\n\n"
        + "\n\n".join(blocks)
        + f"\n\n{_t('trains_schedule', lang)} {escape_md(hours)}"
        + f"\n\n{_t('trains_frequency_disclaimer', lang)}"
    )

    await safe_edit_message(query, text,
                            reply_markup=_trains_menu_keyboard(lang))


async def train_line_callback(update: Update,
                               context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show line details with stations."""
    query = update.callback_query
    lang = get_lang(update)

    line_id = query.data.split(":")[-1]
    if line_id == "freq":
        return await train_freq_callback(update, context)

    await query.answer(t("loading", lang))

    try:
        line_data = CP_LINES.get(line_id)
        if not line_data:
            await safe_edit_message(
                query,
                t("trains_line_not_found", lang),
                reply_markup=_lines_list_keyboard(lang),
            )
            return

        stations = cp.get_line_stations(line_id)
        emoji = line_data.get("emoji", "\U0001f686")
        name = line_data.get("name", line_id)
        route = line_data.get("route", "")
        line_type = line_data.get("type", "")

        lines = [f"{emoji} *{escape_md(name)}*"]
        if route:
            lines.append(f"_{escape_md(route)}_")
        if line_type:
            lines.append(
                f"{escape_md(_t('trains_type_label', lang))}: "
                f"{escape_md(line_type)}\n"
            )

        for i, station_name in enumerate(stations):
            escaped_name = escape_md(cp.display_name(station_name))
            if i == 0 or i == len(stations) - 1:
                lines.append(f"  {emoji} *{escaped_name}*")
            else:
                lines.append(f"  {emoji} {escaped_name}")
            if i < len(stations) - 1:
                lines.append("  │")

        lines.append(
            f"\n\U0001f4ca {escape_md(_line_stations_label(len(stations), lang))}"
        )

        text = "\n".join(lines)
        if len(text) > 4000:
            text = text[:3950] + "\n\n\\.\\.\\. _\\(lista truncada\\)_"

        # Build keyboard with key stations
        buttons = []
        key_stations = []
        if stations:
            key_stations.append(stations[0])
            if len(stations) > 2:
                mid = len(stations) // 2
                key_stations.append(stations[mid])
            if stations[-1] not in key_stations:
                key_stations.append(stations[-1])

        row = []
        for sname in key_stations[:6]:
            label = f"{emoji} {cp.display_name(sname)}"
            if len(label) > 40:
                label = f"{emoji} {cp.display_name(sname)[:32]}..."
            cb_data = f"train:station:{sname}"
            if len(cb_data.encode("utf-8")) <= 64:
                row.append(InlineKeyboardButton(label, callback_data=cb_data))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)

        buttons.append([InlineKeyboardButton(t("kb_back", lang), callback_data="train:lines")])

        await safe_edit_message(query, text,
                                reply_markup=InlineKeyboardMarkup(buttons))
    except Exception:
        logger.exception("Error in train_line_callback for %s", line_id)
        await safe_edit_message(
            query,
            t("error_load_train_line", lang),
            reply_markup=_lines_list_keyboard(lang),
        )


async def train_station_callback(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show station departures (real CP timetable, estimates only as fallback)."""
    query = update.callback_query
    lang = get_lang(update)
    await query.answer(t("loading", lang))

    station_name = query.data.split(":", 2)[-1]
    try:
        user_id = query.from_user.id
        is_fav = await is_favorite(user_id, "train", station_name)
        departures = await _fetch_departures(station_name)

        resolved = cp.resolve_station_name(station_name) or station_name
        station_data = STATIONS.get(resolved, {})
        lines_info = []
        for lid in station_data.get("lines", []):
            ld = CP_LINES.get(lid, {})
            train_emoji = ld.get('emoji', '\U0001f686')
            train_name = ld.get('name', lid)
            lines_info.append(f"{train_emoji} {train_name}")
        line_info_str = " \\| ".join(escape_md(l) for l in lines_info) if lines_info else ""

        text = _format_station_text(station_name, line_info_str, departures, lang)

        back_cb = context.user_data.get("train_back", "menu:trains")
        await safe_edit_message(
            query,
            text,
            reply_markup=train_station_actions_keyboard(
                station_name, is_fav=is_fav, lang=lang, back_callback=back_cb),
        )
    except Exception:
        logger.exception("Error in train_station_callback for %s", station_name)
        await safe_edit_message(
            query,
            t("error_load_train_station", lang).format(
                name=escape_md(cp.display_name(station_name))),
            reply_markup=_trains_menu_keyboard(lang),
        )


async def train_station_lines_callback(update: Update,
                                        context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show lines for a specific station."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)

    station_name = query.data.split(":", 2)[-1]
    user_id = query.from_user.id
    is_fav = await is_favorite(user_id, "train", station_name)
    info = cp.get_station_info(station_name)

    if not info:
        await safe_edit_message(
            query,
            t("train_station_not_found", lang).format(
                name=escape_md(station_name)),
            reply_markup=_trains_menu_keyboard(lang),
        )
        return

    lines_text = []
    for line in info["lines"]:
        lines_text.append(
            f"{line['emoji']} *{escape_md(line['name'])}*\n"
            f"   \U0001f4cd {escape_md(line['route'])}\n"
            f"   {escape_md(_t('trains_type_label', lang))}: "
            f"{escape_md(line['type'])}"
        )

    header = escape_md(info.get("display") or info["name"])
    text = f"\U0001f686 *{header}*\n\n" + "\n\n".join(lines_text)

    await safe_edit_message(
        query,
        text,
        reply_markup=train_station_actions_keyboard(station_name, is_fav=is_fav, lang=lang),
    )


async def train_location_callback(update: Update,
                                   context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send station location on the map."""
    query = update.callback_query
    lang = get_lang(update)
    await query.answer(t("loading_location", lang))

    station_name = query.data.split(":", 2)[-1]
    try:
        user_id = query.from_user.id
        is_fav = await is_favorite(user_id, "train", station_name)
        await query.edit_message_reply_markup(reply_markup=None)
        info = cp.get_station_info(station_name)
        if info and info.get("lat") and info.get("lon"):
            await context.bot.send_location(
                chat_id=query.message.chat_id,
                latitude=info["lat"],
                longitude=info["lon"],
            )
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"\U0001f4cd *{escape_md(info.get('display') or info['name'])}*",
                parse_mode="MarkdownV2",
                reply_markup=train_station_actions_keyboard(station_name, is_fav=is_fav, lang=lang),
            )
        else:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=t("location_unavailable", lang).format(id=escape_md(station_name)),
                parse_mode="MarkdownV2",
            )
    except Exception:
        logger.exception("Error sending train station location for %s", station_name)
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=t("error_location", lang),
            parse_mode="MarkdownV2",
        )


async def handle_train_text_input(update: Update,
                                   context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle text input for train station search. Returns True if handled."""
    ts = context.user_data.get(AWAITING_TRAIN_SEARCH)
    lang = get_lang(update)
    if ts and isinstance(ts, datetime) and (datetime.now() - ts).total_seconds() < 300:
        context.user_data.pop(AWAITING_TRAIN_SEARCH, None)
        query = update.message.text.strip()
        await _search_and_show_stations(update.message, query, context, lang=lang)
        return True
    elif ts is True:
        context.user_data.pop(AWAITING_TRAIN_SEARCH, None)
        query = update.message.text.strip()
        await _search_and_show_stations(update.message, query, context, lang=lang)
        return True
    context.user_data.pop(AWAITING_TRAIN_SEARCH, None)
    return False


async def _search_and_show_stations(message, query: str, context=None, lang: str = "pt") -> None:
    """Search for CP stations and show results."""
    stations = cp.search_stations(query)

    if not stations:
        await message.reply_text(
            t("no_train_stations_found", lang).format(query=escape_md(query)),
            parse_mode="MarkdownV2",
            reply_markup=_trains_menu_keyboard(lang),
        )
        return

    if len(stations) == 1:
        station = stations[0]
        departures = await _fetch_departures(station["name"])

        lines_info = []
        for l in station["lines"]:
            lines_info.append(f"{l['emoji']} {l['name']}")
        line_info_str = " \\| ".join(escape_md(li) for li in lines_info)

        text = _format_station_text(station["name"], line_info_str,
                                    departures, lang)

        user_id = message.from_user.id if message.from_user else None
        is_fav = await is_favorite(user_id, "train", station["name"]) if user_id else False
        await message.reply_text(
            text,
            parse_mode="MarkdownV2",
            reply_markup=train_station_actions_keyboard(station["name"], is_fav=is_fav, lang=lang),
        )
        return

    await message.reply_text(
        t("trains_results_for", lang).format(query=escape_md(query)),
        parse_mode="MarkdownV2",
        reply_markup=train_station_results_keyboard(stations, lang=lang),
    )
