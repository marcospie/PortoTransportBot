"""Event data for Porto — FC Porto matches, festivals, concerts, culture."""

from dataclasses import dataclass


@dataclass
class Event:
    name_pt: str
    name_en: str
    venue_pt: str
    venue_en: str
    date_info_pt: str
    date_info_en: str
    nearest_station: str
    transport_tip_pt: str
    transport_tip_en: str
    category: str  # "football", "festival", "music", "culture"
    emoji: str


EVENTS: list[Event] = [
    Event(
        name_pt="FC Porto — Jogos em Casa",
        name_en="FC Porto — Home Matches",
        venue_pt="Estádio do Dragão",
        venue_en="Estádio do Dragão",
        date_info_pt="Jogos em casa — consultar calendário",
        date_info_en="Home matches — check calendar",
        nearest_station="Estádio do Dragão",
        transport_tip_pt="Metro até Estádio do Dragão (Linhas A/B/E). Em dias de jogo há metro extra.",
        transport_tip_en="Metro to Estádio do Dragão (Lines A/B/E). Extra metro service on match days.",
        category="football",
        emoji="⚽",
    ),
    Event(
        name_pt="FC Porto — Noites de Champions League",
        name_en="FC Porto — Champions League Nights",
        venue_pt="Estádio do Dragão",
        venue_en="Estádio do Dragão",
        date_info_pt="Noites europeias — consultar calendário UEFA",
        date_info_en="European nights — check UEFA calendar",
        nearest_station="Estádio do Dragão",
        transport_tip_pt="Metro até Estádio do Dragão (Linhas A/B/E). Reforço de metro em noites europeias.",
        transport_tip_en="Metro to Estádio do Dragão (Lines A/B/E). Extra metro on European nights.",
        category="football",
        emoji="🏆",
    ),
    Event(
        name_pt="São João",
        name_en="São João Festival",
        venue_pt="Centro do Porto",
        venue_en="Porto city center",
        date_info_pt="23-24 de junho",
        date_info_en="June 23-24",
        nearest_station="Aliados",
        transport_tip_pt="Metro até Aliados ou São Bento. Metro funciona toda a noite de São João.",
        transport_tip_en="Metro to Aliados or São Bento. Metro runs all night on São João.",
        category="festival",
        emoji="🔨",
    ),
    Event(
        name_pt="Serralves em Festa",
        name_en="Serralves em Festa",
        venue_pt="Fundação de Serralves",
        venue_en="Serralves Foundation",
        date_info_pt="Junho (consultar datas)",
        date_info_en="June (check dates)",
        nearest_station="Casa da Música",
        transport_tip_pt="Metro até Casa da Música (Linhas A/B/C/E/F), depois 15 min a pé ou autocarro 201/203.",
        transport_tip_en="Metro to Casa da Música (Lines A/B/C/E/F), then 15 min walk or bus 201/203.",
        category="festival",
        emoji="🎨",
    ),
    Event(
        name_pt="NOS Primavera Sound",
        name_en="NOS Primavera Sound",
        venue_pt="Parque da Cidade",
        venue_en="Parque da Cidade",
        date_info_pt="Junho (consultar datas)",
        date_info_en="June (check dates)",
        nearest_station="Matosinhos Sul",
        transport_tip_pt="Metro até Matosinhos Sul (Linha A). Shuttles disponíveis nos dias do festival.",
        transport_tip_en="Metro to Matosinhos Sul (Line A). Shuttles available on festival days.",
        category="music",
        emoji="🎵",
    ),
    Event(
        name_pt="Fantasporto",
        name_en="Fantasporto Film Festival",
        venue_pt="Rivoli — Teatro Municipal",
        venue_en="Rivoli — Municipal Theatre",
        date_info_pt="Fevereiro-março",
        date_info_en="February-March",
        nearest_station="Aliados",
        transport_tip_pt="Metro até Aliados (Linha D), 3 min a pé até ao Rivoli.",
        transport_tip_en="Metro to Aliados (Line D), 3 min walk to Rivoli.",
        category="culture",
        emoji="🎬",
    ),
    Event(
        name_pt="Queima das Fitas",
        name_en="Queima das Fitas",
        venue_pt="Queimódromo",
        venue_en="Queimódromo",
        date_info_pt="Maio (uma semana)",
        date_info_en="May (one week)",
        nearest_station="Casa da Música",
        transport_tip_pt="Metro até Casa da Música (Linhas A/B/C/E/F). Autocarros especiais durante o evento.",
        transport_tip_en="Metro to Casa da Música (Lines A/B/C/E/F). Special buses during the event.",
        category="festival",
        emoji="🎓",
    ),
    Event(
        name_pt="Feira do Livro do Porto",
        name_en="Porto Book Fair",
        venue_pt="Jardins do Palácio de Cristal",
        venue_en="Crystal Palace Gardens",
        date_info_pt="Maio-junho",
        date_info_en="May-June",
        nearest_station="Casa da Música",
        transport_tip_pt="Metro até Casa da Música (Linhas A/B/C/E/F), depois autocarro 200/201 ou 15 min a pé.",
        transport_tip_en="Metro to Casa da Música (Lines A/B/C/E/F), then bus 200/201 or 15 min walk.",
        category="culture",
        emoji="📚",
    ),
    Event(
        name_pt="Noites Ritual",
        name_en="Noites Ritual",
        venue_pt="Jardins do Palácio de Cristal",
        venue_en="Crystal Palace Gardens",
        date_info_pt="Verão (consultar programação)",
        date_info_en="Summer (check schedule)",
        nearest_station="Casa da Música",
        transport_tip_pt="Metro até Casa da Música (Linhas A/B/C/E/F), depois autocarro 200/201 ou 15 min a pé.",
        transport_tip_en="Metro to Casa da Música (Lines A/B/C/E/F), then bus 200/201 or 15 min walk.",
        category="music",
        emoji="🎶",
    ),
]

EVENT_CATEGORIES = {
    "football": {"name_pt": "Futebol", "name_en": "Football", "emoji": "⚽"},
    "festival": {"name_pt": "Festivais", "name_en": "Festivals", "emoji": "🎉"},
    "music": {"name_pt": "Música", "name_en": "Music", "emoji": "🎵"},
    "culture": {"name_pt": "Cultura", "name_en": "Culture", "emoji": "🎭"},
}


def get_events(category: str | None = None) -> list[Event]:
    """Return events, optionally filtered by category."""
    if category is None:
        return list(EVENTS)
    return [e for e in EVENTS if e.category == category]


def get_event(index: int) -> Event | None:
    """Return a single event by its index in the global EVENTS list."""
    if 0 <= index < len(EVENTS):
        return EVENTS[index]
    return None


def get_event_categories() -> list[str]:
    """Return the list of event category keys."""
    return list(EVENT_CATEGORIES.keys())


def get_events_near_station(station_name: str) -> list[Event]:
    """Return events whose nearest_station matches (case-insensitive)."""
    normalised = station_name.lower()
    return [e for e in EVENTS if e.nearest_station.lower() == normalised]
