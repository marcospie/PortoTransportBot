"""Simple internationalization for the bot. Supports PT and EN."""

from telegram import Update

TRANSLATIONS = {
    "pt": {
        # Start / Welcome
        "welcome": (
            "🚌🚇 *Porto Transport Bot*\n\n"
            "Bem\\-vindo\\! Sou o teu assistente de transportes públicos do Porto\\.\n\n"
            "Posso ajudar\\-te a consultar:\n\n"
            "🚌 *Autocarros \\(STCP\\)* \\- tempos reais de chegada\n"
            "🚇 *Metro do Porto* \\- horários e frequências\n\n"
            "Escolhe uma opção abaixo ou usa os comandos:\n\n"
            "/bus \\- Menu autocarros\n"
            "/metro \\- Menu metro\n"
            "/stop \\<código\\> \\- Consulta rápida de paragem\n"
            "/station \\<nome\\> \\- Consulta rápida de estação\n"
            "/favorites \\- Os teus favoritos"
        ),
        "welcome_with_favs": (
            "🚌🚇 *Porto Transport Bot*\n\n"
            "Olá de novo\\! Aqui estão os teus favoritos:\n"
        ),
        "help": (
            "ℹ️ *Ajuda*\n\n"
            "*Comandos disponíveis:*\n\n"
            "/start \\- Menu principal\n"
            "/bus \\- Autocarros STCP\n"
            "/metro \\- Metro do Porto\n"
            "/stop BCM2 \\- Consultar paragem por código\n"
            "/station Trindade \\- Consultar estação de metro\n"
            "/favorites \\- Gerir favoritos\n"
            "/help \\- Esta mensagem\n\n"
            "*Como usar:*\n\n"
            "1️⃣ Escolhe entre 🚌 autocarros ou 🚇 metro\n"
            "2️⃣ Pesquisa por nome ou código da paragem/estação\n"
            "3️⃣ Vê os tempos de chegada em tempo real\n"
            "4️⃣ Adiciona aos favoritos para acesso rápido\\!\n\n"
            "*Dicas:*\n"
            "• Podes enviar o nome de uma paragem diretamente\n"
            "• 📍 Envia a tua localização para ver paragens perto de ti\n"
            "• Os tempos dos autocarros são em tempo real\n"
            "• Os tempos do metro são estimados com base nas frequências\n"
            "• Usa o botão 🔄 para atualizar os dados"
        ),
        # Location / Nearby
        "nearby_title": "📍 *Transportes perto de ti* \\(raio {radius}m\\)",
        "nearby_empty": (
            "📍 Não encontrei paragens ou estações num raio de "
            "{radius}m da tua localização\\.\n\n"
            "Tenta pesquisar por nome no menu\\."
        ),
        "metro_stations": "Estações de metro",
        "bus_stops": "Paragens de autocarro",
        # Night service
        "metro_closed": (
            "🌙 *Metro encerrado*\n\n"
            "O metro funciona das 06:00 às 01:00\\.\n\n"
            "🚌 *Alternativas noturnas STCP:*\n"
            "• Linha *1M* \\- Madrugada\n"
            "• Linha *2M* \\- Madrugada\n"
            "• Linha *3M* \\- Madrugada\n\n"
            "Consulta /bus para mais informações\\."
        ),
        # Zone info
        "zone_info": "📍 Zona Andante: *{zone}*",
        # Navigation
        "back_main": "🔙 Menu principal",
        "back": "🔙 Voltar",
        # Keyboard
        "kb_nearby": "📍 Perto de mim",
        "kb_favorites": "⭐ Favoritos",
        "kb_help": "ℹ️ Ajuda",
        # Errors
        "error_generic": "❌ Ocorreu um erro\\. Tenta novamente\\.",
    },
    "en": {
        # Start / Welcome
        "welcome": (
            "🚌🚇 *Porto Transport Bot*\n\n"
            "Welcome\\! I'm your Porto public transport assistant\\.\n\n"
            "I can help you with:\n\n"
            "🚌 *Buses \\(STCP\\)* \\- real\\-time arrivals\n"
            "🚇 *Porto Metro* \\- schedules and frequencies\n\n"
            "Choose an option below or use commands:\n\n"
            "/bus \\- Bus menu\n"
            "/metro \\- Metro menu\n"
            "/stop \\<code\\> \\- Quick stop lookup\n"
            "/station \\<name\\> \\- Quick station lookup\n"
            "/favorites \\- Your favorites"
        ),
        "welcome_with_favs": (
            "🚌🚇 *Porto Transport Bot*\n\n"
            "Welcome back\\! Here are your favorites:\n"
        ),
        "help": (
            "ℹ️ *Help*\n\n"
            "*Available commands:*\n\n"
            "/start \\- Main menu\n"
            "/bus \\- STCP Buses\n"
            "/metro \\- Porto Metro\n"
            "/stop BCM2 \\- Check stop by code\n"
            "/station Trindade \\- Check metro station\n"
            "/favorites \\- Manage favorites\n"
            "/help \\- This message\n\n"
            "*How to use:*\n\n"
            "1️⃣ Choose between 🚌 buses or 🚇 metro\n"
            "2️⃣ Search by name or stop/station code\n"
            "3️⃣ See real\\-time arrival times\n"
            "4️⃣ Add to favorites for quick access\\!\n\n"
            "*Tips:*\n"
            "• You can send a stop name directly\n"
            "• 📍 Send your location to find nearby stops\n"
            "• Bus times are real\\-time\n"
            "• Metro times are estimated based on frequencies\n"
            "• Use the 🔄 button to refresh data"
        ),
        # Location / Nearby
        "nearby_title": "📍 *Transport near you* \\(radius {radius}m\\)",
        "nearby_empty": (
            "📍 No stops or stations found within "
            "{radius}m of your location\\.\n\n"
            "Try searching by name in the menu\\."
        ),
        "metro_stations": "Metro stations",
        "bus_stops": "Bus stops",
        # Night service
        "metro_closed": (
            "🌙 *Metro closed*\n\n"
            "Metro operates from 06:00 to 01:00\\.\n\n"
            "🚌 *Night bus alternatives \\(STCP\\):*\n"
            "• Line *1M* \\- Madrugada\n"
            "• Line *2M* \\- Madrugada\n"
            "• Line *3M* \\- Madrugada\n\n"
            "Check /bus for more information\\."
        ),
        # Zone info
        "zone_info": "📍 Andante Zone: *{zone}*",
        # Navigation
        "back_main": "🔙 Main menu",
        "back": "🔙 Back",
        # Keyboard
        "kb_nearby": "📍 Near me",
        "kb_favorites": "⭐ Favorites",
        "kb_help": "ℹ️ Help",
        # Errors
        "error_generic": "❌ An error occurred\\. Please try again\\.",
    },
}

# Zone code to readable name mapping
ZONE_NAMES = {
    "PRT": "Porto (Z2)",
    "MTS": "Matosinhos (Z2-Z4)",
    "VNG": "Vila Nova de Gaia (Z3-Z5)",
    "MAI": "Maia (Z3-Z6)",
    "GDM": "Gondomar (Z3-Z4)",
    "VLG": "Valongo (Z4-Z5)",
    "VCD": "Vila do Conde (Z7-Z8)",
    "PVZ": "Póvoa de Varzim (Z8-Z10)",
}


def get_lang(update: Update) -> str:
    """Detect user language from Telegram settings."""
    if update.effective_user and update.effective_user.language_code:
        lang = update.effective_user.language_code[:2].lower()
        if lang in TRANSLATIONS:
            return lang
    return "pt"


def t(key: str, lang: str = "pt") -> str:
    """Get translated string."""
    translations = TRANSLATIONS.get(lang, TRANSLATIONS["pt"])
    return translations.get(key, TRANSLATIONS["pt"].get(key, key))


def get_zone_display(zone_code: str) -> str:
    """Get displayable zone name from zone code."""
    return ZONE_NAMES.get(zone_code, zone_code)
