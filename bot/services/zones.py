"""Andante Zone Calculator for Porto public transport.

Maps metro, CP train and MetroBus stations to Andante zones (Z2-Z12)
and calculates zone crossings and ticket prices.
"""

import logging

logger = logging.getLogger(__name__)

# Andante zone ordering (for calculating number of zones crossed)
ZONE_ORDER: list[str] = [
    "Z2", "Z3", "Z4", "Z5", "Z6", "Z7", "Z8", "Z9", "Z10", "Z11", "Z12",
]

# Municipality code -> Andante zone mapping
# Each municipality may span multiple zones; we map individual stations below
_MUNICIPALITY_DEFAULT_ZONE: dict[str, str] = {
    "PRT": "Z2",
    "MTS": "Z4",
    "GDM": "Z3",
    "VNG": "Z5",
    "MAI": "Z4",
    "VLG": "Z5",
    "VCD": "Z8",
    "PVZ": "Z10",
}

# Complete station -> zone mapping for all transport modes
# Built from metro, CP and MetroBus station data with manual corrections
ZONES: dict[str, str] = {
    # ========== Metro stations ==========
    # Line A (Matosinhos)
    "Senhor de Matosinhos": "Z4",
    "Mercado": "Z4",
    "Brito Capelo": "Z4",
    "Matosinhos Sul": "Z4",
    "Câmara de Matosinhos": "Z3",
    "Parque de Real": "Z3",
    "Pedro Hispano": "Z3",
    "Estádio do Mar": "Z3",
    # Shared trunk (A/B/C/E)
    "Senhora da Hora": "Z3",
    "Sete Bicas": "Z3",
    "Viso": "Z2",
    "Ramalde": "Z2",
    "Francos": "Z2",
    "Casa da Música": "Z2",
    "Carolina Michaelis": "Z2",
    "Lapa": "Z2",
    "Trindade": "Z2",
    "Bolhão": "Z2",
    "Campo 24 de Agosto": "Z2",
    "Heroísmo": "Z2",
    "Campanhã": "Z3",
    "Estádio do Dragão": "Z3",
    # Line C/F extensions (Gondomar)
    "Nasoni": "Z3",
    "Nau Vitória": "Z3",
    "Levada": "Z3",
    "Rio Tinto": "Z3",
    "Campainha": "Z4",
    "Baguim": "Z4",
    "Fânzeres": "Z4",
    "São Roque": "Z3",
    "Contumil": "Z3",
    # Line C extension (Valongo / Maia)
    "Custió": "Z5",
    "Araújo": "Z5",
    "Cândido dos Reis": "Z5",
    "Fórum da Maia": "Z4",
    "Parque da Maia": "Z4",
    "Mandim": "Z5",
    "Zona Industrial": "Z5",
    "ISMAI": "Z6",
    # Line D (Porto center + Gaia)
    "Hospital de São João": "Z2",
    "IPO": "Z2",
    "Polo Universitário": "Z2",
    "Salgueiros": "Z2",
    "Combatentes": "Z2",
    "Marquês": "Z2",
    "Faria Guimarães": "Z2",
    "Aliados": "Z2",
    "São Bento": "Z2",
    "Jardim do Morro": "Z3",
    "General Torres": "Z3",
    "Santo Ovídio": "Z5",
    "Manuel Leão": "Z5",
    "João de Deus": "Z5",
    "D. João II": "Z5",
    "Câmara de Gaia": "Z5",
    "Vila d'Este": "Z5",
    # Line B (Póvoa de Varzim)
    "Custóias": "Z3",
    "Zona Industrial B": "Z4",
    "Mandim B": "Z4",
    "Crestins": "Z4",
    "Esposade": "Z8",
    "Varziela": "Z8",
    "Árvore": "Z8",
    "Azurara": "Z8",
    "Vila do Conde": "Z8",
    "Santa Clara": "Z9",
    "Portas Fronhas": "Z9",
    "Alto de Pega": "Z10",
    "Póvoa de Varzim": "Z10",
    # Line E (Airport)
    "Aeroporto": "Z4",
    "Verdes": "Z4",
    "Lidador": "Z4",
    "Botica": "Z4",
    "Fonte do Cuco": "Z4",
    "Custió E": "Z3",
    "Requezende": "Z3",
    # ========== CP Train stations ==========
    "Porto-Campanhã": "Z3",
    "Porto-São Bento": "Z2",
    "Ermesinde": "Z4",
    "Contumil CP": "Z3",  # CP Contumil (distinct from metro)
    "Rio Tinto CP": "Z3",  # CP Rio Tinto
    "Valongo": "Z5",
    "General Torres CP": "Z3",
    "Espinho": "Z7",
    "Aveiro": "Z12",
    "Braga": "Z12",
    "Guimarães": "Z12",
    "Marco de Canaveses": "Z12",
    "Caíde": "Z10",
    "Paredes": "Z8",
    "Penafiel": "Z10",
    "Nine": "Z10",
    "Viana do Castelo": "Z12",
    "Granja": "Z6",
    "Espinho-Vouga": "Z7",
    "São Félix da Marinha": "Z6",
    "Miramar": "Z6",
    "Valadares": "Z5",
    "Cete": "Z8",
    "Lordelo CP": "Z6",
    "Receção": "Z6",
    "São Romão": "Z4",
    "Leça do Balio": "Z4",
    "São Gemil": "Z4",
    "Trofa": "Z6",
    "Lousãdo": "Z8",
    "Vizela": "Z10",
    "Santo Tirso": "Z8",
    # ========== MetroBus stops ==========
    "Casa da Música (MetroBus)": "Z2",
    "Rotunda da Boavista": "Z2",
    "Bom Sucesso": "Z2",
    "Avenida da Boavista": "Z2",
    "Fluvial": "Z2",
    "Fonte da Moura": "Z2",
    "Francos (MetroBus)": "Z2",
    "Viso (MetroBus)": "Z2",
    "Estádio do Bessa": "Z2",
    "Norton de Matos": "Z3",
    "Jardim de Matosinhos": "Z3",
    "Matosinhos (MetroBus)": "Z4",
    "Praça da Galiza": "Z2",
    "Campo Alegre": "Z2",
    "Arrábida": "Z2",
    "Flor da Rosa": "Z2",
    "Lordelo": "Z2",
    "Passeio Alegre": "Z2",
    "Massarelos": "Z2",
    "Restauração": "Z2",
    "Constituição": "Z2",
    "Antas": "Z2",
    "Campanhã (MetroBus)": "Z3",
    "Via de Cintura Interna Este": "Z2",
    "Amial": "Z2",
    "Paranhos": "Z2",
    "Hospital de São João (MetroBus)": "Z2",
    "Polo Universitário (MetroBus)": "Z2",
    "Via de Cintura Interna Oeste": "Z2",
    "Prelada": "Z2",
    "Carvalhido": "Z2",
    "Ramalde (MetroBus)": "Z2",
}

# CP station name aliases (CP names that differ from keys in ZONES)
_CP_ALIASES: dict[str, str] = {
    "Contumil": "Contumil",  # metro Contumil
    "Rio Tinto": "Rio Tinto",  # metro Rio Tinto
    "General Torres": "General Torres",  # metro General Torres
    "Lordelo": "Lordelo",  # metrobus Lordelo
    "Caíde": "Caíde",
    "Lousãdo": "Lousãdo",
    "Receção": "Receção",
}

# Ticket prices (approximate 2024)
ZONE_PRICES: dict[int, float] = {
    1: 1.40,   # Z2 only (same zone)
    2: 1.95,   # 2 contiguous zones
    3: 2.50,   # 3 zones
    4: 3.05,   # 4 zones
    5: 3.60,   # 5 zones
    6: 4.15,   # 6 zones
    7: 4.70,   # 7 zones
    8: 5.25,   # 8 zones
    9: 5.80,   # 9 zones
    10: 6.35,  # 10 zones
    11: 6.90,  # 11 zones
}

# Day pass (Andante 24h) prices
DAY_PASS_PRICES: dict[int, float] = {
    1: 4.15,    # Z2 only
    2: 5.80,    # 2 zones
    3: 7.50,    # 3 zones
    4: 9.15,    # 4 zones
    5: 10.80,   # 5 zones
    6: 12.45,   # 6 zones
    7: 14.10,   # 7 zones
    8: 15.30,   # all zones
    9: 15.30,
    10: 15.30,
    11: 15.30,
}

# Andante Tour (tourist pass)
ANDANTE_TOUR_PRICE = 15.00  # 3-day all-zones pass


def get_zone_for_station(station_name: str) -> str | None:
    """Get the Andante zone for a station/stop name.

    Tries exact match first, then fuzzy matching across metro, CP and
    MetroBus station dictionaries.
    """
    # Direct lookup
    if station_name in ZONES:
        return ZONES[station_name]

    # Try case-insensitive lookup
    name_lower = station_name.lower()
    for key, zone in ZONES.items():
        if key.lower() == name_lower:
            return zone

    # Try to find in metro/CP/metrobus station dicts and use municipality
    from bot.services.metro import STATIONS as METRO_STATIONS
    from bot.services.cp import STATIONS as CP_STATIONS
    from bot.services.metrobus import STOPS as METROBUS_STOPS

    if station_name in METRO_STATIONS:
        muni = METRO_STATIONS[station_name].get("zone", "")
        return _MUNICIPALITY_DEFAULT_ZONE.get(muni)

    if station_name in CP_STATIONS:
        # CP stations don't have zone field, use fuzzy on ZONES
        pass

    if station_name in METROBUS_STOPS:
        muni = METROBUS_STOPS[station_name].get("zone", "")
        return _MUNICIPALITY_DEFAULT_ZONE.get(muni)

    # Fuzzy search as last resort
    try:
        from bot.utils.search import fuzzy_search
        matches = fuzzy_search(station_name, list(ZONES.keys()),
                               min_score=40, max_results=1)
        if matches:
            return ZONES[matches[0][0]]
    except ImportError:
        pass

    return None


def _zone_index(zone: str) -> int:
    """Return the index of a zone in ZONE_ORDER (0-based)."""
    try:
        return ZONE_ORDER.index(zone)
    except ValueError:
        return -1


def calculate_zones(origin: str, destination: str) -> dict | None:
    """Calculate zones needed to travel between two stations.

    Returns a dict with:
        - origin_zone: zone code of origin
        - dest_zone: zone code of destination
        - zones_needed: number of zones to cross (minimum 1)
        - price: single ticket price in euros
        - day_pass_price: 24h pass price in euros
        - origin_name: resolved origin name
        - dest_name: resolved destination name

    Returns None if either station is not found.
    """
    origin_zone = get_zone_for_station(origin)
    dest_zone = get_zone_for_station(destination)

    if not origin_zone or not dest_zone:
        return None

    origin_idx = _zone_index(origin_zone)
    dest_idx = _zone_index(dest_zone)

    if origin_idx < 0 or dest_idx < 0:
        return None

    # Number of zones = difference + 1 (you always pay for at least 1 zone)
    zones_needed = abs(dest_idx - origin_idx) + 1

    return {
        "origin_zone": origin_zone,
        "dest_zone": dest_zone,
        "zones_needed": zones_needed,
        "price": get_price(zones_needed),
        "day_pass_price": get_day_pass_price(zones_needed),
        "origin_name": origin,
        "dest_name": destination,
    }


def get_price(num_zones: int) -> float:
    """Get the single ticket price for a given number of zones."""
    num_zones = max(1, num_zones)
    if num_zones in ZONE_PRICES:
        return ZONE_PRICES[num_zones]
    # Beyond mapped prices, return the highest known
    return ZONE_PRICES[max(ZONE_PRICES.keys())]


def get_day_pass_price(num_zones: int) -> float:
    """Get the Andante 24h pass price for a given number of zones."""
    num_zones = max(1, num_zones)
    if num_zones in DAY_PASS_PRICES:
        return DAY_PASS_PRICES[num_zones]
    return DAY_PASS_PRICES[max(DAY_PASS_PRICES.keys())]


def get_stations_in_zone(zone: str) -> list[str]:
    """Get all stations/stops in a given Andante zone."""
    return sorted([name for name, z in ZONES.items() if z == zone])


def get_all_zones() -> list[str]:
    """Get all zones that have at least one station."""
    zones_with_stations = set(ZONES.values())
    return [z for z in ZONE_ORDER if z in zones_with_stations]


def search_station(query: str) -> list[tuple[str, str]]:
    """Search for a station across all transport modes.

    Returns list of (station_name, zone) tuples.
    """
    query_lower = query.strip().lower()
    if not query_lower:
        return []

    results = []
    for name, zone in ZONES.items():
        if query_lower in name.lower():
            results.append((name, zone))

    # Sort by match quality (starts-with first, then alphabetical)
    results.sort(key=lambda x: (not x[0].lower().startswith(query_lower), x[0]))
    return results[:10]
