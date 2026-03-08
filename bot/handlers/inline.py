"""Inline query handler for sharing transport info and autocomplete search."""

import asyncio
import logging
import re
import uuid

from telegram import Update, InlineQueryResultArticle, InputTextMessageContent
from telegram.ext import ContextTypes

from bot.services import stcp
from bot.services.stcp import search_stops_local
from bot.services.metro import search_stations, get_next_departures
from bot.services.metrobus import search_stops as search_metrobus_stops
from bot.utils.formatting import escape_md

logger = logging.getLogger(__name__)

# Pattern for queries that look like bus stop codes
_CODE_PATTERN = re.compile(r"^[A-Za-z]{2,6}\d{0,2}$")


async def inline_query_handler(update: Update,
                                context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline queries: @BotName <query>."""
    raw_query = update.inline_query.query.strip()
    results = []

    if not raw_query:
        # Show usage hints
        results.append(_hint_article(
            "🔍 Pesquisa rápida",
            "Escreve o nome de uma paragem ou estação...",
            "Exemplo: Bolhão, Trindade, Casa da Música",
        ))
        results.append(_hint_article(
            "🚌 Pesquisar autocarros",
            "Escreve 'bus' seguido do nome da paragem",
            "Exemplo: bus Bolhão",
        ))
        results.append(_hint_article(
            "🚇 Pesquisar metro",
            "Escreve 'metro' seguido do nome da estação",
            "Exemplo: metro Trindade",
        ))
        await update.inline_query.answer(results, cache_time=300)
        return

    # Check for prefix routing
    mode = "all"
    query = raw_query
    if raw_query.lower().startswith("bus "):
        mode = "bus"
        query = raw_query[4:].strip()
    elif raw_query.lower().startswith("metro "):
        mode = "metro"
        query = raw_query[6:].strip()
    elif raw_query.lower().startswith("metrobus "):
        mode = "metrobus"
        query = raw_query[9:].strip()

    if not query:
        if mode == "bus":
            results.append(_hint_article(
                "🚌 Pesquisar paragem",
                "Continua a escrever o nome ou código...",
                "Exemplo: Bolhão, BCM2",
            ))
        elif mode == "metro":
            results.append(_hint_article(
                "🚇 Pesquisar estação",
                "Continua a escrever o nome da estação...",
                "Exemplo: Trindade, Bolhão",
            ))
        elif mode == "metrobus":
            results.append(_hint_article(
                "\U0001f68d Pesquisar MetroBus",
                "Continua a escrever o nome da paragem...",
                "Exemplo: Boavista, Campanhã",
            ))
        await update.inline_query.answer(results, cache_time=300)
        return

    if mode in ("all", "bus"):
        await _add_bus_stops_quick(query, results)

    if mode in ("all", "metro"):
        _add_metro_stations_quick(query, results)

    if mode in ("all", "metrobus"):
        _add_metrobus_stops_quick(query, results)

    if not results:
        results.append(_hint_article(
            "🤔 Sem resultados",
            f"Nenhum resultado para '{query}'",
            "Tenta outro nome ou código",
        ))

    await update.inline_query.answer(results[:15], cache_time=5,
                                      is_personal=False)


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


async def _add_bus_stop_by_code(stop_code: str, results: list) -> None:
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
            desc = (f"{len(arrivals)} autocarros - toca para partilhar"
                    if arrivals
                    else "Sem autocarros previstos")
            results.append(InlineQueryResultArticle(
                id=str(uuid.uuid4()),
                title=f"🚌 Paragem {stop_code}",
                description=desc,
                input_message_content=InputTextMessageContent(
                    message_text=text,
                    parse_mode="MarkdownV2",
                ),
            ))
    except Exception:
        logger.exception("Error looking up bus stop by code: %s", stop_code)


async def _add_bus_stops_quick(query: str, results: list) -> None:
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
                _append_bus_stop_result(stop, results)
            return

        # No results from name search — try direct stop code lookup
        # if the query looks like a stop code (e.g. ASP, BIBG, TRN1)
        if _CODE_PATTERN.match(query):
            await _try_stop_code_lookups(query, results)

    except Exception:
        logger.exception("Error searching bus stops for query: %s", query)


def _append_bus_stop_result(stop: dict, results: list) -> None:
    """Append a single bus stop to inline results."""
    stop_code = stop.get("code", stop.get("stop_id", ""))
    stop_name = stop.get("name", "")
    zone = stop.get("zone", "")
    zone_text = f" · Zona {zone}" if zone else ""

    text = (
        f"🚏 *{escape_md(stop_name)}*  `{escape_md(stop_code)}`\n\n"
        f"Para ver horários em tempo real, envia `/stop {escape_md(stop_code)}` no chat\\."
    )

    results.append(InlineQueryResultArticle(
        id=str(uuid.uuid4()),
        title=f"🚌 {stop_name}",
        description=f"Paragem {stop_code}{zone_text}",
        input_message_content=InputTextMessageContent(
            message_text=text,
            parse_mode="MarkdownV2",
        ),
    ))


async def _try_stop_code_lookups(query: str, results: list) -> None:
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
            _append_bus_stop_result(stop, results)


def _add_metro_stations_quick(query: str, results: list) -> None:
    """Search metro stations - quick mode for autocomplete."""
    try:
        stations = search_stations(query)
        for station in stations[:8]:
            name = station["name"]
            line_emojis = " ".join(
                l["emoji"] for l in station.get("lines", [])
            )
            zone = station.get("zone", "")
            zone_text = f" · Zona {zone}" if zone else ""

            lines_names = ", ".join(
                l["name"] for l in station.get("lines", [])
            )

            text = (
                f"🚇 *{escape_md(name)}*\n"
                f"{escape_md(line_emojis)}\n\n"
                f"Linhas: {escape_md(lines_names)}\n\n"
                f"Para ver horários, envia `/station {escape_md(name)}` no chat\\."
            )

            results.append(InlineQueryResultArticle(
                id=str(uuid.uuid4()),
                title=f"🚇 {name}",
                description=f"{line_emojis}{zone_text}",
                input_message_content=InputTextMessageContent(
                    message_text=text,
                    parse_mode="MarkdownV2",
                ),
            ))
    except Exception:
        logger.exception("Error searching metro stations for query: %s", query)


def _add_metrobus_stops_quick(query: str, results: list) -> None:
    """Search MetroBus stops - quick mode for autocomplete."""
    try:
        stops = search_metrobus_stops(query)
        for stop in stops[:8]:
            name = stop["name"]
            line_emojis = " ".join(
                l["emoji"] for l in stop.get("lines", [])
            )
            zone = stop.get("zone", "")
            zone_text = f" \u00b7 Zona {zone}" if zone else ""

            lines_names = ", ".join(
                l["name"] for l in stop.get("lines", [])
            )

            text = (
                f"\U0001f68d *{escape_md(name)}*\n"
                f"{escape_md(line_emojis)}\n\n"
                f"Linhas: {escape_md(lines_names)}\n\n"
                f"Para ver hor\u00e1rios, envia `/metrobus` no chat\\."
            )

            results.append(InlineQueryResultArticle(
                id=str(uuid.uuid4()),
                title=f"\U0001f68d {name}",
                description=f"MetroBus{zone_text}",
                input_message_content=InputTextMessageContent(
                    message_text=text,
                    parse_mode="MarkdownV2",
                ),
            ))
    except Exception:
        logger.exception("Error searching MetroBus stops for query: %s", query)
