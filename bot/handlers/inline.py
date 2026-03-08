"""Inline query handler for sharing transport info and autocomplete search."""

import uuid

from telegram import Update, InlineQueryResultArticle, InputTextMessageContent
from telegram.ext import ContextTypes

from bot.services import stcp
from bot.services.stcp import search_stops_local
from bot.services.metro import search_stations, get_next_departures
from bot.services.metrobus import search_stops as search_metrobus_stops
from bot.utils.formatting import escape_md


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
        # Always try fuzzy local search (handles both codes and names)
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
        pass


async def _add_bus_stops_quick(query: str, results: list) -> None:
    """Search bus stops by name - quick mode for autocomplete (no real-time data).

    Uses local GTFS data for instant results, falls back to API.
    """
    try:
        # Local fuzzy search first (instant, no API call)
        stops = search_stops_local(query, max_results=8)
        if not stops:
            stops = await stcp.search_stops(query)
        for stop in stops[:8]:
            stop_code = stop.get("code", stop.get("stop_id", ""))
            stop_name = stop.get("name", "")
            zone = stop.get("zone", "")

            zone_text = f" · Zona {zone}" if zone else ""

            # Quick result without real-time data (faster autocomplete)
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
    except Exception:
        pass


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
        pass


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
        pass
