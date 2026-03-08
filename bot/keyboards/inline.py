"""Inline keyboard builders for the Telegram bot."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import METRO_LINES
from bot.utils.i18n import t


# --- Main Menu ---

def main_menu_keyboard(lang: str = "pt") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(t("kb_buses", lang), callback_data="menu:bus"),
            InlineKeyboardButton(t("kb_metro", lang), callback_data="menu:metro"),
        ],
        [InlineKeyboardButton(t("kb_plan_route", lang), callback_data="plan:route")],
        [
            InlineKeyboardButton(t("kb_favorites", lang), callback_data="menu:favorites"),
            InlineKeyboardButton(t("kb_settings", lang), callback_data="menu:settings"),
        ],
        [InlineKeyboardButton(t("kb_help", lang), callback_data="menu:help")],
        [InlineKeyboardButton(t("kb_quick_search", lang),
                              switch_inline_query_current_chat="")],
    ])


# --- Bus (STCP) Keyboards ---

def bus_menu_keyboard(lang: str = "pt") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("kb_search_stop", lang),
                              switch_inline_query_current_chat="bus ")],
        [InlineKeyboardButton(t("kb_search_by_code", lang), callback_data="bus:code")],
        [InlineKeyboardButton(t("kb_all_lines", lang), callback_data="bus:routes")],
        [InlineKeyboardButton(t("back_main", lang), callback_data="menu:main")],
    ])


def cancel_keyboard(back_to: str = "menu:bus", lang: str = "pt") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("kb_cancel", lang), callback_data=back_to)],
    ])


def onboarding_keyboard(lang: str = "pt") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("kb_nearby", lang), callback_data="onboard:location")],
        [
            InlineKeyboardButton(t("kb_buses", lang),
                                  switch_inline_query_current_chat="bus "),
            InlineKeyboardButton(t("kb_metro", lang),
                                  switch_inline_query_current_chat="metro "),
        ],
        [InlineKeyboardButton(t("kb_plan_route", lang), callback_data="plan:route")],
    ])


def bus_stop_results_keyboard(stops: list[dict], lang: str = "pt") -> InlineKeyboardMarkup:
    buttons = []
    for stop in stops[:8]:
        stop_id = stop["stop_id"]
        name = stop["name"]
        label = f"🚏 {name} ({stop_id})"
        if len(label) > 50:
            label = f"🚏 {name[:35]}… ({stop_id})"
        buttons.append([
            InlineKeyboardButton(label, callback_data=f"bus:stop:{stop_id}")
        ])
    buttons.append([InlineKeyboardButton(t("kb_back", lang), callback_data="menu:bus")])
    return InlineKeyboardMarkup(buttons)


def bus_stop_actions_keyboard(stop_id: str, is_fav: bool = False, lang: str = "pt") -> InlineKeyboardMarkup:
    if is_fav:
        fav_button = InlineKeyboardButton(t("kb_unfavorite", lang), callback_data=f"fav:remove:bus:{stop_id}")
    else:
        fav_button = InlineKeyboardButton(t("kb_favorite", lang), callback_data=f"fav:add:bus:{stop_id}")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("kb_refresh", lang), callback_data=f"bus:stop:{stop_id}")],
        [
            InlineKeyboardButton(t("kb_details", lang), callback_data=f"bus:info:{stop_id}"),
            InlineKeyboardButton(t("kb_map", lang), callback_data=f"bus:loc:{stop_id}"),
        ],
        [
            fav_button,
            InlineKeyboardButton(t("kb_back_menu", lang), callback_data="menu:bus"),
        ],
    ])


def bus_routes_keyboard(routes: list[dict], page: int = 0,
                        per_page: int = 8, lang: str = "pt") -> InlineKeyboardMarkup:
    start = page * per_page
    end = start + per_page
    page_routes = routes[start:end]

    buttons = []
    row = []
    for r in page_routes:
        num = r.get("number", r.get("id", "?"))
        row.append(InlineKeyboardButton(f"🚌 {num}", callback_data=f"bus:route:{num}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    # Pagination
    nav_row = []
    total_pages = (len(routes) + per_page - 1) // per_page
    if page > 0:
        nav_row.append(InlineKeyboardButton(t("kb_previous", lang), callback_data=f"bus:routes:page:{page - 1}"))
    if total_pages > 1:
        nav_row.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="noop"))
    if end < len(routes):
        nav_row.append(InlineKeyboardButton(t("kb_next", lang), callback_data=f"bus:routes:page:{page + 1}"))
    if nav_row:
        buttons.append(nav_row)

    buttons.append([InlineKeyboardButton(t("kb_back", lang), callback_data="menu:bus")])
    return InlineKeyboardMarkup(buttons)


# --- Metro Keyboards ---

def metro_menu_keyboard(lang: str = "pt") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("kb_search_station", lang),
                              switch_inline_query_current_chat="metro ")],
        [
            InlineKeyboardButton(t("kb_lines", lang), callback_data="metro:lines"),
            InlineKeyboardButton(t("kb_frequencies", lang), callback_data="metro:freq"),
        ],
        [InlineKeyboardButton(t("back_main", lang), callback_data="menu:main")],
    ])


def metro_lines_keyboard(lang: str = "pt") -> InlineKeyboardMarkup:
    buttons = []
    # Show lines in pairs for compact layout
    row = []
    for code, data in METRO_LINES.items():
        emoji = data["emoji"]
        name = data["name"]
        row.append(InlineKeyboardButton(f"{emoji} {name}", callback_data=f"metro:line:{code}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(t("kb_back", lang), callback_data="menu:metro")])
    return InlineKeyboardMarkup(buttons)


def metro_station_results_keyboard(stations: list[dict], lang: str = "pt") -> InlineKeyboardMarkup:
    buttons = []
    for station in stations[:8]:
        name = station["name"]
        lines_str = " ".join(l["emoji"] for l in station["lines"])
        label = f"🚇 {name} {lines_str}"
        if len(label) > 55:
            label = f"🚇 {name[:30]}… {lines_str}"
        buttons.append([
            InlineKeyboardButton(label, callback_data=f"metro:station:{name}")
        ])
    buttons.append([InlineKeyboardButton(t("kb_back", lang), callback_data="menu:metro")])
    return InlineKeyboardMarkup(buttons)


def metro_station_actions_keyboard(station_name: str, is_fav: bool = False, lang: str = "pt") -> InlineKeyboardMarkup:
    if is_fav:
        fav_button = InlineKeyboardButton(t("kb_unfavorite", lang), callback_data=f"fav:remove:metro:{station_name}")
    else:
        fav_button = InlineKeyboardButton(t("kb_favorite", lang), callback_data=f"fav:add:metro:{station_name}")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("kb_refresh", lang), callback_data=f"metro:station:{station_name}")],
        [
            InlineKeyboardButton(t("kb_lines", lang), callback_data=f"metro:station_lines:{station_name}"),
            InlineKeyboardButton(t("kb_map", lang), callback_data=f"metro:loc:{station_name}"),
        ],
        [
            fav_button,
            InlineKeyboardButton(t("kb_back_menu", lang), callback_data="menu:metro"),
        ],
    ])


def metro_line_actions_keyboard(line_code: str, lang: str = "pt") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("kb_freq_detail", lang), callback_data=f"metro:line_freq:{line_code}")],
        [InlineKeyboardButton(t("kb_back", lang), callback_data="metro:lines")],
    ])


def metro_line_detail_keyboard(line_code: str, stations: list[str],
                                stations_data: dict | None = None,
                                lang: str = "pt") -> InlineKeyboardMarkup:
    """Build keyboard for line detail view with key station buttons.

    Shows up to 6 key stations (first, last, and transfer stations)
    plus frequencies and back buttons.
    """
    # Collect key stations: first, last, and transfer stations (stations
    # served by more than one line).
    key_stations: list[str] = []
    transfer_stations: list[str] = []

    if stations_data:
        for name in stations:
            sdata = stations_data.get(name, {})
            if len(sdata.get("lines", [])) > 1:
                transfer_stations.append(name)

    # Always include first and last
    if stations:
        key_stations.append(stations[0])
    # Add transfer stations (keep order, skip duplicates with first/last)
    for ts in transfer_stations:
        if ts not in key_stations:
            key_stations.append(ts)
    if stations and stations[-1] not in key_stations:
        key_stations.append(stations[-1])

    # Limit to 6 stations
    key_stations = key_stations[:6]

    line_data = METRO_LINES.get(line_code, {})
    emoji = line_data.get("emoji", "🚇")

    buttons = []
    # Station buttons in rows of 2
    row: list[InlineKeyboardButton] = []
    for name in key_stations:
        label = f"{emoji} {name}"
        if len(label) > 40:
            label = f"{emoji} {name[:32]}..."
        cb_data = f"metro:station:{name}"
        # Telegram limits callback_data to 64 bytes
        if len(cb_data.encode("utf-8")) <= 64:
            row.append(InlineKeyboardButton(label, callback_data=cb_data))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([InlineKeyboardButton(t("kb_freq_detail", lang), callback_data=f"metro:line_freq:{line_code}")])
    buttons.append([InlineKeyboardButton(t("kb_back", lang), callback_data="metro:lines")])
    return InlineKeyboardMarkup(buttons)


# --- Favorites Keyboards ---

def favorites_keyboard(favorites: list[dict], lang: str = "pt") -> InlineKeyboardMarkup:
    if not favorites:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton(t("kb_find_stop", lang),
                                  switch_inline_query_current_chat="bus ")],
            [InlineKeyboardButton(t("kb_find_station", lang),
                                  switch_inline_query_current_chat="metro ")],
            [InlineKeyboardButton(t("back_main", lang), callback_data="menu:main")],
        ])

    buttons = []
    for fav in favorites[:10]:
        ftype = fav["type"]
        fid = fav["id"]
        name = fav.get("name", fid)
        if ftype == "bus":
            buttons.append([
                InlineKeyboardButton(f"🚌 {name} ({fid})", callback_data=f"bus:stop:{fid}"),
                InlineKeyboardButton("🗑", callback_data=f"fav:remove:{ftype}:{fid}"),
            ])
        else:
            buttons.append([
                InlineKeyboardButton(f"🚇 {name}", callback_data=f"metro:station:{fid}"),
                InlineKeyboardButton("🗑", callback_data=f"fav:remove:{ftype}:{fid}"),
            ])

    buttons.append([InlineKeyboardButton(t("back_main", lang), callback_data="menu:main")])
    return InlineKeyboardMarkup(buttons)
