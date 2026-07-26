"""Inline keyboard builders for the Telegram bot."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import METRO_LINES
from bot.services.cp import CP_LINES
from bot.services.metrobus import METROBUS_LINES
from bot.utils.i18n import t


# --- Main Menu ---

def main_menu_keyboard(lang: str = "pt") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        # Primary transport
        [
            InlineKeyboardButton(t("kb_buses", lang), callback_data="menu:bus"),
            InlineKeyboardButton(t("kb_metrobus", lang), callback_data="menu:metrobus"),
        ],
        [
            InlineKeyboardButton(t("kb_metro", lang), callback_data="menu:metro"),
            InlineKeyboardButton(t("kb_trains", lang), callback_data="menu:trains"),
        ],
        # Tools & tourist
        [
            InlineKeyboardButton(t("kb_plan_route", lang), callback_data="plan:route"),
            InlineKeyboardButton(t("kb_tourist", lang), callback_data="tourist:menu"),
        ],
        [
            InlineKeyboardButton(t("kb_zones", lang), callback_data="menu:zones"),
            InlineKeyboardButton(t("kb_commuter", lang), callback_data="menu:commuter"),
        ],
        [
            InlineKeyboardButton(t("kb_favorites", lang), callback_data="menu:favorites"),
            InlineKeyboardButton(t("kb_events", lang), callback_data="menu:events"),
            InlineKeyboardButton(t("kb_weather", lang), callback_data="menu:weather"),
        ],
        [
            InlineKeyboardButton(t("kb_alerts", lang), callback_data="menu:alerts"),
            InlineKeyboardButton(t("kb_accessibility", lang), callback_data="menu:accessibility"),
            InlineKeyboardButton(t("kb_settings", lang), callback_data="menu:settings"),
        ],
        [
            InlineKeyboardButton(t("kb_help", lang), callback_data="menu:help"),
            InlineKeyboardButton(t("kb_quick_search", lang),
                                  switch_inline_query_current_chat=""),
        ],
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


def bus_stop_actions_keyboard(stop_id: str, is_fav: bool = False,
                              lang: str = "pt",
                              back_callback: str = "menu:bus") -> InlineKeyboardMarkup:
    if is_fav:
        fav_button = InlineKeyboardButton(t("kb_unfavorite", lang), callback_data=f"fav:remove:bus:{stop_id}")
    else:
        fav_button = InlineKeyboardButton(t("kb_favorite", lang), callback_data=f"fav:add:bus:{stop_id}")
    back_label = t("kb_back", lang) if back_callback != "menu:bus" else t("kb_back_menu", lang)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("kb_refresh", lang), callback_data=f"bus:stop:{stop_id}")],
        [
            InlineKeyboardButton(t("kb_details", lang), callback_data=f"bus:info:{stop_id}"),
            InlineKeyboardButton(t("kb_map", lang), callback_data=f"bus:loc:{stop_id}"),
        ],
        [
            fav_button,
            InlineKeyboardButton(back_label, callback_data=back_callback),
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


def metro_station_actions_keyboard(station_name: str, is_fav: bool = False,
                                    lang: str = "pt",
                                    back_callback: str = "menu:metro") -> InlineKeyboardMarkup:
    if is_fav:
        fav_button = InlineKeyboardButton(t("kb_unfavorite", lang), callback_data=f"fav:remove:metro:{station_name}")
    else:
        fav_button = InlineKeyboardButton(t("kb_favorite", lang), callback_data=f"fav:add:metro:{station_name}")
    back_label = t("kb_back", lang) if back_callback != "menu:metro" else t("kb_back_menu", lang)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("kb_refresh", lang), callback_data=f"metro:station:{station_name}")],
        [
            InlineKeyboardButton(t("kb_lines", lang), callback_data=f"metro:station_lines:{station_name}"),
            InlineKeyboardButton(t("kb_map", lang), callback_data=f"metro:loc:{station_name}"),
        ],
        [
            fav_button,
            InlineKeyboardButton(back_label, callback_data=back_callback),
        ],
    ])


def metro_line_actions_keyboard(line_code: str, lang: str = "pt") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("kb_freq_detail", lang), callback_data=f"metro:line_freq:{line_code}")],
        [InlineKeyboardButton(t("kb_back", lang), callback_data="metro:lines")],
    ])


#: Stations shown per page when the line view is paginated.
METRO_LINE_PAGE_SIZE = 10

#: Hard cap on station buttons when the whole line is rendered at once, so the
#: keyboard can never exceed what Telegram is willing to render.
_METRO_LINE_MAX_BUTTONS = 40


def metro_line_page_callback(line_code: str, page: int) -> str:
    """Callback data for a paginated metro line view.

    Kept as a helper so the handler side has a single definition to parse.
    """
    return f"metro:line:{line_code}:page:{page}"


def metro_line_detail_keyboard(line_code: str, stations: list[str],
                                stations_data: dict | None = None,
                                lang: str = "pt",
                                page: int | None = None,
                                per_page: int = METRO_LINE_PAGE_SIZE) -> InlineKeyboardMarkup:
    """Build keyboard for a line detail view with a button per station.

    Every station on the line is tappable, so a mid-line station no longer
    requires a fresh search.

    ``page`` controls paging:

    * ``None`` (default) renders the whole line in one keyboard and emits no
      pagination buttons -- safe for callers that cannot yet handle the
      ``metro:line:<code>:page:<n>`` callback.
    * an ``int`` renders that page plus previous/next buttons.
    """
    line_data = METRO_LINES.get(line_code, {})
    emoji = line_data.get("emoji", "🚇")

    total = len(stations)
    if page is None:
        page_stations = list(stations[:_METRO_LINE_MAX_BUTTONS])
        total_pages = 1
        page = 0
    else:
        per_page = max(1, per_page)
        total_pages = max(1, (total + per_page - 1) // per_page)
        page = max(0, min(page, total_pages - 1))
        start = page * per_page
        page_stations = list(stations[start:start + per_page])

    buttons = []
    # Station buttons in rows of 2, in line order.  Interchanges are flagged so
    # the line view still tells the user where they can transfer.
    row: list[InlineKeyboardButton] = []
    for name in page_stations:
        is_transfer = bool(stations_data
                           and len(stations_data.get(name, {}).get("lines", [])) > 1)
        suffix = " 🔄" if is_transfer else ""
        label = f"{emoji} {name}{suffix}"
        if len(label) > 40:
            label = f"{emoji} {name[:32]}...{suffix}"
        cb_data = f"metro:station:{name}"
        # Telegram limits callback_data to 64 bytes
        if len(cb_data.encode("utf-8")) > 64:
            continue
        row.append(InlineKeyboardButton(label, callback_data=cb_data))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    if total_pages > 1:
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton(
                t("kb_previous", lang),
                callback_data=metro_line_page_callback(line_code, page - 1),
            ))
        nav_row.append(InlineKeyboardButton(f"{page + 1}/{total_pages}",
                                            callback_data="noop"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton(
                t("kb_next", lang),
                callback_data=metro_line_page_callback(line_code, page + 1),
            ))
        buttons.append(nav_row)

    buttons.append([InlineKeyboardButton(t("kb_freq_detail", lang), callback_data=f"metro:line_freq:{line_code}")])
    buttons.append([InlineKeyboardButton(t("kb_back", lang), callback_data="metro:lines")])
    return InlineKeyboardMarkup(buttons)


# --- MetroBus Keyboards ---

def metrobus_menu_keyboard(lang: str = "pt") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("kb_search_metrobus_stop", lang),
                              switch_inline_query_current_chat="metrobus ")],
        [
            InlineKeyboardButton(t("kb_lines", lang), callback_data="metrobus:lines"),
            InlineKeyboardButton(t("kb_frequencies", lang), callback_data="metrobus:freq"),
        ],
        [InlineKeyboardButton(t("back_main", lang), callback_data="menu:main")],
    ])


def metrobus_stop_results_keyboard(stops: list[dict], lang: str = "pt") -> InlineKeyboardMarkup:
    buttons = []
    for stop in stops[:8]:
        name = stop["name"]
        lines_str = " ".join(l["emoji"] for l in stop["lines"])
        label = f"\U0001f68d {name} {lines_str}"
        if len(label) > 55:
            label = f"\U0001f68d {name[:30]}... {lines_str}"
        cb_data = f"metrobus:stop:{name}"
        if len(cb_data.encode("utf-8")) <= 64:
            buttons.append([
                InlineKeyboardButton(label, callback_data=cb_data)
            ])
    buttons.append([InlineKeyboardButton(t("kb_back", lang), callback_data="menu:metrobus")])
    return InlineKeyboardMarkup(buttons)


def metrobus_stop_actions_keyboard(stop_name: str, is_fav: bool = False,
                                    lang: str = "pt",
                                    back_callback: str = "menu:metrobus") -> InlineKeyboardMarkup:
    if is_fav:
        fav_button = InlineKeyboardButton(t("kb_unfavorite", lang), callback_data=f"fav:remove:metrobus:{stop_name}")
    else:
        fav_button = InlineKeyboardButton(t("kb_favorite", lang), callback_data=f"fav:add:metrobus:{stop_name}")
    back_label = t("kb_back", lang) if back_callback != "menu:metrobus" else t("kb_back_menu", lang)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("kb_refresh", lang), callback_data=f"metrobus:stop:{stop_name}")],
        [
            InlineKeyboardButton(t("kb_lines", lang), callback_data=f"metrobus:stop_lines:{stop_name}"),
            InlineKeyboardButton(t("kb_map", lang), callback_data=f"metrobus:loc:{stop_name}"),
        ],
        [
            fav_button,
            InlineKeyboardButton(back_label, callback_data=back_callback),
        ],
    ])


def metrobus_lines_keyboard(lang: str = "pt") -> InlineKeyboardMarkup:
    buttons = []
    for code, data in METROBUS_LINES.items():
        emoji = data["emoji"]
        name = data["name"]
        buttons.append([InlineKeyboardButton(f"{emoji} {name}", callback_data=f"metrobus:line:{code}")])
    buttons.append([InlineKeyboardButton(t("kb_back", lang), callback_data="menu:metrobus")])
    return InlineKeyboardMarkup(buttons)


# --- Favorites Keyboards ---

# Every favorite type maps to the callback prefix of the handler that can
# actually show it, plus the emoji used for that mode.  Keeping this in one
# place stops train/metrobus favorites from being routed to the metro handler
# (which then reports "station not found").
FAVORITE_ROUTES: dict[str, tuple[str, str]] = {
    "bus": ("bus:stop:", "🚌"),
    "metro": ("metro:station:", "🚇"),
    "metrobus": ("metrobus:stop:", "\U0001f68d"),
    "train": ("train:station:", "\U0001f686"),
}

# Types whose id is an opaque code worth showing next to the name.
_CODE_LIKE_TYPES = ("bus",)


def favorite_callback_data(fav_type: str, fav_id: str) -> str:
    """Return the callback_data that opens a favorite in its own handler."""
    prefix, _ = FAVORITE_ROUTES.get(fav_type, FAVORITE_ROUTES["metro"])
    return f"{prefix}{fav_id}"


def favorite_emoji(fav_type: str) -> str:
    """Return the emoji for a favorite type."""
    _, emoji = FAVORITE_ROUTES.get(fav_type, FAVORITE_ROUTES["metro"])
    return emoji


def favorites_keyboard(favorites: list[dict], lang: str = "pt") -> InlineKeyboardMarkup:
    if not favorites:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton(t("kb_find_stop", lang),
                                  switch_inline_query_current_chat="bus ")],
            [InlineKeyboardButton(t("kb_find_station", lang),
                                  switch_inline_query_current_chat="metro ")],
            [
                InlineKeyboardButton(t("kb_metrobus", lang),
                                      switch_inline_query_current_chat="metrobus "),
                InlineKeyboardButton(t("kb_trains", lang),
                                      switch_inline_query_current_chat="train "),
            ],
            [InlineKeyboardButton(t("back_main", lang), callback_data="menu:main")],
        ])

    buttons = []
    for fav in favorites[:10]:
        ftype = fav["type"]
        fid = fav["id"]
        name = fav.get("name", fid)
        emoji = favorite_emoji(ftype)
        if ftype in _CODE_LIKE_TYPES:
            label = f"{emoji} {name} ({fid})"
        else:
            label = f"{emoji} {name}"
        if len(label) > 55:
            label = f"{emoji} {name[:48]}…"

        row = []
        open_cb = favorite_callback_data(ftype, fid)
        if len(open_cb.encode("utf-8")) <= 64:
            row.append(InlineKeyboardButton(label, callback_data=open_cb))
        remove_cb = f"fav:remove:{ftype}:{fid}"
        if len(remove_cb.encode("utf-8")) <= 64:
            row.append(InlineKeyboardButton("🗑", callback_data=remove_cb))
        if row:
            buttons.append(row)

    buttons.append([InlineKeyboardButton(t("back_main", lang), callback_data="menu:main")])
    return InlineKeyboardMarkup(buttons)


# --- Trains (CP) Keyboards ---

def trains_menu_keyboard(lang: str = "pt") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("kb_search_train_station", lang),
                              switch_inline_query_current_chat="train ")],
        [InlineKeyboardButton(t("kb_train_lines", lang), callback_data="train:lines")],
        [InlineKeyboardButton(t("back_main", lang), callback_data="menu:main")],
    ])


def train_station_results_keyboard(stations: list[dict], lang: str = "pt") -> InlineKeyboardMarkup:
    buttons = []
    for station in stations[:8]:
        name = station["name"]
        lines_str = " ".join(l["emoji"] for l in station["lines"])
        label = f"\U0001f686 {name} {lines_str}"
        if len(label) > 55:
            label = f"\U0001f686 {name[:30]}... {lines_str}"
        cb_data = f"train:station:{name}"
        if len(cb_data.encode("utf-8")) <= 64:
            buttons.append([InlineKeyboardButton(label, callback_data=cb_data)])
    buttons.append([InlineKeyboardButton(t("kb_back", lang), callback_data="menu:trains")])
    return InlineKeyboardMarkup(buttons)


def train_station_actions_keyboard(station_name: str, is_fav: bool = False,
                                    lang: str = "pt",
                                    back_callback: str = "menu:trains") -> InlineKeyboardMarkup:
    if is_fav:
        fav_button = InlineKeyboardButton(t("kb_unfavorite", lang), callback_data=f"fav:remove:train:{station_name}")
    else:
        fav_button = InlineKeyboardButton(t("kb_favorite", lang), callback_data=f"fav:add:train:{station_name}")
    back_label = t("kb_back", lang) if back_callback != "menu:trains" else t("kb_back_menu", lang)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("kb_refresh", lang), callback_data=f"train:station:{station_name}")],
        [
            InlineKeyboardButton(t("kb_lines", lang), callback_data=f"train:station_lines:{station_name}"),
            InlineKeyboardButton(t("kb_map", lang), callback_data=f"train:loc:{station_name}"),
        ],
        [
            fav_button,
            InlineKeyboardButton(back_label, callback_data=back_callback),
        ],
    ])


def train_lines_keyboard(lang: str = "pt") -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for lid, data in CP_LINES.items():
        emoji = data["emoji"]
        name = data["name"]
        row.append(InlineKeyboardButton(f"{emoji} {name}", callback_data=f"train:line:{lid}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(t("kb_back", lang), callback_data="menu:trains")])
    return InlineKeyboardMarkup(buttons)


# --- Trip Planning Keyboards ---

def trip_results_keyboard(options: list, lang: str = "pt") -> InlineKeyboardMarkup:
    """Build keyboard showing trip route options."""
    buttons = []
    for i, opt in enumerate(options[:5]):
        label = t("trip_option_btn", lang).format(n=i + 1, time=opt.total_time_min)
        if opt.transfers > 0:
            label += f" | 🔄{opt.transfers}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"trip:detail:{i}")])
    buttons.append([InlineKeyboardButton(t("trip_new", lang), callback_data="plan:route")])
    buttons.append([InlineKeyboardButton(t("back_main", lang), callback_data="menu:main")])
    return InlineKeyboardMarkup(buttons)


def trip_detail_keyboard(option_index: int, lang: str = "pt") -> InlineKeyboardMarkup:
    """Build keyboard for trip detail view."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("trip_new", lang), callback_data="plan:route")],
        [InlineKeyboardButton(t("back_main", lang), callback_data="menu:main")],
    ])


# --- Alerts Keyboards ---

def alerts_keyboard(lang: str = "pt") -> InlineKeyboardMarkup:
    """Build keyboard for the alerts view with filter buttons."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(t("kb_alert_all", lang), callback_data="alerts:filter:all"),
            InlineKeyboardButton(t("kb_alert_delays", lang), callback_data="alerts:filter:delay"),
        ],
        [
            InlineKeyboardButton(t("kb_alert_disruptions", lang), callback_data="alerts:filter:disruption"),
            InlineKeyboardButton(t("kb_alert_engineering", lang), callback_data="alerts:filter:engineering"),
        ],
        [InlineKeyboardButton(t("kb_refresh", lang), callback_data="menu:alerts")],
        [InlineKeyboardButton(t("back_main", lang), callback_data="menu:main")],
    ])


# --- Weather Keyboards ---

def weather_keyboard(lang: str = "pt") -> InlineKeyboardMarkup:
    """Build keyboard for the weather view with refresh and back."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("kb_refresh", lang), callback_data="menu:weather")],
        [InlineKeyboardButton(t("back_main", lang), callback_data="menu:main")],
    ])


# --- Tourist Keyboards ---

def tourist_menu_keyboard(lang: str = "pt") -> InlineKeyboardMarkup:
    """Build the main tourist menu with category buttons."""
    from bot.services.tourist import TOURIST_POIS

    buttons = []
    for key, cat in TOURIST_POIS.items():
        emoji = cat["emoji"]
        title = cat["title_pt"] if lang == "pt" else cat["title_en"]
        buttons.append([
            InlineKeyboardButton(f"{emoji} {title}", callback_data=f"tourist:cat:{key}")
        ])
    buttons.append([InlineKeyboardButton(t("back_main", lang), callback_data="menu:main")])
    return InlineKeyboardMarkup(buttons)


def tourist_category_keyboard(category: str, lang: str = "pt") -> InlineKeyboardMarkup:
    """Build keyboard showing destinations in a category."""
    from bot.services.tourist import get_category

    cat = get_category(category)
    buttons = []
    if cat:
        for i, dest in enumerate(cat.get("destinations", [])):
            name = dest["name_pt"] if lang == "pt" else dest["name_en"]
            buttons.append([
                InlineKeyboardButton(
                    f"\U0001f4cd {name}",
                    callback_data=f"tourist:dest:{category}:{i}",
                )
            ])
    buttons.append([InlineKeyboardButton(t("kb_tourist_tickets", lang), callback_data="tourist:tickets")])
    buttons.append([InlineKeyboardButton(t("kb_tourist_back_menu", lang), callback_data="tourist:menu")])
    return InlineKeyboardMarkup(buttons)


def tourist_destination_keyboard(category: str, dest_index: int,
                                  station: str | None = None,
                                  lang: str = "pt") -> InlineKeyboardMarkup:
    """Build keyboard for a specific destination (map, back)."""
    buttons = []
    if station:
        cb_data = f"metro:station:{station}"
        if len(cb_data.encode("utf-8")) <= 64:
            buttons.append([
                InlineKeyboardButton(t("kb_tourist_show_map", lang), callback_data=cb_data)
            ])
    buttons.append([InlineKeyboardButton(t("kb_tourist_tickets", lang), callback_data="tourist:tickets")])
    buttons.append([InlineKeyboardButton(t("kb_tourist_back_menu", lang), callback_data=f"tourist:cat:{category}")])
    buttons.append([InlineKeyboardButton(t("back_main", lang), callback_data="menu:main")])
    return InlineKeyboardMarkup(buttons)


def tourist_tickets_keyboard(lang: str = "pt") -> InlineKeyboardMarkup:
    """Build keyboard for ticket info page."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("kb_tourist_back_menu", lang), callback_data="tourist:menu")],
        [InlineKeyboardButton(t("back_main", lang), callback_data="menu:main")],
    ])


# --- Zone Calculator Keyboards ---

def zones_menu_keyboard(lang: str = "pt") -> InlineKeyboardMarkup:
    """Build the zone calculator main menu."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("kb_zones_calculate", lang), callback_data="zones:calculate")],
        [InlineKeyboardButton(t("kb_zones_map", lang), callback_data="zones:map")],
        [InlineKeyboardButton(t("back_main", lang), callback_data="menu:main")],
    ])


def zones_result_keyboard(origin: str, dest: str, lang: str = "pt") -> InlineKeyboardMarkup:
    """Build keyboard for zone calculation result."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("kb_zones_new_calc", lang), callback_data="zones:calculate")],
        [InlineKeyboardButton(t("kb_zones_map", lang), callback_data="zones:map")],
        [InlineKeyboardButton(t("kb_zones_back", lang), callback_data="menu:zones")],
    ])


def zones_map_keyboard(lang: str = "pt") -> InlineKeyboardMarkup:
    """Build zone map overview with zone buttons."""
    from bot.services.zones import get_all_zones

    buttons = []
    row: list[InlineKeyboardButton] = []
    for zone in get_all_zones():
        row.append(InlineKeyboardButton(zone, callback_data=f"zones:zone:{zone}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    buttons.append([InlineKeyboardButton(t("kb_zones_calculate", lang), callback_data="zones:calculate")])
    buttons.append([InlineKeyboardButton(t("kb_zones_back", lang), callback_data="menu:zones")])
    return InlineKeyboardMarkup(buttons)


def zone_detail_keyboard(zone: str, lang: str = "pt") -> InlineKeyboardMarkup:
    """Build keyboard for stations in a specific zone."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("kb_zones_map", lang), callback_data="zones:map")],
        [InlineKeyboardButton(t("kb_zones_back", lang), callback_data="menu:zones")],
    ])


# --- Commuter Keyboards ---

def commuter_menu_keyboard(has_profile: bool, lang: str = "pt") -> InlineKeyboardMarkup:
    """Build the commuter profile menu keyboard."""
    if has_profile:
        return commuter_quick_actions_keyboard(lang)
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("commuter_setup", lang), callback_data="commuter:setup")],
        [InlineKeyboardButton(t("back_main", lang), callback_data="menu:main")],
    ])


def commuter_setup_keyboard(step: str, lang: str = "pt") -> InlineKeyboardMarkup:
    """Build keyboard for each commuter setup step."""
    buttons = []
    if step == "home":
        buttons.append([InlineKeyboardButton(t("kb_cancel", lang), callback_data="commuter:cancel")])
    elif step == "work":
        buttons.append([InlineKeyboardButton(t("kb_cancel", lang), callback_data="commuter:cancel")])
    elif step == "mode":
        return commuter_mode_keyboard(lang)
    elif step == "departure":
        buttons.append([InlineKeyboardButton(t("kb_cancel", lang), callback_data="commuter:cancel")])
    elif step == "return":
        buttons.append([InlineKeyboardButton(t("kb_cancel", lang), callback_data="commuter:cancel")])
    else:
        buttons.append([InlineKeyboardButton(t("back_main", lang), callback_data="menu:main")])
    return InlineKeyboardMarkup(buttons)


def commuter_quick_actions_keyboard(lang: str = "pt") -> InlineKeyboardMarkup:
    """Build quick actions keyboard for users with a commuter profile."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("commuter_go_work", lang), callback_data="commuter:go_work")],
        [InlineKeyboardButton(t("commuter_go_home", lang), callback_data="commuter:go_home")],
        [InlineKeyboardButton(t("commuter_my_times", lang), callback_data="commuter:my_times")],
        [InlineKeyboardButton(t("commuter_edit", lang), callback_data="commuter:setup")],
        [InlineKeyboardButton(t("commuter_delete", lang), callback_data="commuter:delete")],
        [InlineKeyboardButton(t("back_main", lang), callback_data="menu:main")],
    ])


def commuter_mode_keyboard(lang: str = "pt") -> InlineKeyboardMarkup:
    """Build transport mode selection keyboard."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("commuter_mode_metro", lang), callback_data="commuter:mode:metro")],
        [InlineKeyboardButton(t("commuter_mode_bus", lang), callback_data="commuter:mode:bus")],
        [InlineKeyboardButton(t("commuter_mode_any", lang), callback_data="commuter:mode:any")],
        [InlineKeyboardButton(t("kb_cancel", lang), callback_data="commuter:cancel")],
    ])


# --- Accessibility Keyboards ---

def accessibility_menu_keyboard(lang: str = "pt") -> InlineKeyboardMarkup:
    """Build the accessibility main menu keyboard."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("kb_accessibility_search", lang), callback_data="access:search")],
        [InlineKeyboardButton(t("kb_accessibility_elevators", lang), callback_data="access:elevators")],
        [InlineKeyboardButton(t("back_main", lang), callback_data="menu:main")],
    ])


def accessibility_station_keyboard(station_name: str, lang: str = "pt") -> InlineKeyboardMarkup:
    """Build keyboard for a specific station's accessibility info."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("kb_accessibility_search", lang), callback_data="access:search")],
        [InlineKeyboardButton(t("kb_accessibility_elevators", lang), callback_data="access:elevators")],
        [InlineKeyboardButton(t("kb_back", lang), callback_data="menu:accessibility")],
    ])


# --- Events Keyboards ---

def events_today_keyboard(events_list: list, lang: str = "pt",
                          show_more: bool = True,
                          upcoming: bool = False) -> InlineKeyboardMarkup:
    """Build keyboard showing today's (or upcoming) events.

    Args:
        events_list: Events to render as buttons.
        lang: ``"pt"`` or ``"en"``.
        show_more: When False the "more events" button is omitted -- used when
            there is nothing else to show, so the button is never a dead end.
        upcoming: When True the list is of future events rather than today's,
            so a direct "all events" shortcut is offered as well.
    """
    from bot.services.events import EVENTS

    buttons = []
    for event in events_list:
        idx = EVENTS.index(event)
        name = event.name_pt if lang == "pt" else event.name_en
        date_info = event.date_info_pt if lang == "pt" else event.date_info_en
        label = f"{event.emoji} {name} — {date_info}"
        if len(label) > 55:
            label = f"{event.emoji} {name[:48]}..."
        buttons.append([
            InlineKeyboardButton(label, callback_data=f"events:detail:{idx}")
        ])
    if upcoming:
        buttons.append([InlineKeyboardButton(t("kb_events_all", lang),
                                             callback_data="events:cat:all")])
    if show_more:
        buttons.append([InlineKeyboardButton(t("kb_events_more", lang),
                                             callback_data="events:categories")])
    buttons.append([InlineKeyboardButton(t("back_main", lang), callback_data="menu:main")])
    return InlineKeyboardMarkup(buttons)


def events_menu_keyboard(lang: str = "pt") -> InlineKeyboardMarkup:
    """Build the events category menu."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("kb_events_all", lang), callback_data="events:cat:all")],
        [InlineKeyboardButton(t("kb_events_football", lang), callback_data="events:cat:football")],
        [InlineKeyboardButton(t("kb_events_festival", lang), callback_data="events:cat:festival")],
        [InlineKeyboardButton(t("kb_events_music", lang), callback_data="events:cat:music")],
        [InlineKeyboardButton(t("kb_events_culture", lang), callback_data="events:cat:culture")],
        [InlineKeyboardButton(t("back_main", lang), callback_data="menu:main")],
    ])


def events_category_keyboard(events_list: list, lang: str = "pt") -> InlineKeyboardMarkup:
    """Build keyboard showing events in a category."""
    from bot.services.events import EVENTS

    buttons = []
    for event in events_list:
        idx = EVENTS.index(event)
        name = event.name_pt if lang == "pt" else event.name_en
        label = f"{event.emoji} {name}"
        if len(label) > 55:
            label = f"{event.emoji} {name[:48]}..."
        buttons.append([
            InlineKeyboardButton(label, callback_data=f"events:detail:{idx}")
        ])
    buttons.append([InlineKeyboardButton(t("kb_events_back_menu", lang), callback_data="menu:events")])
    return InlineKeyboardMarkup(buttons)


def events_detail_keyboard(event_index: int, category: str, lang: str = "pt") -> InlineKeyboardMarkup:
    """Build keyboard for event detail view with station button."""
    from bot.services.events import get_event
    from bot.services.metro import STATIONS

    event = get_event(event_index)
    buttons = []
    if event and event.nearest_station in STATIONS:
        cb_data = f"metro:station:{event.nearest_station}"
        if len(cb_data.encode("utf-8")) <= 64:
            buttons.append([
                InlineKeyboardButton(t("kb_tourist_show_map", lang), callback_data=cb_data)
            ])
    buttons.append([InlineKeyboardButton(t("kb_events_back_menu", lang), callback_data="menu:events")])
    buttons.append([InlineKeyboardButton(t("back_main", lang), callback_data="menu:main")])
    return InlineKeyboardMarkup(buttons)
