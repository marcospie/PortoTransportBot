from datetime import datetime


def format_bus_arrivals(stop_code: str, stop_name: str, arrivals: list[dict]) -> str:
    """Format bus arrival data into a readable Telegram message."""
    if not arrivals:
        return (
            f"🚏 *{escape_md(stop_name)}* \\(`{stop_code}`\\)\n\n"
            "Sem autocarros previstos na próxima hora\\."
        )

    lines = [f"🚏 *{escape_md(stop_name)}* \\(`{stop_code}`\\)\n"]
    lines.append("🕐 *Próximas passagens:*\n")

    for arrival in arrivals:
        line_num = arrival.get("line", "?")
        destination = arrival.get("destination", "?")
        time_str = arrival.get("time", "?")
        lines.append(f"  🚌 *{escape_md(line_num)}* → {escape_md(destination)}")
        lines.append(f"      ⏱ {escape_md(time_str)}\n")

    lines.append(f"\n_Atualizado: {escape_md(datetime.now().strftime('%H:%M:%S'))}_")
    return "\n".join(lines)


def format_metro_schedule(station_name: str, line_info: str,
                          departures: list[dict]) -> str:
    """Format metro departure data into a readable Telegram message."""
    if not departures:
        return (
            f"🚇 *{escape_md(station_name)}*\n"
            f"{line_info}\n\n"
            "Sem informação de horários disponível\\."
        )

    lines = [
        f"🚇 *{escape_md(station_name)}*",
        f"{line_info}\n",
        "🕐 *Próximas partidas:*\n",
    ]

    for dep in departures:
        direction = dep.get("direction", "?")
        time_str = dep.get("time", "?")
        lines.append(f"  🚃 → {escape_md(direction)}")
        lines.append(f"      ⏱ {escape_md(time_str)}\n")

    lines.append(f"\n_Atualizado: {escape_md(datetime.now().strftime('%H:%M:%S'))}_")
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
        lines.append(f"  {prefix} {escape_md(stop)}")

    return "\n".join(lines)


def format_metro_line_info(line_code: str, line_data: dict,
                           stations: list[str]) -> str:
    """Format metro line information."""
    emoji = line_data.get("emoji", "🚇")
    name = line_data.get("name", f"Linha {line_code}")
    route = line_data.get("route", "")

    lines = [
        f"{emoji} *{escape_md(name)}* \\(Linha {line_code}\\)",
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
