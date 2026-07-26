from datetime import datetime
from zoneinfo import ZoneInfo

#: Timestamps shown to users are Porto's wall clock, not the host's — a bot
#: deployed on a UTC host would otherwise stamp "Atualizado às" an hour early.
PORTO_TZ = ZoneInfo("Europe/Lisbon")


def _now_hhmm() -> str:
    return escape_md(datetime.now(PORTO_TZ).strftime("%H:%M"))


# Footer / status wording.  This module renders raw strings rather than going
# through bot.utils.i18n (no translation keys exist for these), so the two
# languages are kept side by side here.
_LABELS = {
    "pt": {
        "no_arrivals": ("Sem autocarros previstos na próxima hora\\.\n"
                        "Tenta atualizar daqui a pouco\\."),
        "data_unavailable": (
            "⚠️ *Dados STCP temporariamente indisponíveis*\n\n"
            "Não foi possível obter os tempos de espera desta paragem\\.\n"
            "Isto não significa que não haja autocarros — tenta novamente "
            "dentro de um minuto\\."
        ),
        "stop_not_found": (
            "⚠️ *Paragem não encontrada*\n\n"
            "O código desta paragem não existe nos dados da STCP\\."
        ),
        "no_schedule": "Sem informação de horários disponível\\.",
        "updated": "Atualizado às",
        "estimate": "Estimativa",
        "scheduled": "Horário previsto",
    },
    "en": {
        "no_arrivals": ("No buses expected in the next hour\\.\n"
                        "Try refreshing in a moment\\."),
        "data_unavailable": (
            "⚠️ *STCP data temporarily unavailable*\n\n"
            "The waiting times for this stop could not be retrieved\\.\n"
            "This does not mean there are no buses — please try again in "
            "a minute\\."
        ),
        "stop_not_found": (
            "⚠️ *Stop not found*\n\n"
            "This stop code does not exist in the STCP data\\."
        ),
        "no_schedule": "No schedule information available\\.",
        "updated": "Updated at",
        "estimate": "Estimate",
        "scheduled": "Scheduled",
    },
}


def _label(key: str, lang: str = "pt") -> str:
    return _LABELS.get(lang, _LABELS["pt"]).get(key, _LABELS["pt"][key])


def _timestamp_footer(departures: list[dict], lang: str = "pt") -> str:
    """Build a footer whose wording matches what the data actually is.

    Real-time data gets "Atualizado às", frequency-based guesses get
    "Estimativa", and plain timetable data gets "Horário previsto" — so the
    message never implies live tracking when none happened.
    """
    timestamp = _now_hhmm()
    if any(d.get("estimated") for d in departures):
        return f"_{_label('estimate', lang)}  ·  {timestamp}_"
    if any(d.get("realtime") for d in departures):
        return f"_{_label('updated', lang)} {timestamp}_"
    return f"_{_label('scheduled', lang)}  ·  {timestamp}_"


def format_bus_arrivals(stop_code: str, stop_name: str, arrivals: list[dict],
                        error: bool | None = None, source: str | None = None,
                        lang: str = "pt") -> str:
    """Format bus arrival data into a compact Telegram message.

    Args:
        stop_code: Stop code shown next to the name.
        stop_name: Human-readable stop name.
        arrivals: Arrival dicts. May be an ``stcp.ArrivalsList``, in which case
            its ``error``/``source`` metadata is picked up automatically.
        error: Force the "data source unavailable" rendering. When ``None``
            (the default) it is read from the ``arrivals`` metadata, so callers
            that only forward ``data["arrivals"]`` still get honest output.
        source: Optional data-source marker (``"unavailable"``, ``"not_found"``,
            ``"realtime"`` ...). Defaults to the ``arrivals`` metadata.
        lang: ``"pt"`` or ``"en"``.
    """
    header = f"🚏 *{escape_md(stop_name)}*  `{stop_code}`"
    separator = "━━━━━━━━━━━━━━━━"

    if error is None:
        error = bool(getattr(arrivals, "error", False))
    if source is None:
        source = getattr(arrivals, "source", None)

    if error:
        # The data source failed. Never claim there are no buses.
        body = (_label("stop_not_found", lang) if source == "not_found"
                else _label("data_unavailable", lang))
        return f"{header}\n{separator}\n\n{body}"

    if not arrivals:
        return f"{header}\n{separator}\n\n{_label('no_arrivals', lang)}"

    # Split arrivals into urgent (< 5 min) and others
    urgent = []
    regular = []
    for a in arrivals:
        minutes = a.get("minutes")
        if minutes is not None and minutes < 5:
            urgent.append(a)
        else:
            regular.append(a)

    lines = [header, separator, ""]

    has_both_groups = bool(urgent) and bool(regular)

    if has_both_groups:
        lines.append("⏳ *A chegar:*" if lang == "pt" else "⏳ *Arriving:*")
        for a in urgent:
            lines.append(_format_bus_arrival_line(a))
        lines.append("")
        lines.append("🕐 *Seguintes:*" if lang == "pt" else "🕐 *Later:*")
        for a in regular:
            lines.append(_format_bus_arrival_line(a))
    else:
        # Only one group is populated — just list them all, in order.
        for a in arrivals:
            lines.append(_format_bus_arrival_line(a))

    lines.append("")
    lines.append(_bus_footer(arrivals, source, lang))
    return "\n".join(lines)


def _bus_footer(arrivals: list[dict], source: str | None, lang: str) -> str:
    """Footer for bus arrivals, reflecting whether data is live or scheduled."""
    timestamp = _now_hhmm()
    if source in (None, "realtime"):
        return f"_{_label('updated', lang)} {timestamp}_"
    return f"_{_label('scheduled', lang)}  ·  {timestamp}_"


def _format_bus_arrival_line(arrival: dict) -> str:
    """Format a single bus arrival as a compact one-liner."""
    line_num = escape_md(arrival.get("line", "?"))
    destination = escape_md(arrival.get("destination", "?"))
    time_str = arrival.get("time", "?")

    # The time field from stcp service already contains status emoji prefix
    # e.g. "✅ 3 minutos" or "⚠️ A chegar"
    # We put the raw time text in backticks, but status emoji stays outside
    status_emoji = ""
    time_display = time_str
    for emoji in ("✅", "⚠️", "⏩"):
        if time_str.startswith(emoji):
            status_emoji = f" {emoji}"
            time_display = time_str[len(emoji):].strip()
            break

    return f"*{line_num}*  {destination}  —  `{escape_md(time_display)}`{status_emoji}"


def format_metro_schedule(station_name: str, line_info: str,
                          departures: list[dict], lang: str = "pt") -> str:
    """Format metro departure data into a compact Telegram message."""
    header = f"🚇 *{escape_md(station_name)}*"
    separator = "━━━━━━━━━━━━━━━━"

    if not departures:
        return (
            f"{header}\n"
            f"{line_info}\n"
            f"{separator}\n\n"
            f"{_label('no_schedule', lang)}"
        )

    lines = [header]
    if line_info:
        lines.append(line_info)
    lines.append(separator)
    lines.append("")

    for dep in departures:
        direction = escape_md(dep.get("direction", "?"))
        time_str = dep.get("time", "?")
        # Metro times often start with ~ for estimates; keep that inside backticks
        lines.append(f"*{direction}*  —  `{escape_md(time_str)}`")

    lines.append("")
    lines.append(_timestamp_footer(departures, lang))

    return "\n".join(lines)


def format_route_info(route_num: str, direction: str,
                      stops: list[str]) -> str:
    """Format route information with stops list."""
    lines = [
        f"🚌 *Linha {escape_md(route_num)}*",
        f"📍 {escape_md(direction)}\n",
        "*Paragens:*\n",
    ]
    for i, stop in enumerate(stops, 1):
        prefix = "🔴" if i == 1 or i == len(stops) else "⚪"
        lines.append(f"  {prefix} `{escape_md(stop)}`")

    return "\n".join(lines)


def format_metro_line_info(line_code: str, line_data: dict,
                           stations: list[str],
                           stations_data: dict | None = None) -> str:
    """Format metro line information with a visual station map.

    Args:
        line_code: Line code (e.g. "A").
        line_data: Line metadata dict with emoji, name, route.
        stations: Ordered list of station names on this line.
        stations_data: Optional dict mapping station name to its data
            (with "lines" key). When provided, transfer stations are
            annotated with connecting line emojis.
    """
    from bot.config import METRO_LINES as _METRO_LINES

    emoji = line_data.get("emoji", "🚇")
    name = line_data.get("name", f"Linha {line_code}")
    route = line_data.get("route", "")

    lines = [f"{emoji} *{escape_md(name)}*"]
    if route:
        lines.append(f"_{escape_md(route)}_\n")

    for i, station_name in enumerate(stations):
        # Build transfer info when station data is available
        transfer_info = ""
        if stations_data:
            sdata = stations_data.get(station_name, {})
            other_lines = [l for l in sdata.get("lines", []) if l != line_code]
            if other_lines:
                other_emojis = "".join(
                    _METRO_LINES.get(l, {}).get("emoji", "") for l in other_lines
                )
                transfer_info = f" 🔄 {other_emojis}"

        escaped_name = escape_md(station_name)
        if i == 0 or i == len(stations) - 1:
            lines.append(f"  {emoji} *{escaped_name}*{transfer_info}")
        else:
            lines.append(f"  {emoji} {escaped_name}{transfer_info}")

        if i < len(stations) - 1:
            lines.append("  │")

    lines.append(f"\n📊 {len(stations)} estações")

    text = "\n".join(lines)
    # Truncate if too long for Telegram (max ~4096 chars)
    if len(text) > 4000:
        text = text[:3950] + "\n\n\\.\\.\\. _\\(lista truncada\\)_"
    return text


def format_metrobus_schedule(stop_name: str, line_info: str,
                             departures: list[dict], lang: str = "pt") -> str:
    """Format MetroBus departure data into a compact Telegram message."""
    header = f"\U0001f68d *{escape_md(stop_name)}*"
    separator = "━━━━━━━━━━━━━━━━"

    if not departures:
        return (
            f"{header}\n"
            f"{line_info}\n"
            f"{separator}\n\n"
            f"{_label('no_schedule', lang)}"
        )

    lines = [header]
    if line_info:
        lines.append(line_info)
    lines.append(separator)
    lines.append("")

    for dep in departures:
        direction = escape_md(dep.get("direction", "?"))
        time_str = dep.get("time", "?")
        lines.append(f"*{direction}*  —  `{escape_md(time_str)}`")

    lines.append("")
    lines.append(_timestamp_footer(departures, lang))

    return "\n".join(lines)


def format_metrobus_line_info(line_code: str, line_data: dict,
                               stops: list[str],
                               stops_data: dict | None = None) -> str:
    """Format MetroBus line information with a visual stop map."""
    emoji = line_data.get("emoji", "\U0001f68d")
    name = line_data.get("name", f"Linha {line_code}")
    route = line_data.get("route", "")

    lines = [f"{emoji} *{escape_md(name)}*"]
    if route:
        lines.append(f"_{escape_md(route)}_\n")

    for i, stop_name in enumerate(stops):
        escaped_name = escape_md(stop_name)
        if i == 0 or i == len(stops) - 1:
            lines.append(f"  {emoji} *{escaped_name}*")
        else:
            lines.append(f"  {emoji} {escaped_name}")

        if i < len(stops) - 1:
            lines.append("  │")

    lines.append(f"\n📊 {len(stops)} paragens")

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:3950] + "\n\n\\.\\.\\. _\\(lista truncada\\)_"
    return text


def escape_md(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    special_chars = r"_*[]()~`>#+-=|{}.!"
    result = []
    for ch in str(text):
        if ch in special_chars:
            result.append(f"\\{ch}")
        else:
            result.append(ch)
    return "".join(result)
