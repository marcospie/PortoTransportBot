"""Main entry point for the Porto Transport Bot."""

import logging

from telegram import BotCommand, BotCommandScopeAllPrivateChats, MenuButtonCommands, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    InlineQueryHandler,
    MessageHandler,
    filters,
)

from bot.config import TELEGRAM_BOT_TOKEN
from bot.database import init_db, close_db
from bot.handlers import accessibility, alerts, bus, commuter, events, favorites, inline, location, metro, metrobus, routes, settings, start, tourist, trains, trip_planner, weather, zones
from bot.services.metro import download_gtfs
from bot.services.stcp import download_stcp_gtfs
from bot.utils.i18n import get_lang, t

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def unknown_callback(update: Update, context) -> None:
    """Catch-all for unmatched callback queries (stale buttons, etc.)."""
    lang = get_lang(update)
    msg = "Este botão já não é válido. Use /start para recomeçar." if lang == "pt" else "This button is no longer valid. Use /start to restart."
    await update.callback_query.answer(msg)
    try:
        await update.callback_query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass


async def handle_text(update: Update, context) -> None:
    """Route free-text messages to the appropriate handler."""
    text = update.message.text.strip()
    lang = get_lang(update)

    # Handle persistent reply keyboard buttons (match both PT and EN labels)
    if text in ("⭐ Favoritos", "⭐ Favorites"):
        await favorites.favorites_command(update, context)
        return
    if text in ("ℹ️ Ajuda", "ℹ️ Help"):
        await start.help_command(update, context)
        return
    if text in ("📍 Paragens perto de mim", "📍 Stops near me", "📍 Perto de mim", "📍 Near me"):
        # Location button text - ignore, location handler handles actual location
        return

    # Check if any handler is awaiting input
    if await commuter.handle_commuter_text_input(update, context):
        return
    if await routes.handle_route_text_input(update, context):
        return
    if await bus.handle_bus_text_input(update, context):
        return
    if await metro.handle_metro_text_input(update, context):
        return
    if await trains.handle_train_text_input(update, context):
        return
    if await zones.handle_zones_text_input(update, context):
        return
    if await accessibility.handle_accessibility_text_input(update, context):
        return

    # If it looks like a stop code (short, uppercase, with numbers)
    if len(text) <= 6 and any(c.isdigit() for c in text):
        from bot.services import stcp
        from bot.utils.formatting import format_bus_arrivals
        from bot.keyboards.inline import bus_stop_actions_keyboard
        from bot.database import is_favorite as _is_favorite

        stop_id = text.upper()
        data = await stcp.get_stop_real_time(stop_id)
        if data["arrivals"] or data["stop_name"] != stop_id:
            user_id = update.effective_user.id
            is_fav = await _is_favorite(user_id, "bus", stop_id)
            msg = format_bus_arrivals(stop_id, data["stop_name"], data["arrivals"])
            await update.message.reply_text(
                msg,
                parse_mode="MarkdownV2",
                reply_markup=bus_stop_actions_keyboard(stop_id, is_fav=is_fav, lang=lang),
            )
            return

    # Try as metro station search
    stations = metro.metro.search_stations(text)
    if stations:
        from bot.keyboards.inline import metro_station_results_keyboard
        from bot.utils.formatting import escape_md

        if len(stations) == 1:
            # Direct match - show departures
            station = stations[0]
            departures = metro.metro.get_next_departures(station["name"])
            lines_info = []
            for l in station["lines"]:
                lines_info.append(f"{l['emoji']} {l['name']}")
            line_info_str = " \\| ".join(escape_md(li) for li in lines_info)

            from bot.utils.formatting import format_metro_schedule
            from bot.keyboards.inline import metro_station_actions_keyboard
            from bot.database import is_favorite as _is_fav

            msg = format_metro_schedule(station["name"], line_info_str, departures)
            if departures and departures[0].get("estimated"):
                msg += f"\n\n{t('metro_estimated_warning', lang)}"
            user_id = update.effective_user.id
            is_fav = await _is_fav(user_id, "metro", station["name"])
            await update.message.reply_text(
                msg,
                parse_mode="MarkdownV2",
                reply_markup=metro_station_actions_keyboard(station["name"], is_fav=is_fav, lang=lang),
            )
            return

        await update.message.reply_text(
            t("metro_results_for", lang).format(query=escape_md(text)),
            parse_mode="MarkdownV2",
            reply_markup=metro_station_results_keyboard(stations, lang=lang),
        )
        return

    # Try as bus stop search
    from bot.services import stcp
    stops = await stcp.search_stops(text)
    if stops:
        from bot.keyboards.inline import bus_stop_results_keyboard
        from bot.utils.formatting import escape_md

        await update.message.reply_text(
            t("results_for", lang).format(query=escape_md(text)),
            parse_mode="MarkdownV2",
            reply_markup=bus_stop_results_keyboard(stops, lang=lang),
        )
        return

    # Nothing found
    from bot.keyboards.inline import main_menu_keyboard
    from bot.utils.formatting import escape_md

    await update.message.reply_text(
        t("no_results", lang).format(query=escape_md(text)),
        parse_mode="MarkdownV2",
        reply_markup=main_menu_keyboard(lang),
    )


async def post_init(application: Application) -> None:
    """Run after bot initialization - set up DB, register commands, download GTFS."""
    await init_db()

    # Register bot commands for autocomplete (PT)
    # Keep descriptions ≤22 chars for iOS compatibility
    pt_commands = [
        BotCommand("start", "Menu principal"),
        BotCommand("bus", "Autocarros STCP"),
        BotCommand("metro", "Metro do Porto"),
        BotCommand("stop", "Paragem por código"),
        BotCommand("station", "Estação de metro"),
        BotCommand("route", "Planear trajeto"),
        BotCommand("favorites", "Os teus favoritos"),
        BotCommand("fav", "Favorito rápido"),
        BotCommand("settings", "Configurações"),
        BotCommand("metrobus", "MetroBus BRT"),
        BotCommand("comboios", "Comboios CP"),
        BotCommand("estacao", "Estacao CP"),
        BotCommand("tourist", "Guia turístico"),
        BotCommand("commuter", "Perfil commuter"),
        BotCommand("zonas", "Calculador zonas"),
        BotCommand("alertas", "Alertas de serviço"),
        BotCommand("acessibilidade", "Acessibilidade"),
        BotCommand("meteo", "Meteorologia"),
        BotCommand("eventos", "Eventos no Porto"),
        BotCommand("help", "Ajuda"),
    ]
    en_commands = [
        BotCommand("start", "Main menu"),
        BotCommand("bus", "STCP Buses"),
        BotCommand("metro", "Porto Metro"),
        BotCommand("stop", "Stop by code"),
        BotCommand("station", "Metro station"),
        BotCommand("route", "Plan a route"),
        BotCommand("favorites", "Your favorites"),
        BotCommand("fav", "Quick favorite"),
        BotCommand("settings", "Settings"),
        BotCommand("metrobus", "MetroBus BRT"),
        BotCommand("comboios", "CP Trains"),
        BotCommand("estacao", "CP Station"),
        BotCommand("tourist", "Tourist guide"),
        BotCommand("commuter", "Commuter profile"),
        BotCommand("zonas", "Zone calculator"),
        BotCommand("alertas", "Service alerts"),
        BotCommand("acessibilidade", "Accessibility"),
        BotCommand("meteo", "Weather"),
        BotCommand("eventos", "Events in Porto"),
        BotCommand("help", "Help"),
    ]

    bot = application.bot
    try:
        # Set global default commands (PT) — this is what iOS reads
        await bot.set_my_commands(pt_commands)
        logger.info("Global commands set (%d commands)", len(pt_commands))

        # Also set language-specific commands for clients that support it
        await bot.set_my_commands(en_commands, language_code="en")
        await bot.set_my_commands(pt_commands, language_code="pt")
        logger.info("Language-specific commands set (PT + EN)")

        # Set same for private chats scope (some clients prefer this)
        scope = BotCommandScopeAllPrivateChats()
        await bot.set_my_commands(pt_commands, scope=scope)
        await bot.set_my_commands(en_commands, scope=scope, language_code="en")
        await bot.set_my_commands(pt_commands, scope=scope, language_code="pt")
        logger.info("Private chat scope commands set")

        # Set the menu button to show commands list
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())

        # Verify commands were registered
        registered = await bot.get_my_commands()
        logger.info("Verified %d commands registered: %s",
                     len(registered), ", ".join(f"/{c.command}" for c in registered))

        # Set bot description (shown before user starts the bot)
        await bot.set_my_description(
            "Consulta autocarros STCP e Metro do Porto em tempo real. "
            "Horários, paragens perto de ti, favoritos e planeamento de rotas.",
            language_code="pt",
        )
        await bot.set_my_description(
            "Real-time Porto public transport info. "
            "STCP buses, Metro schedules, nearby stops, favorites and route planning.",
            language_code="en",
        )

        # Set short description (shown in bot profile)
        await bot.set_my_short_description(
            "Transportes do Porto em tempo real - STCP e Metro",
            language_code="pt",
        )
        await bot.set_my_short_description(
            "Porto public transport in real time - STCP & Metro",
            language_code="en",
        )

        logger.info("Bot commands and descriptions registered successfully")
    except Exception:
        logger.exception("Failed to register bot commands")

    logger.info("Attempting to download Metro GTFS data...")
    success = await download_gtfs()
    if success:
        logger.info("Metro GTFS data loaded successfully")
    else:
        logger.warning("Could not load GTFS data - using frequency estimates")

    logger.info("Attempting to download STCP GTFS data...")
    stcp_success = await download_stcp_gtfs()
    if stcp_success:
        logger.info("STCP GTFS data loaded - nearby bus stops available")
    else:
        logger.warning("Could not load STCP GTFS data - nearby bus search limited")


async def post_shutdown(application: Application) -> None:
    """Clean up resources on shutdown."""
    await close_db()


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not set.")
        print("Copy .env.example to .env and add your bot token.")
        return

    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Command handlers
    app.add_handler(CommandHandler("start", start.start_command))
    app.add_handler(CommandHandler("help", start.help_command))
    app.add_handler(CommandHandler("bus", bus.bus_command))
    app.add_handler(CommandHandler("metro", metro.metro_command))
    app.add_handler(CommandHandler("stop", bus.stop_command))
    app.add_handler(CommandHandler("station", metro.station_command))
    app.add_handler(CommandHandler("favorites", favorites.favorites_command))
    app.add_handler(CommandHandler("fav", favorites.fav_quick_command))
    app.add_handler(CommandHandler("route", routes.route_command))
    app.add_handler(CommandHandler("settings", settings.settings_command))
    app.add_handler(CommandHandler("alertas", alerts.alertas_command))
    app.add_handler(CommandHandler("tourist", tourist.tourist_command))
    app.add_handler(CommandHandler("metrobus", metrobus.metrobus_command))
    app.add_handler(CommandHandler("commuter", commuter.commuter_command))
    app.add_handler(CommandHandler("comboios", trains.trains_command))
    app.add_handler(CommandHandler("estacao", trains.estacao_command))
    app.add_handler(CommandHandler("zonas", zones.zones_command))
    app.add_handler(CommandHandler("acessibilidade", accessibility.accessibility_command))
    app.add_handler(CommandHandler("meteo", weather.weather_command))
    app.add_handler(CommandHandler("eventos", events.events_command))

    # Callback query handlers - menu navigation
    app.add_handler(CallbackQueryHandler(start.main_menu_callback, pattern=r"^menu:main$"))
    app.add_handler(CallbackQueryHandler(start.help_callback, pattern=r"^menu:help$"))

    # Bus callbacks
    app.add_handler(CallbackQueryHandler(bus.bus_menu_callback, pattern=r"^menu:bus$"))
    app.add_handler(CallbackQueryHandler(bus.bus_find_callback, pattern=r"^bus:find$"))
    # Legacy aliases for backwards compatibility
    app.add_handler(CallbackQueryHandler(bus.bus_search_callback, pattern=r"^bus:search$"))
    app.add_handler(CallbackQueryHandler(bus.bus_code_callback, pattern=r"^bus:code$"))
    app.add_handler(CallbackQueryHandler(bus.bus_routes_callback, pattern=r"^bus:routes$"))
    app.add_handler(CallbackQueryHandler(bus.bus_routes_page_callback, pattern=r"^bus:routes:page:\d+$"))
    app.add_handler(CallbackQueryHandler(bus.bus_stop_callback, pattern=r"^bus:stop:.+$"))
    app.add_handler(CallbackQueryHandler(bus.bus_stop_info_callback, pattern=r"^bus:info:.+$"))
    app.add_handler(CallbackQueryHandler(bus.bus_location_callback, pattern=r"^bus:loc:.+$"))
    app.add_handler(CallbackQueryHandler(bus.bus_route_callback, pattern=r"^bus:route:.+$"))

    # Metro callbacks
    app.add_handler(CallbackQueryHandler(metro.metro_menu_callback, pattern=r"^menu:metro$"))
    app.add_handler(CallbackQueryHandler(metro.metro_search_callback, pattern=r"^metro:search$"))
    app.add_handler(CallbackQueryHandler(metro.metro_lines_callback, pattern=r"^metro:lines$"))
    app.add_handler(CallbackQueryHandler(metro.metro_freq_callback, pattern=r"^metro:freq$"))
    app.add_handler(CallbackQueryHandler(metro.metro_line_callback, pattern=r"^metro:line:[A-F]$"))
    app.add_handler(CallbackQueryHandler(metro.metro_line_freq_callback, pattern=r"^metro:line_freq:[A-F]$"))
    app.add_handler(CallbackQueryHandler(metro.metro_location_callback, pattern=r"^metro:loc:.+$"))
    app.add_handler(CallbackQueryHandler(metro.metro_station_callback, pattern=r"^metro:station:.+$"))
    app.add_handler(CallbackQueryHandler(metro.metro_station_lines_callback, pattern=r"^metro:station_lines:.+$"))

    # MetroBus callbacks
    app.add_handler(CallbackQueryHandler(metrobus.metrobus_menu_callback, pattern=r"^menu:metrobus$"))
    app.add_handler(CallbackQueryHandler(metrobus.metrobus_search_callback, pattern=r"^metrobus:search$"))
    app.add_handler(CallbackQueryHandler(metrobus.metrobus_lines_callback, pattern=r"^metrobus:lines$"))
    app.add_handler(CallbackQueryHandler(metrobus.metrobus_freq_callback, pattern=r"^metrobus:freq$"))
    app.add_handler(CallbackQueryHandler(metrobus.metrobus_line_callback, pattern=r"^metrobus:line:\d+$"))
    app.add_handler(CallbackQueryHandler(metrobus.metrobus_location_callback, pattern=r"^metrobus:loc:.+$"))
    app.add_handler(CallbackQueryHandler(metrobus.metrobus_stop_callback, pattern=r"^metrobus:stop:.+$"))
    app.add_handler(CallbackQueryHandler(metrobus.metrobus_stop_lines_callback, pattern=r"^metrobus:stop_lines:.+$"))

    # Train (CP) callbacks
    app.add_handler(CallbackQueryHandler(trains.trains_menu_callback, pattern=r"^menu:trains$"))
    app.add_handler(CallbackQueryHandler(trains.train_search_callback, pattern=r"^train:search$"))
    app.add_handler(CallbackQueryHandler(trains.train_lines_callback, pattern=r"^train:lines$"))
    app.add_handler(CallbackQueryHandler(trains.train_line_callback, pattern=r"^train:line:.+$"))
    app.add_handler(CallbackQueryHandler(trains.train_station_callback, pattern=r"^train:station:.+$"))
    app.add_handler(CallbackQueryHandler(trains.train_station_lines_callback, pattern=r"^train:station_lines:.+$"))
    app.add_handler(CallbackQueryHandler(trains.train_location_callback, pattern=r"^train:loc:.+$"))

    # Tourist callbacks
    app.add_handler(CallbackQueryHandler(tourist.tourist_menu_callback, pattern=r"^tourist:menu$"))
    app.add_handler(CallbackQueryHandler(tourist.tourist_category_callback, pattern=r"^tourist:cat:.+$"))
    app.add_handler(CallbackQueryHandler(tourist.tourist_destination_callback, pattern=r"^tourist:dest:.+$"))
    app.add_handler(CallbackQueryHandler(tourist.tourist_tickets_callback, pattern=r"^tourist:tickets$"))

    # Events callbacks
    app.add_handler(CallbackQueryHandler(events.events_menu_callback, pattern=r"^menu:events$"))
    app.add_handler(CallbackQueryHandler(events.events_categories_callback, pattern=r"^events:categories$"))
    app.add_handler(CallbackQueryHandler(events.events_category_callback, pattern=r"^events:cat:.+$"))
    app.add_handler(CallbackQueryHandler(events.events_detail_callback, pattern=r"^events:detail:\d+$"))

    # Alerts callbacks
    app.add_handler(CallbackQueryHandler(alerts.alerts_menu_callback, pattern=r"^menu:alerts$"))
    app.add_handler(CallbackQueryHandler(alerts.alerts_filter_callback, pattern=r"^alerts:filter:.+$"))

    # Weather callbacks
    app.add_handler(CallbackQueryHandler(weather.weather_menu_callback, pattern=r"^menu:weather$"))

    # Commuter callbacks
    app.add_handler(CallbackQueryHandler(commuter.commuter_menu_callback, pattern=r"^menu:commuter$"))
    app.add_handler(CallbackQueryHandler(commuter.commuter_setup_callback, pattern=r"^commuter:setup$"))
    app.add_handler(CallbackQueryHandler(commuter.commuter_cancel_callback, pattern=r"^commuter:cancel$"))
    app.add_handler(CallbackQueryHandler(commuter.commuter_delete_callback, pattern=r"^commuter:delete$"))
    app.add_handler(CallbackQueryHandler(commuter.commuter_go_work_callback, pattern=r"^commuter:go_work$"))
    app.add_handler(CallbackQueryHandler(commuter.commuter_go_home_callback, pattern=r"^commuter:go_home$"))
    app.add_handler(CallbackQueryHandler(commuter.commuter_my_times_callback, pattern=r"^commuter:my_times$"))
    app.add_handler(CallbackQueryHandler(commuter.commuter_mode_callback, pattern=r"^commuter:mode:.+$"))

    # Zone calculator callbacks
    app.add_handler(CallbackQueryHandler(zones.zones_menu_callback, pattern=r"^menu:zones$"))
    app.add_handler(CallbackQueryHandler(zones.zones_calculate_callback, pattern=r"^zones:calculate$"))
    app.add_handler(CallbackQueryHandler(zones.zones_map_callback, pattern=r"^zones:map$"))
    app.add_handler(CallbackQueryHandler(zones.zones_zone_callback, pattern=r"^zones:zone:.+$"))

    # Accessibility callbacks
    app.add_handler(CallbackQueryHandler(accessibility.accessibility_menu_callback, pattern=r"^menu:accessibility$"))
    app.add_handler(CallbackQueryHandler(accessibility.accessibility_station_callback, pattern=r"^access:station:.+$"))
    app.add_handler(CallbackQueryHandler(accessibility.accessibility_search_callback, pattern=r"^access:search$"))
    app.add_handler(CallbackQueryHandler(accessibility.accessibility_elevators_callback, pattern=r"^access:elevators$"))

    # Nearby refresh callback
    app.add_handler(CallbackQueryHandler(location.nearby_refresh_callback, pattern=r"^nearby:refresh$"))

    # Route planning callbacks
    app.add_handler(CallbackQueryHandler(routes.route_plan_callback, pattern=r"^plan:route$"))
    app.add_handler(CallbackQueryHandler(routes.route_plan_callback, pattern=r"^route:plan$"))
    app.add_handler(CallbackQueryHandler(routes.trip_detail_callback, pattern=r"^trip:detail:\d+$"))

    # Favorites callbacks
    app.add_handler(CallbackQueryHandler(favorites.favorites_callback, pattern=r"^menu:favorites$"))
    app.add_handler(CallbackQueryHandler(favorites.add_favorite_callback, pattern=r"^fav:add:.+$"))
    app.add_handler(CallbackQueryHandler(favorites.remove_favorite_callback, pattern=r"^fav:remove:.+$"))

    # Settings callbacks
    app.add_handler(CallbackQueryHandler(settings.settings_menu_callback, pattern=r"^menu:settings$"))
    app.add_handler(CallbackQueryHandler(settings.settings_option_callback, pattern=r"^settings:(metro_radius|bus_radius|max_results|language)$"))
    app.add_handler(CallbackQueryHandler(settings.settings_set_callback, pattern=r"^settings:set:.+$"))
    app.add_handler(CallbackQueryHandler(settings.settings_reset_callback, pattern=r"^settings:reset$"))

    # No-op callback for informational buttons (e.g. page counters)
    app.add_handler(CallbackQueryHandler(
        lambda update, _: update.callback_query.answer(), pattern=r"^noop$"
    ))

    # Onboarding location shortcut
    async def onboard_location_callback(update: Update, context):
        query = update.callback_query
        await query.answer()
        lang = get_lang(update)
        msg = ("📍 Carrega no botão *Perto de mim* no teclado abaixo para partilhar a tua localização\\!"
               if lang == "pt" else
               "📍 Tap the *Near me* button on the keyboard below to share your location\\!")
        await query.edit_message_text(
            msg,
            parse_mode="MarkdownV2",
        )

    app.add_handler(CallbackQueryHandler(onboard_location_callback, pattern=r"^onboard:location$"))

    # Inline query handler (for @BotName queries in any chat)
    app.add_handler(InlineQueryHandler(inline.inline_query_handler))

    # Location handler (user sends their location)
    app.add_handler(MessageHandler(filters.LOCATION, location.location_handler))

    # Text message handler (for search inputs and free text)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Catch-all for unmatched callback queries (stale buttons, etc.)
    app.add_handler(CallbackQueryHandler(unknown_callback))

    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
