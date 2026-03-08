"""Event data for Porto — FC Porto matches, festivals, concerts, culture."""

from dataclasses import dataclass
from datetime import date


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
    start_date: date
    end_date: date


EVENTS: list[Event] = [
    Event(
        name_pt="FC Porto vs SC Braga",
        name_en="FC Porto vs SC Braga",
        venue_pt="Estádio do Dragão",
        venue_en="Estádio do Dragão",
        date_info_pt="8 de março, 20h30",
        date_info_en="March 8, 8:30 PM",
        nearest_station="Estádio do Dragão",
        transport_tip_pt="Metro até Estádio do Dragão (Linhas A/B/E). Em dias de jogo há metro extra.",
        transport_tip_en="Metro to Estádio do Dragão (Lines A/B/E). Extra metro service on match days.",
        category="football",
        emoji="⚽",
        start_date=date(2026, 3, 8),
        end_date=date(2026, 3, 8),
    ),
    Event(
        name_pt="Fantasporto 2026",
        name_en="Fantasporto 2026",
        venue_pt="Rivoli — Teatro Municipal",
        venue_en="Rivoli — Municipal Theatre",
        date_info_pt="28 fev — 14 mar",
        date_info_en="Feb 28 — Mar 14",
        nearest_station="Aliados",
        transport_tip_pt="Metro até Aliados (Linha D), 3 min a pé até ao Rivoli.",
        transport_tip_en="Metro to Aliados (Line D), 3 min walk to Rivoli.",
        category="culture",
        emoji="🎬",
        start_date=date(2026, 2, 28),
        end_date=date(2026, 3, 14),
    ),
    Event(
        name_pt="FC Porto vs Moreirense",
        name_en="FC Porto vs Moreirense",
        venue_pt="Estádio do Dragão",
        venue_en="Estádio do Dragão",
        date_info_pt="22 de março, 18h00",
        date_info_en="March 22, 6:00 PM",
        nearest_station="Estádio do Dragão",
        transport_tip_pt="Metro até Estádio do Dragão (Linhas A/B/E). Em dias de jogo há metro extra.",
        transport_tip_en="Metro to Estádio do Dragão (Lines A/B/E). Extra metro service on match days.",
        category="football",
        emoji="⚽",
        start_date=date(2026, 3, 22),
        end_date=date(2026, 3, 22),
    ),
    Event(
        name_pt="FC Porto vs Benfica",
        name_en="FC Porto vs Benfica",
        venue_pt="Estádio do Dragão",
        venue_en="Estádio do Dragão",
        date_info_pt="12 de abril, 20h30",
        date_info_en="April 12, 8:30 PM",
        nearest_station="Estádio do Dragão",
        transport_tip_pt="Metro até Estádio do Dragão (Linhas A/B/E). Em dias de jogo há metro extra. Clássico — espera mais afluência.",
        transport_tip_en="Metro to Estádio do Dragão (Lines A/B/E). Extra metro on match days. Derby — expect larger crowds.",
        category="football",
        emoji="⚽",
        start_date=date(2026, 4, 12),
        end_date=date(2026, 4, 12),
    ),
    Event(
        name_pt="Queima das Fitas do Porto",
        name_en="Queima das Fitas",
        venue_pt="Queimódromo",
        venue_en="Queimódromo",
        date_info_pt="3 — 10 mai",
        date_info_en="May 3 — 10",
        nearest_station="Casa da Música",
        transport_tip_pt="Metro até Casa da Música (Linhas A/B/C/E/F). Autocarros especiais durante o evento.",
        transport_tip_en="Metro to Casa da Música (Lines A/B/C/E/F). Special buses during the event.",
        category="festival",
        emoji="🎓",
        start_date=date(2026, 5, 3),
        end_date=date(2026, 5, 10),
    ),
    Event(
        name_pt="Feira do Livro do Porto",
        name_en="Porto Book Fair",
        venue_pt="Jardins do Palácio de Cristal",
        venue_en="Crystal Palace Gardens",
        date_info_pt="15 mai — 1 jun",
        date_info_en="May 15 — Jun 1",
        nearest_station="Casa da Música",
        transport_tip_pt="Metro até Casa da Música (Linhas A/B/C/E/F), depois autocarro 200/201 ou 15 min a pé.",
        transport_tip_en="Metro to Casa da Música (Lines A/B/C/E/F), then bus 200/201 or 15 min walk.",
        category="culture",
        emoji="📚",
        start_date=date(2026, 5, 15),
        end_date=date(2026, 6, 1),
    ),
    Event(
        name_pt="NOS Primavera Sound",
        name_en="NOS Primavera Sound",
        venue_pt="Parque da Cidade",
        venue_en="Parque da Cidade",
        date_info_pt="4 — 7 jun",
        date_info_en="Jun 4 — 7",
        nearest_station="Matosinhos Sul",
        transport_tip_pt="Metro até Matosinhos Sul (Linha A). Shuttles disponíveis nos dias do festival.",
        transport_tip_en="Metro to Matosinhos Sul (Line A). Shuttles available on festival days.",
        category="music",
        emoji="🎵",
        start_date=date(2026, 6, 4),
        end_date=date(2026, 6, 7),
    ),
    Event(
        name_pt="Serralves em Festa",
        name_en="Serralves em Festa",
        venue_pt="Fundação de Serralves",
        venue_en="Serralves Foundation",
        date_info_pt="13 — 14 jun",
        date_info_en="Jun 13 — 14",
        nearest_station="Casa da Música",
        transport_tip_pt="Metro até Casa da Música (Linhas A/B/C/E/F), depois 15 min a pé ou autocarro 201/203.",
        transport_tip_en="Metro to Casa da Música (Lines A/B/C/E/F), then 15 min walk or bus 201/203.",
        category="festival",
        emoji="🎨",
        start_date=date(2026, 6, 13),
        end_date=date(2026, 6, 14),
    ),
    Event(
        name_pt="São João",
        name_en="São João Festival",
        venue_pt="Centro do Porto",
        venue_en="Porto city center",
        date_info_pt="23 — 24 jun",
        date_info_en="Jun 23 — 24",
        nearest_station="Aliados",
        transport_tip_pt="Metro até Aliados ou São Bento. Metro funciona toda a noite de São João.",
        transport_tip_en="Metro to Aliados or São Bento. Metro runs all night on São João.",
        category="festival",
        emoji="🔨",
        start_date=date(2026, 6, 23),
        end_date=date(2026, 6, 24),
    ),
    Event(
        name_pt="Noites Ritual",
        name_en="Noites Ritual",
        venue_pt="Jardins do Palácio de Cristal",
        venue_en="Crystal Palace Gardens",
        date_info_pt="2 jul — 29 ago",
        date_info_en="Jul 2 — Aug 29",
        nearest_station="Casa da Música",
        transport_tip_pt="Metro até Casa da Música (Linhas A/B/C/E/F), depois autocarro 200/201 ou 15 min a pé.",
        transport_tip_en="Metro to Casa da Música (Lines A/B/C/E/F), then bus 200/201 or 15 min walk.",
        category="music",
        emoji="🎶",
        start_date=date(2026, 7, 2),
        end_date=date(2026, 8, 29),
    ),
]

EVENT_CATEGORIES = {
    "football": {"name_pt": "Futebol", "name_en": "Football", "emoji": "⚽"},
    "festival": {"name_pt": "Festivais", "name_en": "Festivals", "emoji": "🎉"},
    "music": {"name_pt": "Música", "name_en": "Music", "emoji": "🎵"},
    "culture": {"name_pt": "Cultura", "name_en": "Culture", "emoji": "🎭"},
}


def get_todays_events(today: date | None = None) -> list[Event]:
    """Return events happening today."""
    if today is None:
        today = date.today()
    return [e for e in EVENTS if e.start_date <= today <= e.end_date]


def get_upcoming_events(today: date | None = None, limit: int = 5) -> list[Event]:
    """Return the next upcoming events (starting after today)."""
    if today is None:
        today = date.today()
    future = [e for e in EVENTS if e.start_date > today]
    future.sort(key=lambda e: e.start_date)
    return future[:limit]


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
