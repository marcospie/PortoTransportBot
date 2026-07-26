"""Handler for Commuter Profile (Perfil Commuter) feature."""

import logging
import re

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    Update,
)
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
from bot.handlers.routes import tf, format_trip_option, plain
from bot.services.trip_planner import (
    is_valid_porto_coords,
    plan_trip_from_coords_async,
    resolve_location as resolve_transport_location,
    resolve_location_any,
)
from bot.utils.i18n import t, get_lang
from bot.utils.formatting import escape_md
from bot.utils.telegram import safe_edit_message

logger = logging.getLogger(__name__)

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

# Steps of the setup wizard that accept a shared location.
_LOCATION_STEPS = ("home", "work")

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
    """Resolve a location name to coordinates across *all* transport modes.

    The previous implementation substring-matched metro station names only, and
    its bus fallback blindly took the first search hit with ``lat``/``lon``
    defaulting to ``0.0`` — which silently wrote a broken profile.  This now
    goes through the trip planner's resolver (metro + CP + MetroBus) and only
    returns coordinates that pass validation.
    """
    if not query or not query.strip():
        return None

    result = resolve_transport_location(query)
    if not result:
        return None
    if not is_valid_porto_coords(result.get("lat"), result.get("lon")):
        logger.warning("Refusing location %r with invalid coordinates %r/%r",
                       result.get("name"), result.get("lat"), result.get("lon"))
        return None
    return {
        "name": result["name"],
        "lat": float(result["lat"]),
        "lon": float(result["lon"]),
    }


async def _resolve_location_async(query: str) -> dict | None:
    """Resolve a location, including STCP bus stops (async lookup)."""
    result = _resolve_location(query)
    if result:
        return result

    try:
        found = await resolve_location_any(query)
    except Exception:
        logger.debug("Async location resolution failed for %r", query, exc_info=True)
        return None

    if not found:
        return None
    if not is_valid_porto_coords(found.get("lat"), found.get("lon")):
        logger.warning("Refusing STCP location %r with invalid coordinates",
                       found.get("name"))
        return None
    return {
        "name": found["name"],
        "lat": float(found["lat"]),
        "lon": float(found["lon"]),
    }


def _setup_reply_keyboard(lang: str) -> ReplyKeyboardMarkup:
    """One-time keyboard letting the user share a location during setup."""
    return ReplyKeyboardMarkup(
        [[KeyboardButton(tf("commuter_share_location_button", lang),
                         request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def _profile_text(profile: dict | None, lang: str) -> str:
    if profile:
        mode_label = _mode_label(profile.get("preferred_mode", "any"), lang)
        return t("commuter_title", lang) + "\n\n" + t("commuter_profile_summary", lang).format(
            home=escape_md(profile.get("home_name", "?")),
            work=escape_md(profile.get("work_name", "?")),
            mode=escape_md(mode_label),
            departure=escape_md(profile.get("usual_departure_time", "08:00")),
            return_time=escape_md(profile.get("usual_return_time", "18:00")),
        )
    return t("commuter_title", lang) + "\n\n" + t("commuter_no_profile", lang)


def profile_coords(profile: dict) -> tuple[float, float, float, float] | None:
    """Return (home_lat, home_lon, work_lat, work_lon) when all are valid."""
    home_lat = profile.get("home_lat")
    home_lon = profile.get("home_lon")
    work_lat = profile.get("work_lat")
    work_lon = profile.get("work_lon")
    if not is_valid_porto_coords(home_lat, home_lon):
        return None
    if not is_valid_porto_coords(work_lat, work_lon):
        return None
    return float(home_lat), float(home_lon), float(work_lat), float(work_lon)


# ===================================================================
# Command
# ===================================================================

async def commuter_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /commuter command."""
    user_id = update.effective_user.id
    lang = get_lang(update)
    profile = await get_commuter_profile(user_id)

    await update.message.reply_text(
        _profile_text(profile, lang),
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

    await safe_edit_message(
        query,
        _profile_text(profile, lang),
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

    await safe_edit_message(
        query,
        t("commuter_ask_home", lang) + "\n\n" + tf("commuter_location_hint", lang),
        reply_markup=commuter_setup_keyboard("home", lang),
    )

    # Offer a real "share location" button — arbitrary addresses cannot be
    # resolved by name, but a shared pin always works.
    try:
        await query.message.reply_text(
            tf("commuter_location_hint", lang),
            parse_mode="MarkdownV2",
            reply_markup=_setup_reply_keyboard(lang),
        )
    except Exception:
        logger.debug("Could not attach the setup location keyboard", exc_info=True)


async def commuter_mode_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle transport mode selection."""
    query = update.callback_query
    await query.answer()
    lang = get_lang(update)

    mode = query.data.split(":")[-1]  # commuter:mode:<mode>
    setup = context.user_data.get("commuter_setup", {})
    setup["preferred_mode"] = mode
    context.user_data["commuter_setup"] = setup

    # Move to departure time step
    context.user_data["commuter_step"] = "departure"

    await safe_edit_message(
        query,
        t("commuter_ask_departure", lang),
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

    await safe_edit_message(
        query,
        _profile_text(profile, lang),
        reply_markup=commuter_menu_keyboard(profile is not None, lang),
    )


async def commuter_delete_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Delete commuter profile."""
    query = update.callback_query
    user_id = update.effective_user.id
    lang = get_lang(update)

    await delete_commuter_profile(user_id)
    await query.answer(plain(t("commuter_deleted", lang)))

    await safe_edit_message(
        query,
        _profile_text(None, lang),
        reply_markup=commuter_menu_keyboard(False, lang),
    )


def _commuter_results_keyboard(options: list, lang: str) -> InlineKeyboardMarkup:
    """Trip option buttons plus a way back into the commuter menu."""
    buttons: list[list[InlineKeyboardButton]] = []
    for i, opt in enumerate(options[:5]):
        label = t("trip_option_btn", lang).format(n=i + 1, time=opt.total_time_min)
        if opt.transfers > 0:
            label += f" | 🔄{opt.transfers}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"trip:detail:{i}")])
    buttons.append([InlineKeyboardButton(t("commuter_go_work", lang),
                                        callback_data="commuter:go_work")])
    buttons.append([InlineKeyboardButton(t("commuter_go_home", lang),
                                        callback_data="commuter:go_home")])
    buttons.append([InlineKeyboardButton(t("back", lang),
                                        callback_data="menu:commuter")])
    return InlineKeyboardMarkup(buttons)


async def _show_commute_route(update: Update, context: ContextTypes.DEFAULT_TYPE,
                              to_work: bool) -> None:
    """Plan and render the real route between home and work."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    lang = get_lang(update)

    profile = await get_commuter_profile(user_id)
    if not profile:
        await safe_edit_message(
            query,
            t("commuter_no_profile", lang),
            reply_markup=commuter_menu_keyboard(False, lang),
        )
        return

    mode_label = _mode_label(profile.get("preferred_mode", "any"), lang)
    header_key = "commuter_route_to_work" if to_work else "commuter_route_to_home"
    header = t(header_key, lang).format(
        home=escape_md(profile.get("home_name", "?")),
        work=escape_md(profile.get("work_name", "?")),
        mode=escape_md(mode_label),
    )

    coords = profile_coords(profile)
    if coords is None:
        # A profile written by the old, unvalidated setup flow.
        await safe_edit_message(
            query,
            header + "\n\n" + tf("commuter_profile_incomplete", lang),
            reply_markup=commuter_quick_actions_keyboard(lang),
        )
        return

    home_lat, home_lon, work_lat, work_lon = coords
    if to_work:
        o_lat, o_lon, d_lat, d_lon = home_lat, home_lon, work_lat, work_lon
    else:
        o_lat, o_lon, d_lat, d_lon = work_lat, work_lon, home_lat, home_lon

    try:
        options = await plan_trip_from_coords_async(o_lat, o_lon, d_lat, d_lon)
    except Exception:
        logger.exception("Commuter trip planning failed")
        options = []

    if not options:
        await safe_edit_message(
            query,
            header + "\n\n" + t("trip_no_routes", lang),
            reply_markup=commuter_quick_actions_keyboard(lang),
        )
        return

    context.user_data["trip_options"] = options

    parts = [header, "━━━━━━━━━━━━━━━━\n"]
    for i, opt in enumerate(options[:3], 1):
        parts.append(format_trip_option(opt, i, lang))
        parts.append("")

    text = "\n".join(parts)
    if len(text) > 4000:
        text = text[:3990] + "\\.\\.\\."

    await safe_edit_message(
        query, text, reply_markup=_commuter_results_keyboard(options, lang),
    )


async def commuter_go_work_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the real route from home to work."""
    await _show_commute_route(update, context, to_work=True)


async def commuter_go_home_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show the real route from work to home."""
    await _show_commute_route(update, context, to_work=False)


async def commuter_my_times_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show user's usual commute times."""
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    lang = get_lang(update)

    profile = await get_commuter_profile(user_id)
    if not profile:
        await safe_edit_message(
            query,
            t("commuter_no_profile", lang),
            reply_markup=commuter_menu_keyboard(False, lang),
        )
        return

    text = t("commuter_my_times_msg", lang).format(
        departure=escape_md(profile.get("usual_departure_time", "08:00")),
        return_time=escape_md(profile.get("usual_return_time", "18:00")),
        home=escape_md(profile.get("home_name", "?")),
        work=escape_md(profile.get("work_name", "?")),
    )

    await safe_edit_message(query, text,
                            reply_markup=commuter_quick_actions_keyboard(lang))


# ===================================================================
# Setup flow input handling
# ===================================================================

async def _store_setup_location(update: Update, context: ContextTypes.DEFAULT_TYPE,
                                step: str, location: dict, lang: str) -> None:
    """Persist a resolved home/work location and advance the wizard."""
    setup = context.user_data.get("commuter_setup", {})
    prefix = "home" if step == "home" else "work"
    setup[f"{prefix}_name"] = location["name"]
    setup[f"{prefix}_lat"] = location["lat"]
    setup[f"{prefix}_lon"] = location["lon"]
    context.user_data["commuter_setup"] = setup

    if step == "home":
        context.user_data["commuter_step"] = "work"
        await update.message.reply_text(
            t("commuter_ask_work", lang) + "\n\n" + tf("commuter_location_hint", lang),
            parse_mode="MarkdownV2",
            reply_markup=commuter_setup_keyboard("work", lang),
        )
    else:
        context.user_data["commuter_step"] = "mode"
        await update.message.reply_text(
            t("commuter_ask_mode", lang),
            parse_mode="MarkdownV2",
            reply_markup=commuter_mode_keyboard(lang),
        )


async def handle_commuter_location(update: Update,
                                   context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Consume a shared location as the home/work step. Returns True if handled.

    Called from the location handler so people whose home is an ordinary address
    (i.e. almost everyone) can set up a profile at all.
    """
    step = context.user_data.get("commuter_step") if isinstance(
        getattr(context, "user_data", None), dict) else None
    if step not in _LOCATION_STEPS:
        return False

    location = getattr(update.message, "location", None)
    if not location:
        return False

    lang = get_lang(update)
    lat, lon = location.latitude, location.longitude

    if not is_valid_porto_coords(lat, lon):
        await update.message.reply_text(
            tf("commuter_invalid_coords", lang),
            parse_mode="MarkdownV2",
            reply_markup=commuter_setup_keyboard(step, lang),
        )
        return True

    label = "🏠 " if step == "home" else "🏢 "
    resolved = {
        "name": label + tf("my_location", lang),
        "lat": float(lat),
        "lon": float(lon),
    }
    await _store_setup_location(update, context, step, resolved, lang)
    return True


async def handle_commuter_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Handle text input during commuter setup. Returns True if handled."""
    step = context.user_data.get("commuter_step")
    if not step:
        return False

    text = update.message.text.strip()
    lang = get_lang(update)
    user_id = update.effective_user.id
    setup = context.user_data.get("commuter_setup", {})

    if step in _LOCATION_STEPS:
        location = await _resolve_location_async(text)
        if not location:
            await update.message.reply_text(
                t("commuter_location_not_found", lang).format(query=escape_md(text))
                + "\n\n" + tf("commuter_location_hint", lang),
                parse_mode="MarkdownV2",
                reply_markup=commuter_setup_keyboard(step, lang),
            )
            return True

        if not is_valid_porto_coords(location.get("lat"), location.get("lon")):
            # Never store a broken profile.
            await update.message.reply_text(
                tf("commuter_invalid_coords", lang),
                parse_mode="MarkdownV2",
                reply_markup=commuter_setup_keyboard(step, lang),
            )
            return True

        await _store_setup_location(update, context, step, location, lang)
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

        # Refuse to persist a profile whose coordinates would be unusable.
        if not (is_valid_porto_coords(setup.get("home_lat"), setup.get("home_lon"))
                and is_valid_porto_coords(setup.get("work_lat"), setup.get("work_lon"))):
            context.user_data["commuter_step"] = "home"
            await update.message.reply_text(
                tf("commuter_invalid_coords", lang),
                parse_mode="MarkdownV2",
                reply_markup=commuter_setup_keyboard("home", lang),
            )
            return True

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
