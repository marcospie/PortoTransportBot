"""Inline query handler for sharing transport info in any chat."""

import uuid

from telegram import Update, InlineQueryResultArticle, InputTextMessageContent
from telegram.ext import ContextTypes

from bot.services import stcp
from bot.services.metro import search_stations, get_next_departures
from bot.utils.formatting import escape_md


async def inline_query_handler(update: Update,
                                context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline queries: @BotName <query>."""
    query = update.inline_query.query.strip()
    results = []

    if not query:
        # Show usage hint
        results.append(InlineQueryResultArticle(
            id=str(uuid.uuid4()),
            title="Escreve um código de paragem ou nome de estação",
            description="Exemplo: BCM2, Trindade, Bolhão",
            input_message_content=InputTextMessageContent(
                message_text=(
                    "Use @PortoTransportBot seguido do nome da paragem "
                    "ou estação para ver horários em tempo real\\."
                ),
                parse_mode="MarkdownV2",
            ),
        ))
    else:
        # Check if it looks like a stop code (short alphanumeric with digits)
        is_code = len(query) <= 6 and any(c.isdigit() for c in query)

        if is_code:
            await _add_bus_stop_by_code(query.upper(), results)

        # Search metro stations
        _add_metro_stations(query, results)

        # Search bus stops by name (only when it doesn't look like a code)
        if not is_code:
            await _add_bus_stops_by_name(query, results)

    # Telegram allows up to 50 results; keep a reasonable limit
    await update.inline_query.answer(results[:10], cache_time=30)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

async def _add_bus_stop_by_code(stop_code: str,
                                results: list) -> None:
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


def _add_metro_stations(query: str, results: list) -> None:
    """Search metro stations and append results."""
    try:
        stations = search_stations(query)
        for station in stations[:3]:
            name = station["name"]
            line_emojis = " ".join(
                l["emoji"] for l in station.get("lines", [])
            )

            try:
                departures = get_next_departures(name, count=4)
                if departures and not departures[0].get("direction", "").startswith("Serviço"):
                    lines_text = [f"🚇 *{escape_md(name)}*\n"]
                    for dep in departures[:4]:
                        direction = escape_md(str(dep.get("direction", "?")))
                        time_val = escape_md(str(dep.get("time", "?")))
                        line_info = escape_md(str(dep.get("line", "")))
                        lines_text.append(
                            f"  🚃 {line_info} → {direction}")
                        lines_text.append(f"      ⏱ {time_val}")
                    text = "\n".join(lines_text)
                else:
                    text = f"🚇 *{escape_md(name)}*\nSem partidas disponíveis"
            except Exception:
                text = f"🚇 *{escape_md(name)}*\nInformação indisponível"

            results.append(InlineQueryResultArticle(
                id=str(uuid.uuid4()),
                title=f"🚇 {name}",
                description=(f"Metro - {line_emojis}"
                             if line_emojis else "Metro do Porto"),
                input_message_content=InputTextMessageContent(
                    message_text=text,
                    parse_mode="MarkdownV2",
                ),
            ))
    except Exception:
        pass


async def _add_bus_stops_by_name(query: str, results: list) -> None:
    """Search bus stops by name and append results."""
    try:
        stops = await stcp.search_stops(query)
        for stop in stops[:3]:
            stop_code = stop.get("code", "")
            stop_name = stop.get("name", "")

            try:
                data = await stcp.get_stop_real_time(stop_code)
                arrivals = data.get("arrivals", [])
                if arrivals:
                    lines_text = [
                        f"🚏 *{escape_md(stop_name)}*  "
                        f"`{escape_md(stop_code)}`\n"
                    ]
                    for arr in arrivals[:5]:
                        line_num = escape_md(str(arr.get("line", "?")))
                        dest = escape_md(str(arr.get("destination", "?")))
                        time_val = escape_md(str(arr.get("time", "?")))
                        lines_text.append(
                            f"  🚌 *{line_num}* → {dest}")
                        lines_text.append(f"      ⏱ {time_val}")
                    text = "\n".join(lines_text)
                else:
                    text = (
                        f"🚏 *{escape_md(stop_name)}*  "
                        f"`{escape_md(stop_code)}`\n"
                        "Sem autocarros previstos"
                    )
            except Exception:
                text = (
                    f"🚏 *{escape_md(stop_name)}*  "
                    f"`{escape_md(stop_code)}`"
                )

            results.append(InlineQueryResultArticle(
                id=str(uuid.uuid4()),
                title=f"🚌 {stop_name}",
                description=f"Paragem {stop_code}",
                input_message_content=InputTextMessageContent(
                    message_text=text,
                    parse_mode="MarkdownV2",
                ),
            ))
    except Exception:
        pass
