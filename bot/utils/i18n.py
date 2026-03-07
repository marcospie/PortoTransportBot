"""Simple internationalization for the bot. Supports PT and EN."""

from telegram import Update

TRANSLATIONS = {
    "pt": {
        # Start / Welcome
        "welcome": (
            "🚌🚇 *Porto Transport Bot*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "O teu assistente de transportes do Porto\\.\n\n"
            "🚌 *Autocarros* — tempos reais STCP\n"
            "🚇 *Metro* — horários e frequências\n"
            "🗺 *Rotas* — planeia o teu trajeto\n"
            "📍 *Localização* — paragens perto de ti\n\n"
            "Escolhe uma opção ou escreve o nome de uma paragem:"
        ),
        "welcome_with_favs": (
            "🚌🚇 *Porto Transport Bot*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "👋 Olá de novo\\! Os teus favoritos:\n"
        ),
        "help": (
            "ℹ️ *Ajuda*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "*Comandos:*\n"
            "  /bus — Autocarros STCP\n"
            "  /metro — Metro do Porto\n"
            "  /stop `BCM2` — Consulta rápida\n"
            "  /station `Trindade` — Estação de metro\n"
            "  /route — Planear trajeto\n"
            "  /favorites — Os teus favoritos\n"
            "  /settings — Configurações\n\n"
            "*Como usar:*\n"
            "1️⃣ Escolhe 🚌 autocarros ou 🚇 metro\n"
            "2️⃣ Pesquisa por nome ou código\n"
            "3️⃣ Consulta os horários em tempo real\n"
            "4️⃣ Adiciona aos ⭐ favoritos\\!\n\n"
            "*Dicas:*\n"
            "• Escreve o nome da paragem diretamente\n"
            "• 📍 Envia a tua localização para ver paragens perto\n"
            "• 🔄 Atualiza os horários a qualquer momento\n"
            "• Usa @nomedobot numa conversa para pesquisa rápida"
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
        # Settings
        "settings_title": (
            "⚙️ *Configurações*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "Personaliza o teu bot\\.\n"
            "Toca numa opção para alterar:"
        ),
        "settings_metro_radius": "🚇 Raio metro: {value}m",
        "settings_bus_radius": "🚌 Raio autocarros: {value}m",
        "settings_max_results": "📊 Máx. resultados: {value}",
        "settings_language": "🌐 Idioma: {value}",
        "settings_reset": "🔄 Repor predefinições",
        "settings_pick_metro_radius": "🚇 *Raio de pesquisa \\- Metro*\n\nEscolhe a distância máxima para encontrar estações de metro perto de ti:",
        "settings_pick_bus_radius": "🚌 *Raio de pesquisa \\- Autocarros*\n\nEscolhe a distância máxima para encontrar paragens perto de ti:",
        "settings_pick_max_results": "📊 *Máximo de resultados*\n\nQuantas paragens/estações mostrar na pesquisa por localização:",
        "settings_pick_language": "🌐 *Idioma*\n\nEscolhe o idioma do bot\\.\n_Automático_ usa o idioma do teu Telegram:",
        "settings_saved": "Guardado!",
        "settings_reset_done": "Configurações repostas!",
        # Errors
        "error_generic": "❌ Ocorreu um erro\\. Tenta novamente\\.",
    },
    "en": {
        # Start / Welcome
        "welcome": (
            "🚌🚇 *Porto Transport Bot*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "Your Porto public transport assistant\\.\n\n"
            "🚌 *Buses* — real\\-time STCP arrivals\n"
            "🚇 *Metro* — schedules and frequencies\n"
            "🗺 *Routes* — plan your trip\n"
            "📍 *Location* — nearby stops\n\n"
            "Pick an option or type a stop name:"
        ),
        "welcome_with_favs": (
            "🚌🚇 *Porto Transport Bot*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "👋 Welcome back\\! Your favorites:\n"
        ),
        "help": (
            "ℹ️ *Help*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "*Commands:*\n"
            "  /bus — STCP Buses\n"
            "  /metro — Porto Metro\n"
            "  /stop `BCM2` — Quick stop lookup\n"
            "  /station `Trindade` — Metro station\n"
            "  /route — Plan a route\n"
            "  /favorites — Your favorites\n"
            "  /settings — Settings\n\n"
            "*How to use:*\n"
            "1️⃣ Choose 🚌 buses or 🚇 metro\n"
            "2️⃣ Search by name or stop code\n"
            "3️⃣ See real\\-time arrivals\n"
            "4️⃣ Add to ⭐ favorites\\!\n\n"
            "*Tips:*\n"
            "• Type a stop name directly\n"
            "• 📍 Send your location for nearby stops\n"
            "• 🔄 Refresh times anytime\n"
            "• Use @botname in any chat for inline search"
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
        # Settings
        "settings_title": (
            "⚙️ *Settings*\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "Customise your bot\\.\n"
            "Tap an option to change:"
        ),
        "settings_metro_radius": "🚇 Metro radius: {value}m",
        "settings_bus_radius": "🚌 Bus radius: {value}m",
        "settings_max_results": "📊 Max results: {value}",
        "settings_language": "🌐 Language: {value}",
        "settings_reset": "🔄 Reset defaults",
        "settings_pick_metro_radius": "🚇 *Search radius \\- Metro*\n\nChoose the max distance to find metro stations near you:",
        "settings_pick_bus_radius": "🚌 *Search radius \\- Buses*\n\nChoose the max distance to find bus stops near you:",
        "settings_pick_max_results": "📊 *Maximum results*\n\nHow many stops/stations to show in location search:",
        "settings_pick_language": "🌐 *Language*\n\nChoose the bot language\\.\n_Auto_ uses your Telegram language:",
        "settings_saved": "Saved!",
        "settings_reset_done": "Settings reset!",
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
