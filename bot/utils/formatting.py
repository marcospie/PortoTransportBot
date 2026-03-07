from datetime import datetime


def format_bus_arrivals(stop_code: str, stop_name: str, arrivals: list[dict]) -> str:
    """Format bus arrival data into a compact Telegram message."""
    header = f"🚏 *{escape_md(stop_name)}*  `{stop_code}`"
    separator = "━━━━━━━━━━━━━━━━"

    if not arrivals:
        return (
            f"{header}\n"
            f"{separator}\n\n"
            "Sem autocarros previstos na próxima hora\\.\n"
            "Tenta atualizar daqui a pouco\\."
        )

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
        lines.append("⏳ *A chegar:*")
    if urgent or not has_both_groups:
        for a in (urgent if has_both_groups else arrivals[:0]):
            lines.append(_format_bus_arrival_line(a))
        if has_both_groups:
            lines.append("")

    if has_both_groups:
        lines.append("🕐 *Seguintes:*")
        for a in regular:
            lines.append(_format_bus_arrival_line(a))
    else:
        # No split needed — just list them all
        for a in arrivals:
            lines.append(_format_bus_arrival_line(a))

    timestamp = escape_md(datetime.now().strftime("%H:%M"))
    lines.append("")
    lines.append(f"_Atualizado às {timestamp}_")
    return "\n".join(lines)


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
                          departures: list[dict]) -> str:
    """Format metro departure data into a compact Telegram message."""
    header = f"🚇 *{escape_md(station_name)}*"
    separator = "━━━━━━━━━━━━━━━━"

    if not departures:
        return (
            f"{header}\n"
            f"{line_info}\n"
            f"{separator}\n\n"
            "Sem informação de horários disponível\\."
        )

    # Check if departures are estimated
    is_estimated = any(d.get("estimated") for d in departures)

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

    timestamp = escape_md(datetime.now().strftime("%H:%M"))
    lines.append("")
    if is_estimated:
        lines.append(f"_Estimativa  ·  {timestamp}_")
    else:
        lines.append(f"_Atualizado às {timestamp}_")

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
                           stations: list[str]) -> str:
    """Format metro line information."""
    emoji = line_data.get("emoji", "🚇")
    name = line_data.get("name", f"Linha {line_code}")
    route = line_data.get("route", "")

    lines = [
        f"{emoji} *{escape_md(name)}* \\(Linha `{escape_md(line_code)}`\\)",
        f"📍 {escape_md(route)}\n",
        f"*Estações \\({len(stations)}\\):*",
    ]
    for i, station in enumerate(stations, 1):
        prefix = "🔴" if i == 1 or i == len(stations) else "⚪"
        lines.append(f"  {prefix} {escape_md(station)}")

    return "\n".join(lines)


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
