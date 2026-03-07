"""Inline keyboard builders for the Telegram bot."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import METRO_LINES


# --- Main Menu ---

def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🚌 Autocarros (STCP)", callback_data="menu:bus"),
            InlineKeyboardButton("🚇 Metro", callback_data="menu:metro"),
        ],
        [
            InlineKeyboardButton("⭐ Favoritos", callback_data="menu:favorites"),
            InlineKeyboardButton("ℹ️ Ajuda", callback_data="menu:help"),
        ],
    ])


# --- Bus (STCP) Keyboards ---

def bus_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Pesquisar paragem", callback_data="bus:search")],
        [InlineKeyboardButton("📍 Paragem por código", callback_data="bus:code")],
        [InlineKeyboardButton("🚌 Ver linhas", callback_data="bus:routes")],
        [InlineKeyboardButton("🔙 Menu principal", callback_data="menu:main")],
    ])


def bus_stop_results_keyboard(stops: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for stop in stops[:8]:
        stop_id = stop["stop_id"]
        name = stop["name"]
        label = f"🚏 {name} ({stop_id})"
        if len(label) > 50:
            label = f"🚏 {name[:35]}... ({stop_id})"
        buttons.append([
            InlineKeyboardButton(label, callback_data=f"bus:stop:{stop_id}")
        ])
    buttons.append([InlineKeyboardButton("🔙 Voltar", callback_data="menu:bus")])
    return InlineKeyboardMarkup(buttons)


def bus_stop_actions_keyboard(stop_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Atualizar", callback_data=f"bus:stop:{stop_id}")],
        [
            InlineKeyboardButton("ℹ️ Info paragem", callback_data=f"bus:info:{stop_id}"),
            InlineKeyboardButton("⭐ Favoritar", callback_data=f"fav:add:bus:{stop_id}"),
        ],
        [InlineKeyboardButton("🔙 Voltar", callback_data="menu:bus")],
    ])


def bus_routes_keyboard(routes: list[dict], page: int = 0,
                        per_page: int = 8) -> InlineKeyboardMarkup:
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
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Anterior", callback_data=f"bus:routes:page:{page - 1}"))
    if end < len(routes):
        nav_row.append(InlineKeyboardButton("Seguinte ➡️", callback_data=f"bus:routes:page:{page + 1}"))
    if nav_row:
        buttons.append(nav_row)

    buttons.append([InlineKeyboardButton("🔙 Voltar", callback_data="menu:bus")])
    return InlineKeyboardMarkup(buttons)


# --- Metro Keyboards ---

def metro_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Pesquisar estação", callback_data="metro:search")],
        [InlineKeyboardButton("🗺 Ver linhas", callback_data="metro:lines")],
        [InlineKeyboardButton("🕐 Frequências", callback_data="metro:freq")],
        [InlineKeyboardButton("🔙 Menu principal", callback_data="menu:main")],
    ])


def metro_lines_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    for code, data in METRO_LINES.items():
        emoji = data["emoji"]
        name = data["name"]
        buttons.append([
            InlineKeyboardButton(f"{emoji} {name}", callback_data=f"metro:line:{code}")
        ])
    buttons.append([InlineKeyboardButton("🔙 Voltar", callback_data="menu:metro")])
    return InlineKeyboardMarkup(buttons)


def metro_station_results_keyboard(stations: list[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for station in stations[:8]:
        name = station["name"]
        lines_str = " ".join(l["emoji"] for l in station["lines"])
        label = f"🚇 {name} {lines_str}"
        if len(label) > 55:
            label = f"🚇 {name[:30]}... {lines_str}"
        buttons.append([
            InlineKeyboardButton(label, callback_data=f"metro:station:{name}")
        ])
    buttons.append([InlineKeyboardButton("🔙 Voltar", callback_data="menu:metro")])
    return InlineKeyboardMarkup(buttons)


def metro_station_actions_keyboard(station_name: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Atualizar", callback_data=f"metro:station:{station_name}")],
        [
            InlineKeyboardButton("🗺 Linhas", callback_data=f"metro:station_lines:{station_name}"),
            InlineKeyboardButton("⭐ Favoritar", callback_data=f"fav:add:metro:{station_name}"),
        ],
        [InlineKeyboardButton("🔙 Voltar", callback_data="menu:metro")],
    ])


def metro_line_actions_keyboard(line_code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Frequências", callback_data=f"metro:line_freq:{line_code}")],
        [InlineKeyboardButton("🔙 Voltar", callback_data="metro:lines")],
    ])


# --- Favorites Keyboards ---

def favorites_keyboard(favorites: list[dict]) -> InlineKeyboardMarkup:
    if not favorites:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🚌 Ir a autocarros", callback_data="menu:bus")],
            [InlineKeyboardButton("🚇 Ir ao metro", callback_data="menu:metro")],
            [InlineKeyboardButton("🔙 Menu principal", callback_data="menu:main")],
        ])

    buttons = []
    for fav in favorites[:10]:
        ftype = fav["type"]
        fid = fav["id"]
        name = fav.get("name", fid)
        if ftype == "bus":
            buttons.append([
                InlineKeyboardButton(f"🚌 {name} ({fid})", callback_data=f"bus:stop:{fid}"),
                InlineKeyboardButton("❌", callback_data=f"fav:remove:{ftype}:{fid}"),
            ])
        else:
            buttons.append([
                InlineKeyboardButton(f"🚇 {name}", callback_data=f"metro:station:{fid}"),
                InlineKeyboardButton("❌", callback_data=f"fav:remove:{ftype}:{fid}"),
            ])

    buttons.append([InlineKeyboardButton("🔙 Menu principal", callback_data="menu:main")])
    return InlineKeyboardMarkup(buttons)
