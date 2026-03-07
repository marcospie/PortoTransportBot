"""Favorites management handlers."""

import json
import logging
from pathlib import Path

from telegram import Update
from telegram.ext import ContextTypes

from bot.config import DATA_DIR
from bot.keyboards.inline import favorites_keyboard
from bot.utils.formatting import escape_md

logger = logging.getLogger(__name__)

FAVORITES_DIR = DATA_DIR / "favorites"


def _get_favorites_path(user_id: int) -> Path:
    FAVORITES_DIR.mkdir(parents=True, exist_ok=True)
    return FAVORITES_DIR / f"{user_id}.json"


def _load_favorites(user_id: int) -> list[dict]:
    path = _get_favorites_path(user_id)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def _save_favorites(user_id: int, favorites: list[dict]) -> None:
    path = _get_favorites_path(user_id)
    path.write_text(json.dumps(favorites, ensure_ascii=False, indent=2))


async def favorites_command(update: Update,
                             context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /favorites command."""
    user_id = update.effective_user.id
    favs = _load_favorites(user_id)

    if not favs:
        text = (
            "⭐ *Os teus favoritos*\n\n"
            "Ainda não tens favoritos\\.\n"
            "Adiciona paragens ou estações aos favoritos "
            "usando o botão ⭐ nas páginas de consulta\\."
        )
    else:
        text = f"⭐ *Os teus favoritos* \\({escape_md(str(len(favs)))}\\)\n\nSeleciona para consultar:"

    await update.message.reply_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=favorites_keyboard(favs),
    )


async def favorites_callback(update: Update,
                               context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show favorites menu via callback."""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    favs = _load_favorites(user_id)

    if not favs:
        text = (
            "⭐ *Os teus favoritos*\n\n"
            "Ainda não tens favoritos\\.\n"
            "Adiciona paragens ou estações aos favoritos "
            "usando o botão ⭐ nas páginas de consulta\\."
        )
    else:
        text = f"⭐ *Os teus favoritos* \\({escape_md(str(len(favs)))}\\)\n\nSeleciona para consultar:"

    await query.edit_message_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=favorites_keyboard(favs),
    )


async def add_favorite_callback(update: Update,
                                  context: ContextTypes.DEFAULT_TYPE) -> None:
    """Add a stop/station to favorites."""
    query = update.callback_query
    user_id = update.effective_user.id

    # Parse callback data: fav:add:bus:BCM2 or fav:add:metro:Trindade
    parts = query.data.split(":", 3)
    if len(parts) < 4:
        await query.answer("Erro ao adicionar favorito")
        return

    fav_type = parts[2]  # bus or metro
    fav_id = parts[3]    # stop_id or station_name

    favs = _load_favorites(user_id)

    # Check if already favorited
    if any(f["type"] == fav_type and f["id"] == fav_id for f in favs):
        await query.answer("Já está nos favoritos! ⭐")
        return

    # Get name
    if fav_type == "bus":
        from bot.services import stcp
        info = await stcp.get_stop_info(fav_id)
        name = info.get("name", fav_id)
    else:
        name = fav_id

    favs.append({
        "type": fav_type,
        "id": fav_id,
        "name": name,
    })
    _save_favorites(user_id, favs)

    await query.answer(f"Adicionado aos favoritos! ⭐ {name}")


async def remove_favorite_callback(update: Update,
                                     context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remove a stop/station from favorites."""
    query = update.callback_query
    user_id = update.effective_user.id

    parts = query.data.split(":", 3)
    if len(parts) < 4:
        await query.answer("Erro ao remover favorito")
        return

    fav_type = parts[2]
    fav_id = parts[3]

    favs = _load_favorites(user_id)
    favs = [f for f in favs if not (f["type"] == fav_type and f["id"] == fav_id)]
    _save_favorites(user_id, favs)

    await query.answer("Removido dos favoritos ❌")

    # Refresh the favorites list
    if not favs:
        text = (
            "⭐ *Os teus favoritos*\n\n"
            "Ainda não tens favoritos\\.\n"
            "Adiciona paragens ou estações aos favoritos "
            "usando o botão ⭐ nas páginas de consulta\\."
        )
    else:
        text = f"⭐ *Os teus favoritos* \\({escape_md(str(len(favs)))}\\)\n\nSeleciona para consultar:"

    await query.edit_message_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=favorites_keyboard(favs),
    )
