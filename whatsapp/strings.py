"""Localisation for the WhatsApp bot (PT / EN).

Strings are resolved in this order:

1. :data:`WA_STRINGS` - WhatsApp-specific copy that has no Telegram
   equivalent (WhatsApp has no slash commands, no reply keyboards, ...).
2. ``bot.utils.i18n.t`` - the shared PT/EN table used by the Telegram bot.
   This is where the bulk of the copy comes from, so the two channels stay in
   sync and a new translation only has to be written once.

Whatever the source, the result is passed through
:func:`whatsapp.formatting.from_markdown_v2` because the shared table is
MarkdownV2-escaped for Telegram and WhatsApp must never see those backslashes.

``bot/utils/i18n.py`` is owned by the Telegram side, so this module treats it as
a read-only dependency and degrades gracefully if a key disappears.
"""

from __future__ import annotations

import logging

from whatsapp.formatting import from_markdown_v2

logger = logging.getLogger(__name__)

__all__ = ["SUPPORTED_LANGS", "DEFAULT_LANG", "WA_STRINGS", "wt", "lang_from_phone"]

SUPPORTED_LANGS = ("pt", "en")
DEFAULT_LANG = "pt"

# Portugal country calling code - a +351 number gets Portuguese by default.
_PT_DIALLING_CODES = ("351",)


WA_STRINGS: dict[str, dict[str, str]] = {
    "pt": {
        "wa_menu_body": (
            "🚍 *Porto Transport Bot*\n\n"
            "Bem-vindo! Escolhe uma opção ou envia diretamente o nome/código "
            "de uma paragem ou estação."
        ),
        "wa_menu_button": "Ver opções",
        "wa_menu_section": "O que queres fazer?",
        "wa_prompt_bus": (
            "🔍 Envia o nome ou o código da paragem.\n\n"
            "Exemplo: Bolhão, BCM2"
        ),
        "wa_prompt_metro": (
            "🔍 Envia o nome da estação de metro.\n\n"
            "Exemplo: Trindade, Bolhão"
        ),
        "wa_help": (
            "ℹ️ *Como usar o Porto Transport Bot*\n\n"
            "Envia uma destas opções:\n\n"
            "🔍 *Nome de paragem* → pesquisa paragens STCP\n"
            "   Exemplo: Bolhão, Casa da Música\n\n"
            "🔢 *Código de paragem* → horários em tempo real\n"
            "   Exemplo: BCM2, TRD1\n\n"
            "🚇 *Nome de estação* → horários do metro\n"
            "   Exemplo: Trindade, Aliados\n\n"
            "📍 *Localização* → transportes perto de ti\n"
            "   Partilha a tua localização\n\n"
            "⭐ *favoritos* → as tuas paragens guardadas\n"
            "🗺 *viagem* → planear um trajeto\n"
            "🌐 *idioma* → mudar de idioma\n"
            "📝 *menu* → ver o menu principal\n\n"
            "💡 Dica: basta escrever o nome da paragem ou estação para ver "
            "os horários!"
        ),
        "wa_kb_language": "🌐 Idioma",
        "wa_lang_picker": "🌐 *Idioma*\n\nEscolhe o idioma do bot:",
        "wa_lang_set": "🌐 Idioma alterado para *Português*.",
        "wa_cancelled": "❌ Operação cancelada.",
        "wa_bus_no_arrivals": "Sem autocarros previstos na próxima hora.",
        "wa_metro_no_info": "Sem informação de horários.",
        "wa_metro_closed": "🌙 Serviço encerrado.",
        "wa_metro_hours": "Funcionamento: {hours}",
        "wa_updated_at": "_Atualizado às {time}_",
        "wa_nearby_metro": "🚇 *Metro:*",
        "wa_nearby_bus": "🚌 *Autocarros:*",
        "wa_stop_section": "Paragens encontradas",
        "wa_stop_list_button": "Ver paragens",
        "wa_station_section": "Estações encontradas",
        "wa_station_list_button": "Ver estações",
        "wa_favs_section": "Os teus favoritos",
        "wa_favs_list_button": "Ver favoritos",
        "wa_fav_desc_stop": "Paragem {id}",
        "wa_fav_desc_station": "Estação de metro",
        "wa_trip_prompt_origin": (
            "🗺 *Planear viagem*\n\n"
            "Envia o nome da paragem ou estação de *origem*.\n"
            "Exemplo: Bolhão, Trindade, Campanhã"
        ),
        "wa_trip_prompt_dest": "Agora envia o nome da paragem ou estação de *destino*.",
        "wa_stop_desc": "Paragem {id}",
    },
    "en": {
        "wa_menu_body": (
            "🚍 *Porto Transport Bot*\n\n"
            "Welcome! Pick an option or just send the name/code of a stop or "
            "station."
        ),
        "wa_menu_button": "See options",
        "wa_menu_section": "What do you want to do?",
        "wa_prompt_bus": (
            "🔍 Send the stop name or code.\n\n"
            "Example: Bolhão, BCM2"
        ),
        "wa_prompt_metro": (
            "🔍 Send the metro station name.\n\n"
            "Example: Trindade, Bolhão"
        ),
        "wa_help": (
            "ℹ️ *How to use the Porto Transport Bot*\n\n"
            "Send any of these:\n\n"
            "🔍 *Stop name* → search STCP stops\n"
            "   Example: Bolhão, Casa da Música\n\n"
            "🔢 *Stop code* → real-time arrivals\n"
            "   Example: BCM2, TRD1\n\n"
            "🚇 *Station name* → metro departures\n"
            "   Example: Trindade, Aliados\n\n"
            "📍 *Location* → transport near you\n"
            "   Share your location\n\n"
            "⭐ *favorites* → your saved stops\n"
            "🗺 *trip* → plan a journey\n"
            "🌐 *language* → change language\n"
            "📝 *menu* → show the main menu\n\n"
            "💡 Tip: just type a stop or station name to see the times!"
        ),
        "wa_kb_language": "🌐 Language",
        "wa_lang_picker": "🌐 *Language*\n\nChoose the bot language:",
        "wa_lang_set": "🌐 Language changed to *English*.",
        "wa_cancelled": "❌ Cancelled.",
        "wa_bus_no_arrivals": "No buses expected within the next hour.",
        "wa_metro_no_info": "No schedule information available.",
        "wa_metro_closed": "🌙 Service closed.",
        "wa_metro_hours": "Operating hours: {hours}",
        "wa_updated_at": "_Updated at {time}_",
        "wa_nearby_metro": "🚇 *Metro:*",
        "wa_nearby_bus": "🚌 *Buses:*",
        "wa_stop_section": "Stops found",
        "wa_stop_list_button": "See stops",
        "wa_station_section": "Stations found",
        "wa_station_list_button": "See stations",
        "wa_favs_section": "Your favorites",
        "wa_favs_list_button": "See favorites",
        "wa_fav_desc_stop": "Stop {id}",
        "wa_fav_desc_station": "Metro station",
        "wa_trip_prompt_origin": (
            "🗺 *Plan a trip*\n\n"
            "Send the name of the *origin* stop or station.\n"
            "Example: Bolhão, Trindade, Campanhã"
        ),
        "wa_trip_prompt_dest": "Now send the name of the *destination* stop or station.",
        "wa_stop_desc": "Stop {id}",
    },
}


def normalise_lang(lang: str | None) -> str:
    """Return a supported language code for *lang* (falls back to PT)."""
    if not lang:
        return DEFAULT_LANG
    code = str(lang)[:2].lower()
    return code if code in SUPPORTED_LANGS else DEFAULT_LANG


def lang_from_phone(phone: str) -> str:
    """Guess a language from a WhatsApp phone number's country code.

    Meta's inbound message payload carries no locale field, so the dialling
    code is the only signal available: Portuguese numbers get PT, everyone else
    gets EN (and any user can override it with the ``idioma``/``language``
    command).
    """
    digits = "".join(c for c in (phone or "") if c.isdigit())
    if not digits:
        return DEFAULT_LANG
    if digits.startswith(_PT_DIALLING_CODES):
        return "pt"
    return "en"


def _raw(key: str, lang: str) -> str:
    """Look the raw (still MarkdownV2-escaped) template up."""
    wa_lang = WA_STRINGS.get(lang) or {}
    if key in wa_lang:
        return wa_lang[key]
    wa_default = WA_STRINGS[DEFAULT_LANG]
    if key in wa_default:
        return wa_default[key]

    # Fall back to the shared Telegram translation table.
    try:
        from bot.utils.i18n import t as _t
        value = _t(key, lang)
    except Exception:  # pragma: no cover - defensive: i18n is another owner's file
        logger.exception("Could not read shared i18n table for key %r", key)
        return key
    if value == key:
        logger.warning("Missing translation for key %r (lang=%s)", key, lang)
    return value


def wt(key: str, lang: str = DEFAULT_LANG, **kwargs) -> str:
    """Translate *key* into WhatsApp-ready text.

    Looks the key up in :data:`WA_STRINGS`, then in the shared Telegram table,
    strips MarkdownV2 escaping and finally applies ``str.format(**kwargs)``.
    """
    lang = normalise_lang(lang)
    text = from_markdown_v2(_raw(key, lang))
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            logger.warning("Could not format translation %r with %r", key, sorted(kwargs))
    return text
