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
from bot.handlers import bus, favorites, inline, location, metro, routes, settings, start
from bot.services.metro import download_gtfs
from bot.services.stcp import download_stcp_gtfs

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def unknown_callback(update: Update, context) -> None:
    """Catch-all for unmatched callback queries (stale buttons, etc.)."""
    await update.callback_query.answer(
        "Este botão já não é válido. Use /start para recomeçar."
    )
    try:
        await update.callback_query.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass


async def handle_text(update: Update, context) -> None:
    """Route free-text messages to the appropriate handler."""
    text = update.message.text.strip()

    # Handle persistent reply keyboard buttons
    if text in ("⭐ Favoritos", "⭐ Favorites"):
        await favorites.favorites_command(update, context)
        return
    if text in ("ℹ️ Ajuda", "ℹ️ Help"):
        await start.help_command(update, context)
        return

    # Check if any handler is awaiting input
    if await routes.handle_route_text_input(update, context):
        return
    if await bus.handle_bus_text_input(update, context):
        return
    if await metro.handle_metro_text_input(update, context):
        return

    # If it looks like a stop code (short, uppercase, with numbers)
    if len(text) <= 6 and any(c.isdigit() for c in text):
        from bot.services import stcp
        from bot.utils.formatting import format_bus_arrivals
        from bot.keyboards.inline import bus_stop_actions_keyboard

        stop_id = text.upper()
        data = await stcp.get_stop_real_time(stop_id)
        if data["arrivals"] or data["stop_name"] != stop_id:
            msg = format_bus_arrivals(stop_id, data["stop_name"], data["arrivals"])
            await update.message.reply_text(
                msg,
                parse_mode="MarkdownV2",
                reply_markup=bus_stop_actions_keyboard(stop_id),
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

            msg = format_metro_schedule(station["name"], line_info_str, departures)
            if departures and departures[0].get("estimated"):
                msg += "\n\n_⚠️ Tempos estimados com base nas frequências_"
            await update.message.reply_text(
                msg,
                parse_mode="MarkdownV2",
                reply_markup=metro_station_actions_keyboard(station["name"]),
            )
            return

        await update.message.reply_text(
            f"🔍 Resultados para *{escape_md(text)}*:",
            parse_mode="MarkdownV2",
            reply_markup=metro_station_results_keyboard(stations),
        )
        return

    # Try as bus stop search
    from bot.services import stcp
    stops = await stcp.search_stops(text)
    if stops:
        from bot.keyboards.inline import bus_stop_results_keyboard
        from bot.utils.formatting import escape_md

        await update.message.reply_text(
            f"🔍 Resultados para *{escape_md(text)}*:",
            parse_mode="MarkdownV2",
            reply_markup=bus_stop_results_keyboard(stops),
        )
        return

    # Nothing found
    from bot.keyboards.inline import main_menu_keyboard
    from bot.utils.formatting import escape_md

    await update.message.reply_text(
        f"🤔 Não encontrei resultados para *{escape_md(text)}*\\.\n\n"
        "Tenta pesquisar por:\n"
        "• Nome de uma paragem STCP\n"
        "• Código de paragem \\(ex: BCM2\\)\n"
        "• Nome de estação de metro\n\n"
        "Ou usa o menu abaixo:",
        parse_mode="MarkdownV2",
        reply_markup=main_menu_keyboard(),
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

    # Route planning callbacks
    app.add_handler(CallbackQueryHandler(routes.route_plan_callback, pattern=r"^plan:route$"))
    app.add_handler(CallbackQueryHandler(routes.route_plan_callback, pattern=r"^route:plan$"))

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
        await query.edit_message_text(
            "📍 Carrega no botão *Perto de mim* no teclado abaixo para partilhar a tua localização\\!",
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
