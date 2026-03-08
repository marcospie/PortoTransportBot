"""Handler for Commuter Profile (Perfil Commuter) feature."""

import logging
import re

from telegram import Update
from telegram.ext import ContextTypes

from bot.database import (
    get_commuter_profile,
    save_commuter_profile,
    delete_commuter_profile,
)
from bot.keyboards.inline import (
    commuter_menu_keyboard,
    commuter_setup_keyboard,
    commuter_quick_actions_keyboard,
    commuter_mode_keyboard,
)
from bot.utils.i18n import t, get_lang
from bot.utils.formatting import escape_md

logger = logging.getLogger(__name__)

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

# Mode labels for display
_MODE_LABELS = {
    "metro": "commuter_mode_metro",
    "bus": "commuter_mode_bus",
    "any": "commuter_mode_any",
}


def _mode_label(mode: str, lang: str) -> str:
    key = _MODE_LABELS.get(mode, "commuter_mode_any")
    return t(key, lang)


def _resolve_location(query: str) -> dict | None:
    """Try to resolve a location name to coordinates.

    Searches metro stations first, then bus stops (sync search only).
    Returns dict with name/lat/lon or None.
    """
    from bot.services.metro import STATIONS

    # Try metro stations
    query_lower = query.lower()
    for name, data in STATIONS.items():
        if query_lower in name.lower():
            return {
                "name": name,
                "lat": data["lat"],
                "lon": data["lon"],
            }

    return None


async def _resolve_location_async(query: str) -> dict | None:
    """Try to resolve a location, including async bus stop search."""
    # First try sync metro search
    result = _resolve_location(query)
    if result:
        return result

    # Try bus stops
    try:
        from bot.services.stcp import search_stops
        stops = await search_stops(query)
        if stops:
            stop = stops[0]
            return {
                "name": stop.get("name", query),
                "lat": stop.get("lat", 0.0),
                "lon": stop.get("lon", 0.0),
            }
    except Exception:
        pass

    return None


# ===================================================================
# Command
# ===================================================================

async def commuter_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /commuter command."""
    user_id = update.effective_user.id
    lang = get_lang(update)
    profile = await get_commuter_profile(user_id)

    if profile:
        mode_label = _mode_label(profile.get("preferred_mode", "any"), lang)
        text = t("commuter_title", lang) + "\n\n" + t("commuter_profile_summary", lang).format(
            home=escape_md(profile.get("home_name", "?")),
            work=escape_md(profile.get("work_name", "?")),
            mode=escape_md(mode_label),
            departure=escape_md(profile.get("usual_departure_time", "08:00")),
            return_time=escape_md(profile.get("usual_return_time", "18:00")),
        )
    else:
        text = t("commuter_title", lang) + "\n\n" + t("commuter_no_profile", lang)

    await update.message.reply_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=commuter_menu_keyboard(profile is not None, lang),
    )


# ===================================================================
# Callbacks
# ===================================================================

async def commuter_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show commuter menu (from inline button)."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    lang = get_lang(update)
    profile = await get_commuter_profile(user_id)

    if profile:
        mode_label = _mode_label(profile.get("preferred_mode", "any"), lang)
        text = t("commuter_title", lang) + "\n\n" + t("commuter_profile_summary", lang).format(
            home=escape_md(profile.get("home_name", "?")),
            work=escape_md(profile.get("work_name", "?")),
            mode=escape_md(mode_label),
            departure=escape_md(profile.get("usual_departure_time", "08:00")),
            return_time=escape_md(profile.get("usual_return_time", "18:00")),
        )
    else:
        text = t("commuter_title", lang) + "\n\n" + t("commuter_no_profile", lang)

    await query.edit_message_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=commuter_menu_keyboard(profile is not None, lang),
    )


async def commuter_setup_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start commuter profile setup - step 1: ask for home location."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)

    # Initialize setup data in user context
    context.user_data["commuter_setup"] = {}
    context.user_data["commuter_step"] = "home"

    await query.edit_message_text(
        t("commuter_ask_home", lang),
        parse_mode="MarkdownV2",
        reply_markup=commuter_setup_keyboard("home", lang),
    )


async def commuter_mode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle transport mode selection."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)

    mode = query.data.split(":")[-1]  # commuter:mode:<mode>
    setup = context.user_data.get("commuter_setup", {})
    setup["preferred_mode"] = mode

    # Move to departure time step
    context.user_data["commuter_step"] = "departure"

    await query.edit_message_text(
        t("commuter_ask_departure", lang),
        parse_mode="MarkdownV2",
        reply_markup=commuter_setup_keyboard("departure", lang),
    )


async def commuter_cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Cancel commuter setup."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)

    context.user_data.pop("commuter_setup", None)
    context.user_data.pop("commuter_step", None)

    user_id = update.effective_user.id
    profile = await get_commuter_profile(user_id)

    if profile:
        mode_label = _mode_label(profile.get("preferred_mode", "any"), lang)
        text = t("commuter_title", lang) + "\n\n" + t("commuter_profile_summary", lang).format(
            home=escape_md(profile.get("home_name", "?")),
            work=escape_md(profile.get("work_name", "?")),
            mode=escape_md(mode_label),
            departure=escape_md(profile.get("usual_departure_time", "08:00")),
            return_time=escape_md(profile.get("usual_return_time", "18:00")),
        )
    else:
        text = t("commuter_title", lang) + "\n\n" + t("commuter_no_profile", lang)

    await query.edit_message_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=commuter_menu_keyboard(profile is not None, lang),
    )


async def commuter_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete commuter profile."""
    query = update.callback_query
    user_id = update.effective_user.id
    lang = get_lang(update)

    await delete_commuter_profile(user_id)
    await query.answer(t("commuter_deleted", lang))

    text = t("commuter_title", lang) + "\n\n" + t("commuter_no_profile", lang)
    await query.edit_message_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=commuter_menu_keyboard(False, lang),
    )


async def commuter_go_work_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show route from home to work."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    lang = get_lang(update)

    profile = await get_commuter_profile(user_id)
    if not profile:
        await query.edit_message_text(
            t("commuter_no_profile", lang),
            parse_mode="MarkdownV2",
            reply_markup=commuter_menu_keyboard(False, lang),
        )
        return

    mode_label = _mode_label(profile.get("preferred_mode", "any"), lang)
    text = t("commuter_route_to_work", lang).format(
        home=escape_md(profile.get("home_name", "?")),
        work=escape_md(profile.get("work_name", "?")),
        mode=escape_md(mode_label),
    )

    await query.edit_message_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=commuter_quick_actions_keyboard(lang),
    )


async def commuter_go_home_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show route from work to home."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    lang = get_lang(update)

    profile = await get_commuter_profile(user_id)
    if not profile:
        await query.edit_message_text(
            t("commuter_no_profile", lang),
            parse_mode="MarkdownV2",
            reply_markup=commuter_menu_keyboard(False, lang),
        )
        return

    mode_label = _mode_label(profile.get("preferred_mode", "any"), lang)
    text = t("commuter_route_to_home", lang).format(
        home=escape_md(profile.get("home_name", "?")),
        work=escape_md(profile.get("work_name", "?")),
        mode=escape_md(mode_label),
    )

    await query.edit_message_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=commuter_quick_actions_keyboard(lang),
    )


async def commuter_my_times_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show user's usual commute times."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    lang = get_lang(update)

    profile = await get_commuter_profile(user_id)
    if not profile:
        await query.edit_message_text(
            t("commuter_no_profile", lang),
            parse_mode="MarkdownV2",
            reply_markup=commuter_menu_keyboard(False, lang),
        )
        return

    text = t("commuter_my_times_msg", lang).format(
        departure=escape_md(profile.get("usual_departure_time", "08:00")),
        return_time=escape_md(profile.get("usual_return_time", "18:00")),
        home=escape_md(profile.get("home_name", "?")),
        work=escape_md(profile.get("work_name", "?")),
    )

    await query.edit_message_text(
        text,
        parse_mode="MarkdownV2",
        reply_markup=commuter_quick_actions_keyboard(lang),
    )


# ===================================================================
# Text input handler (for setup flow)
# ===================================================================

async def handle_commuter_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle text input during commuter setup. Returns True if handled."""
    step = context.user_data.get("commuter_step")
    if not step:
        return False

    text = update.message.text.strip()
    lang = get_lang(update)
    user_id = update.effective_user.id
    setup = context.user_data.get("commuter_setup", {})

    if step == "home":
        location = await _resolve_location_async(text)
        if not location:
            await update.message.reply_text(
                t("commuter_location_not_found", lang).format(query=escape_md(text)),
                parse_mode="MarkdownV2",
                reply_markup=commuter_setup_keyboard("home", lang),
            )
            return True

        setup["home_name"] = location["name"]
        setup["home_lat"] = location["lat"]
        setup["home_lon"] = location["lon"]
        context.user_data["commuter_setup"] = setup
        context.user_data["commuter_step"] = "work"

        await update.message.reply_text(
            t("commuter_ask_work", lang),
            parse_mode="MarkdownV2",
            reply_markup=commuter_setup_keyboard("work", lang),
        )
        return True

    elif step == "work":
        location = await _resolve_location_async(text)
        if not location:
            await update.message.reply_text(
                t("commuter_location_not_found", lang).format(query=escape_md(text)),
                parse_mode="MarkdownV2",
                reply_markup=commuter_setup_keyboard("work", lang),
            )
            return True

        setup["work_name"] = location["name"]
        setup["work_lat"] = location["lat"]
        setup["work_lon"] = location["lon"]
        context.user_data["commuter_setup"] = setup
        context.user_data["commuter_step"] = "mode"

        await update.message.reply_text(
            t("commuter_ask_mode", lang),
            parse_mode="MarkdownV2",
            reply_markup=commuter_mode_keyboard(lang),
        )
        return True

    elif step == "departure":
        if not _TIME_RE.match(text):
            await update.message.reply_text(
                t("commuter_invalid_time", lang),
                parse_mode="MarkdownV2",
                reply_markup=commuter_setup_keyboard("departure", lang),
            )
            return True

        setup["usual_departure_time"] = text
        context.user_data["commuter_setup"] = setup
        context.user_data["commuter_step"] = "return"

        await update.message.reply_text(
            t("commuter_ask_return", lang),
            parse_mode="MarkdownV2",
            reply_markup=commuter_setup_keyboard("return", lang),
        )
        return True

    elif step == "return":
        if not _TIME_RE.match(text):
            await update.message.reply_text(
                t("commuter_invalid_time", lang),
                parse_mode="MarkdownV2",
                reply_markup=commuter_setup_keyboard("return", lang),
            )
            return True

        setup["usual_return_time"] = text
        context.user_data["commuter_setup"] = setup

        # Save the profile
        await save_commuter_profile(user_id, setup)

        # Clear setup state
        context.user_data.pop("commuter_setup", None)
        context.user_data.pop("commuter_step", None)

        mode_label = _mode_label(setup.get("preferred_mode", "any"), lang)
        text_msg = t("commuter_confirm", lang).format(
            home=escape_md(setup.get("home_name", "?")),
            work=escape_md(setup.get("work_name", "?")),
            mode=escape_md(mode_label),
            departure=escape_md(setup.get("usual_departure_time", "08:00")),
            return_time=escape_md(setup.get("usual_return_time", "18:00")),
        )

        await update.message.reply_text(
            text_msg,
            parse_mode="MarkdownV2",
            reply_markup=commuter_quick_actions_keyboard(lang),
        )
        return True

    return False
