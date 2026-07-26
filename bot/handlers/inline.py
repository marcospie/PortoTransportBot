"""Inline query handler for sharing transport info and autocomplete search."""

import asyncio
import logging
import re
import uuid

from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup,
    InlineQueryResultArticle, InputTextMessageContent, Update,
)
from telegram.ext import ContextTypes

from bot.services import stcp
from bot.services.stcp import search_stops_local
from bot.services.metro import search_stations, get_next_departures
from bot.services.metrobus import search_stops as search_metrobus_stops
from bot.services.cp import search_stations as search_train_stations
from bot.utils.formatting import escape_md
from bot.utils.i18n import TRANSLATIONS, t

logger = logging.getLogger(__name__)

# Pattern for queries that look like bus stop codes
_CODE_PATTERN = re.compile(r"^[A-Za-z]{2,6}\d{0,2}$")

# Query prefixes that narrow the search to a single transport mode.
# Order matters: "metrobus " must be tested before "metro ".
_MODE_PREFIXES = (
    ("metrobus ", "metrobus"),
    ("metro ", "metro"),
    ("bus ", "bus"),
    ("train ", "train"),
)

# Every user-visible string in inline mode goes through _t().  These defaults
# keep the wording correct for keys that are not in bot.utils.i18n yet -- once
# the keys land there, i18n wins automatically.
_FALLBACKS: dict[str, dict[str, str]] = {
    "pt": {
        "inline_hint_quick_title": "🔍 Pesquisa rápida",
        "inline_hint_quick_desc": "Escreve o nome de uma paragem ou estação...",
        "inline_hint_quick_detail": "Exemplo: Bolhão, Trindade, Casa da Música",
        "inline_hint_bus_title": "🚌 Pesquisar autocarros",
        "inline_hint_bus_desc": "Escreve 'bus' seguido do nome da paragem",
        "inline_hint_bus_detail": "Exemplo: bus Bolhão",
        "inline_hint_metro_title": "🚇 Pesquisar metro",
        "inline_hint_metro_desc": "Escreve 'metro' seguido do nome da estação",
        "inline_hint_metro_detail": "Exemplo: metro Trindade",
        "inline_hint_metrobus_title": "\U0001f68d Pesquisar MetroBus",
        "inline_hint_metrobus_desc": "Escreve 'metrobus' seguido do nome da paragem",
        "inline_hint_metrobus_detail": "Exemplo: metrobus Boavista",
        "inline_hint_train_title": "\U0001f686 Pesquisar comboios",
        "inline_hint_train_desc": "Escreve 'train' seguido do nome da estação",
        "inline_hint_train_detail": "Exemplo: train Campanhã",
        "inline_typing_bus_title": "🚌 Pesquisar paragem",
        "inline_typing_bus_desc": "Continua a escrever o nome ou código...",
        "inline_typing_bus_detail": "Exemplo: Bolhão, BCM2",
        "inline_typing_metro_title": "🚇 Pesquisar estação",
        "inline_typing_metro_desc": "Continua a escrever o nome da estação...",
        "inline_typing_metro_detail": "Exemplo: Trindade, Bolhão",
        "inline_typing_metrobus_title": "\U0001f68d Pesquisar MetroBus",
        "inline_typing_metrobus_desc": "Continua a escrever o nome da paragem...",
        "inline_typing_metrobus_detail": "Exemplo: Boavista, Campanhã",
        "inline_typing_train_title": "\U0001f686 Pesquisar estação CP",
        "inline_typing_train_desc": "Continua a escrever o nome da estação...",
        "inline_typing_train_detail": "Exemplo: Campanhã, Ermesinde",
        "inline_no_results_title": "🤔 Sem resultados",
        "inline_no_results_desc": "Nenhum resultado para '{query}'",
        "inline_no_results_detail": "Tenta outro nome ou código",
        "inline_view_times": "🕐 Ver horários",
        "inline_zone": "Zona {zone}",
        "inline_bus_stop": "Paragem {code}",
        "inline_lines": "Linhas",
        "inline_bus_arrivals": "{count} autocarros - toca para partilhar",
        "inline_bus_no_arrivals": "Sem autocarros previstos",
        "inline_metrobus_label": "MetroBus",
        "inline_train_label": "Comboios CP",
    },
    "en": {
        "inline_hint_quick_title": "🔍 Quick search",
        "inline_hint_quick_desc": "Type the name of a stop or station...",
        "inline_hint_quick_detail": "Example: Bolhão, Trindade, Casa da Música",
        "inline_hint_bus_title": "🚌 Search buses",
        "inline_hint_bus_desc": "Type 'bus' followed by the stop name",
        "inline_hint_bus_detail": "Example: bus Bolhão",
        "inline_hint_metro_title": "🚇 Search metro",
        "inline_hint_metro_desc": "Type 'metro' followed by the station name",
        "inline_hint_metro_detail": "Example: metro Trindade",
        "inline_hint_metrobus_title": "\U0001f68d Search MetroBus",
        "inline_hint_metrobus_desc": "Type 'metrobus' followed by the stop name",
        "inline_hint_metrobus_detail": "Example: metrobus Boavista",
        "inline_hint_train_title": "\U0001f686 Search trains",
        "inline_hint_train_desc": "Type 'train' followed by the station name",
        "inline_hint_train_detail": "Example: train Campanhã",
        "inline_typing_bus_title": "🚌 Search stop",
        "inline_typing_bus_desc": "Keep typing the name or code...",
        "inline_typing_bus_detail": "Example: Bolhão, BCM2",
        "inline_typing_metro_title": "🚇 Search station",
        "inline_typing_metro_desc": "Keep typing the station name...",
        "inline_typing_metro_detail": "Example: Trindade, Bolhão",
        "inline_typing_metrobus_title": "\U0001f68d Search MetroBus",
        "inline_typing_metrobus_desc": "Keep typing the stop name...",
        "inline_typing_metrobus_detail": "Example: Boavista, Campanhã",
        "inline_typing_train_title": "\U0001f686 Search CP station",
        "inline_typing_train_desc": "Keep typing the station name...",
        "inline_typing_train_detail": "Example: Campanhã, Ermesinde",
        "inline_no_results_title": "🤔 No results",
        "inline_no_results_desc": "No results for '{query}'",
        "inline_no_results_detail": "Try another name or code",
        "inline_view_times": "🕐 See times",
        "inline_zone": "Zone {zone}",
        "inline_bus_stop": "Stop {code}",
        "inline_lines": "Lines",
        "inline_bus_arrivals": "{count} buses - tap to share",
        "inline_bus_no_arrivals": "No buses expected",
        "inline_metrobus_label": "MetroBus",
        "inline_train_label": "CP trains",
    },
}


def _t(key: str, lang: str = "pt") -> str:
    """Translate ``key``, falling back to this module's own wording.

    ``bot.utils.i18n.t`` returns the key itself when a translation is missing;
    that would leak raw keys into the user's face, so fall back to the local
    table instead.
    """
    value = t(key, lang)
    if value != key:
        return value
    table = _FALLBACKS.get(lang) or _FALLBACKS["pt"]
    return table.get(key, _FALLBACKS["pt"].get(key, key))


def _inline_lang(inline_query) -> str:
    """Detect the requesting user's language from the inline query itself.

    ``get_lang`` needs an ``Update.effective_user``, which is not what an
    inline query carries, so read ``inline_query.from_user`` directly.
    """
    user = getattr(inline_query, "from_user", None)
    code = getattr(user, "language_code", None)
    if isinstance(code, str) and code:
        lang = code[:2].lower()
        if lang in TRANSLATIONS:
            return lang
    return "pt"


def _zone_suffix(zone: str, lang: str) -> str:
    """Return a ' · Zona X' suffix, or an empty string when unknown."""
    if not zone:
        return ""
    return " · " + _t("inline_zone", lang).format(zone=zone)


async def inline_query_handler(update: Update,
                                context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline queries: @BotName <query>."""
    # Do not strip the trailing space yet: the mode prefixes ("bus ", "metro
    # ", ...) are exactly what the switch_inline_query buttons pre-fill, and
    # stripping first made every one of them fall through to a literal search.
    raw_query = update.inline_query.query.lstrip()
    lang = _inline_lang(update.inline_query)
    results = []

    if not raw_query.strip():
        # Show usage hints
        for mode in ("quick", "bus", "metro", "train"):
            results.append(_hint_article(
                _t(f"inline_hint_{mode}_title", lang),
                _t(f"inline_hint_{mode}_desc", lang),
                _t(f"inline_hint_{mode}_detail", lang),
            ))
        await update.inline_query.answer(results, cache_time=300,
                                          is_personal=True)
        return

    # Check for prefix routing
    mode = "all"
    query = raw_query.strip()
    lowered = raw_query.lower()
    for prefix, prefix_mode in _MODE_PREFIXES:
        if lowered.startswith(prefix):
            mode = prefix_mode
            query = raw_query[len(prefix):].strip()
            break
        # A bare mode word ("metro" with no trailing space yet) is a mode
        # selection too, not something to search for.
        if lowered.strip() == prefix.strip():
            mode = prefix_mode
            query = ""
            break

    if not query:
        if mode != "all":
            results.append(_hint_article(
                _t(f"inline_typing_{mode}_title", lang),
                _t(f"inline_typing_{mode}_desc", lang),
                _t(f"inline_typing_{mode}_detail", lang),
            ))
        await update.inline_query.answer(results, cache_time=300,
                                          is_personal=True)
        return

    if mode in ("all", "bus"):
        await _add_bus_stops_quick(query, results, lang=lang)

    if mode in ("all", "metro"):
        _add_metro_stations_quick(query, results, lang=lang)

    if mode in ("all", "metrobus"):
        _add_metrobus_stops_quick(query, results, lang=lang)

    if mode in ("all", "train"):
        _add_train_stations_quick(query, results, lang=lang)

    if not results:
        results.append(_hint_article(
            _t("inline_no_results_title", lang),
            _t("inline_no_results_desc", lang).format(query=query),
            _t("inline_no_results_detail", lang),
        ))

    # Results depend on the requesting user's language, so they must never be
    # cached across users.
    await update.inline_query.answer(results[:15], cache_time=5,
                                      is_personal=True)


def _hint_article(title: str, description: str, detail: str) -> InlineQueryResultArticle:
    """Create a hint/placeholder article."""
    return InlineQueryResultArticle(
        id=str(uuid.uuid4()),
        title=title,
        description=description,
        input_message_content=InputTextMessageContent(
            message_text=escape_md(detail),
            parse_mode="MarkdownV2",
        ),
    )


def _times_button(callback_data: str, lang: str) -> InlineKeyboardMarkup | None:
    """Build a "see times" button, or None if callback_data is too long.

    Telegram rejects callback_data over 64 bytes, and accented station names
    are multi-byte in UTF-8, so this is checked rather than assumed.
    """
    if len(callback_data.encode("utf-8")) > 64:
        return None
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(_t("inline_view_times", lang),
                              callback_data=callback_data)],
    ])


async def _add_bus_stop_by_code(stop_code: str, results: list,
                                 lang: str = "pt") -> None:
    """Look up a bus stop by its code and append results."""
    try:
        data = await stcp.get_stop_real_time(stop_code)
        arrivals = data.get("arrivals", [])
        stop_name = data.get("stop_name", stop_code)

        if arrivals or stop_name != stop_code:
            lines = [f"🚏 *{escape_md(stop_name)}*  `{escape_md(stop_code)}`\n"]
            for arr in arrivals[:5]:
                line_num = escape_md(str(arr.get("line", "?")))
                dest = escape_md(str(arr.get("destination", "?")))
                time_val = escape_md(str(arr.get("time", "?")))
                lines.append(f"  🚌 *{line_num}* → {dest}")
                lines.append(f"      ⏱ {time_val}")

            text = "\n".join(lines)
            desc = (_t("inline_bus_arrivals", lang).format(count=len(arrivals))
                    if arrivals
                    else _t("inline_bus_no_arrivals", lang))
            results.append(InlineQueryResultArticle(
                id=str(uuid.uuid4()),
                title=f"🚌 " + _t("inline_bus_stop", lang).format(code=stop_code),
                description=desc,
                input_message_content=InputTextMessageContent(
                    message_text=text,
                    parse_mode="MarkdownV2",
                ),
                reply_markup=_times_button(f"bus:stop:{stop_code}", lang),
            ))
    except Exception:
        logger.exception("Error looking up bus stop by code: %s", stop_code)


async def _add_bus_stops_quick(query: str, results: list,
                                lang: str = "pt") -> None:
    """Search bus stops by name or code - quick mode for autocomplete.

    Uses local GTFS data for instant results, falls back to API,
    and finally tries direct stop code lookups.
    """
    try:
        # Local fuzzy search first (instant, no API call)
        stops = search_stops_local(query, max_results=8)
        if not stops:
            stops = await stcp.search_stops(query)

        if stops:
            for stop in stops[:8]:
                _append_bus_stop_result(stop, results, lang=lang)
            return

        # No results from name search — try direct stop code lookup
        # if the query looks like a stop code (e.g. ASP, BIBG, TRN1)
        if _CODE_PATTERN.match(query):
            await _try_stop_code_lookups(query, results, lang=lang)

    except Exception:
        logger.exception("Error searching bus stops for query: %s", query)


def _append_bus_stop_result(stop: dict, results: list,
                             lang: str = "pt") -> None:
    """Append a single bus stop to inline results."""
    stop_code = stop.get("code", stop.get("stop_id", ""))
    stop_name = stop.get("name", "")
    zone_text = _zone_suffix(stop.get("zone", ""), lang)

    text = f"🚏 *{escape_md(stop_name)}*  `{escape_md(stop_code)}`"
    if zone_text:
        text += f"\n{escape_md(zone_text.lstrip(' ·').strip())}"

    results.append(InlineQueryResultArticle(
        id=str(uuid.uuid4()),
        title=f"🚌 {stop_name}",
        description=_t("inline_bus_stop", lang).format(code=stop_code) + zone_text,
        input_message_content=InputTextMessageContent(
            message_text=text,
            parse_mode="MarkdownV2",
        ),
        # A tappable button instead of "type /stop CODE yourself".
        reply_markup=_times_button(f"bus:stop:{stop_code}", lang),
    ))


async def _try_stop_code_lookups(query: str, results: list,
                                  lang: str = "pt") -> None:
    """Try looking up bus stops by code prefix (e.g. ASP → ASP1, ASP2, ...).

    When GTFS data isn't loaded and the API name search returns nothing,
    this tries common stop code patterns as a last resort.
    """
    code_base = query.strip().upper()

    # If query already ends with a digit, try it directly
    if code_base[-1].isdigit():
        candidates = [code_base]
    else:
        # Try appending common suffixes: 1, 2, 3, ..., L1, L2
        candidates = [f"{code_base}{i}" for i in range(1, 7)]
        candidates.extend([f"{code_base}L{i}" for i in range(1, 3)])

    # Try all candidates concurrently (with short timeout)
    async def _probe(code: str) -> dict | None:
        try:
            data = await stcp.get_stop_real_time(code)
            name = data.get("stop_name", code)
            # API returns the code back as name when stop doesn't exist
            if name and name != code:
                return {"stop_id": code, "name": name, "code": code, "zone": ""}
        except Exception:
            pass
        return None

    tasks = [_probe(c) for c in candidates]
    found = await asyncio.gather(*tasks)

    for stop in found:
        if stop is not None:
            _append_bus_stop_result(stop, results, lang=lang)


def _append_station_result(station: dict, results: list, emoji: str,
                           callback_prefix: str, subtitle: str,
                           lang: str) -> None:
    """Append a rail-style station/stop (metro, MetroBus, CP) to results."""
    name = station["name"]
    line_emojis = " ".join(l["emoji"] for l in station.get("lines", []))
    lines_names = ", ".join(l["name"] for l in station.get("lines", []))
    zone_text = _zone_suffix(station.get("zone", ""), lang)

    text = (
        f"{emoji} *{escape_md(name)}*\n"
        f"{escape_md(line_emojis)}\n\n"
        f"{escape_md(_t('inline_lines', lang))}: {escape_md(lines_names)}"
    )

    results.append(InlineQueryResultArticle(
        id=str(uuid.uuid4()),
        title=f"{emoji} {name}",
        description=f"{subtitle}{zone_text}" if subtitle else f"{line_emojis}{zone_text}",
        input_message_content=InputTextMessageContent(
            message_text=text,
            parse_mode="MarkdownV2",
        ),
        reply_markup=_times_button(f"{callback_prefix}{name}", lang),
    ))


def _add_metro_stations_quick(query: str, results: list,
                              lang: str = "pt") -> None:
    """Search metro stations - quick mode for autocomplete."""
    try:
        stations = search_stations(query)
        for station in stations[:8]:
            line_emojis = " ".join(l["emoji"] for l in station.get("lines", []))
            _append_station_result(station, results, emoji="🚇",
                                   callback_prefix="metro:station:",
                                   subtitle=line_emojis, lang=lang)
    except Exception:
        logger.exception("Error searching metro stations for query: %s", query)


def _add_metrobus_stops_quick(query: str, results: list,
                              lang: str = "pt") -> None:
    """Search MetroBus stops - quick mode for autocomplete."""
    try:
        stops = search_metrobus_stops(query)
        for stop in stops[:8]:
            _append_station_result(stop, results, emoji="\U0001f68d",
                                   callback_prefix="metrobus:stop:",
                                   subtitle=_t("inline_metrobus_label", lang),
                                   lang=lang)
    except Exception:
        logger.exception("Error searching MetroBus stops for query: %s", query)


def _add_train_stations_quick(query: str, results: list,
                              lang: str = "pt") -> None:
    """Search CP train stations - quick mode for autocomplete."""
    try:
        stations = search_train_stations(query)
        for station in stations[:8]:
            _append_station_result(station, results, emoji="\U0001f686",
                                   callback_prefix="train:station:",
                                   subtitle=_t("inline_train_label", lang),
                                   lang=lang)
    except Exception:
        logger.exception("Error searching train stations for query: %s", query)
