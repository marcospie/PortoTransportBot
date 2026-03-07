"""Main entry point for the Porto Transport Bot."""

import logging

from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from bot.config import TELEGRAM_BOT_TOKEN
from bot.handlers import bus, favorites, location, metro, start
from bot.services.metro import download_gtfs

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def handle_text(update: Update, context) -> None:
    """Route free-text messages to the appropriate handler."""
    # Check if any handler is awaiting input
    if await bus.handle_bus_text_input(update, context):
        return
    if await metro.handle_metro_text_input(update, context):
        return

    # Default: try to interpret as stop code or station name
    text = update.message.text.strip()

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
    """Run after bot initialization - download GTFS data."""
    logger.info("Attempting to download Metro GTFS data...")
    success = await download_gtfs()
    if success:
        logger.info("Metro GTFS data loaded successfully")
    else:
        logger.warning("Could not load GTFS data - using frequency estimates")


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not set.")
        print("Copy .env.example to .env and add your bot token.")
        return

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    # Command handlers
    app.add_handler(CommandHandler("start", start.start_command))
    app.add_handler(CommandHandler("help", start.help_command))
    app.add_handler(CommandHandler("bus", bus.bus_command))
    app.add_handler(CommandHandler("metro", metro.metro_command))
    app.add_handler(CommandHandler("stop", bus.stop_command))
    app.add_handler(CommandHandler("station", metro.station_command))
    app.add_handler(CommandHandler("favorites", favorites.favorites_command))

    # Callback query handlers - menu navigation
    app.add_handler(CallbackQueryHandler(start.main_menu_callback, pattern=r"^menu:main$"))
    app.add_handler(CallbackQueryHandler(start.help_callback, pattern=r"^menu:help$"))

    # Bus callbacks
    app.add_handler(CallbackQueryHandler(bus.bus_menu_callback, pattern=r"^menu:bus$"))
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

    # Favorites callbacks
    app.add_handler(CallbackQueryHandler(favorites.favorites_callback, pattern=r"^menu:favorites$"))
    app.add_handler(CallbackQueryHandler(favorites.add_favorite_callback, pattern=r"^fav:add:.+$"))
    app.add_handler(CallbackQueryHandler(favorites.remove_favorite_callback, pattern=r"^fav:remove:.+$"))

    # Location handler (user sends their location)
    app.add_handler(MessageHandler(filters.LOCATION, location.location_handler))

    # Text message handler (for search inputs and free text)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Bot starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
