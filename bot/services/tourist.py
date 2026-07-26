"""Tourist points of interest data for Porto.

Curated transport information for popular tourist destinations,
including metro lines, bus alternatives, zones, and practical tips.

Every price shown here comes from :mod:`bot.services.fares`, and every "zone"
below is the Andante *title* you need to buy starting from central Porto
(``PRT1``), computed with :mod:`bot.services.zones` rather than typed in by
hand.  That is why the zone calculator and this guide can no longer disagree.
"""

from bot.services import fares
from bot.services.zones import calculate_zones


def _title_from_porto_centre(station: str, fallback: str = "Z2") -> str:
    """Andante title needed to reach ``station`` from central Porto.

    Falls back to ``fallback`` for places we have no station entry for (e.g.
    destinations reached only by city bus, which stay inside PRT1/PRT2 and are
    therefore Z2 anyway).
    """
    result = calculate_zones("Trindade", station)
    if result and result.get("title"):
        return result["title"]
    return fallback


TOURIST_POIS = {
    "beaches": {
        "title_pt": "Praias",
        "title_en": "Beaches",
        "emoji": "🏖",
        "destinations": [
            {
                "name_pt": "Praia de Matosinhos",
                "name_en": "Matosinhos Beach",
                "best_transport": "metro",
                "station": "Matosinhos Sul",
                "line": "A",
                "line_name": "Linha Azul",
                "bus_alt": "500, 502",
                "zone": _title_from_porto_centre("Matosinhos Sul"),
                "walk_min": 5,
                "tip_pt": "Sai na estação Matosinhos Sul, 5 min a pé até à praia. Zona com ótimos restaurantes de peixe fresco.",
                "tip_en": "Exit at Matosinhos Sul, 5 min walk to the beach. Area has great fresh fish restaurants.",
            },
            {
                "name_pt": "Praias da Foz",
                "name_en": "Foz Beaches",
                "best_transport": "bus",
                "station": "Foz (via autocarro)",
                "line": "500",
                "line_name": "Bus 500",
                "bus_alt": "500, 203",
                "zone": _title_from_porto_centre("Foz (via autocarro)", "Z2"),
                "walk_min": 3,
                "tip_pt": "Apanha o autocarro 500 desde a Praça da Liberdade. Percurso panorâmico junto ao rio Douro.",
                "tip_en": "Take bus 500 from Praça da Liberdade. Scenic route along the Douro river.",
            },
        ],
    },
    "wine_cellars": {
        "title_pt": "Caves do Vinho do Porto",
        "title_en": "Port Wine Cellars",
        "emoji": "🍷",
        "destinations": [
            {
                "name_pt": "Caves de Gaia (Cais)",
                "name_en": "Gaia Cellars (Waterfront)",
                "best_transport": "metro",
                "station": "Jardim do Morro",
                "line": "D",
                "line_name": "Linha Amarela",
                "bus_alt": "900, 901, 906",
                "zone": _title_from_porto_centre("Jardim do Morro"),
                "walk_min": 10,
                "tip_pt": "Sai em Jardim do Morro e desce a pé até ao cais. Vista espetacular da Ponte D. Luís I.",
                "tip_en": "Exit at Jardim do Morro and walk down to the waterfront. Spectacular view of D. Luís I Bridge.",
            },
            {
                "name_pt": "Caves de Gaia (General Torres)",
                "name_en": "Gaia Cellars (General Torres)",
                "best_transport": "metro",
                "station": "General Torres",
                "line": "D",
                "line_name": "Linha Amarela",
                "bus_alt": "900, 901",
                "zone": _title_from_porto_centre("General Torres"),
                "walk_min": 5,
                "tip_pt": "Estação mais próxima do centro das caves. Podes visitar Taylor's, Graham's e Sandeman.",
                "tip_en": "Closest station to the main cellars area. You can visit Taylor's, Graham's and Sandeman.",
            },
        ],
    },
    "historic_center": {
        "title_pt": "Centro Histórico",
        "title_en": "Historic Center",
        "emoji": "⛪",
        "destinations": [
            {
                "name_pt": "Ribeira",
                "name_en": "Ribeira (Riverside)",
                "best_transport": "metro",
                "station": "São Bento",
                "line": "D",
                "line_name": "Linha Amarela",
                "bus_alt": "1, 500, 900",
                "zone": _title_from_porto_centre("São Bento"),
                "walk_min": 10,
                "tip_pt": "Do São Bento, desce pela Rua das Flores até à Ribeira. Património UNESCO.",
                "tip_en": "From São Bento, walk down Rua das Flores to Ribeira. UNESCO World Heritage site.",
            },
            {
                "name_pt": "Torre dos Clérigos",
                "name_en": "Clérigos Tower",
                "best_transport": "metro",
                "station": "Aliados",
                "line": "D",
                "line_name": "Linha Amarela",
                "bus_alt": "200, 201, 207",
                "zone": _title_from_porto_centre("Aliados"),
                "walk_min": 5,
                "tip_pt": "Sai nos Aliados e caminha até à Torre. Sobe os 240 degraus para uma vista panorâmica.",
                "tip_en": "Exit at Aliados and walk to the Tower. Climb 240 steps for a panoramic view.",
            },
            {
                "name_pt": "Estação de São Bento",
                "name_en": "São Bento Station",
                "best_transport": "metro",
                "station": "São Bento",
                "line": "D",
                "line_name": "Linha Amarela",
                "bus_alt": "1, 200, 900",
                "zone": _title_from_porto_centre("São Bento"),
                "walk_min": 0,
                "tip_pt": "A estação de metro é dentro da própria estação histórica. Não percas os azulejos!",
                "tip_en": "The metro station is inside the historic train station itself. Don't miss the tile panels!",
            },
        ],
    },
    "airport": {
        "title_pt": "Aeroporto",
        "title_en": "Airport",
        "emoji": "✈️",
        "destinations": [
            {
                "name_pt": "Aeroporto Francisco Sá Carneiro",
                "name_en": "Porto Airport (OPO)",
                "best_transport": "metro",
                "station": "Aeroporto",
                "line": "E",
                "line_name": "Linha Violeta",
                "bus_alt": "601, 602, 604",
                "zone": _title_from_porto_centre("Aeroporto"),
                "walk_min": 0,
                "tip_pt": (
                    "Metro direto, ~35 min desde Trindade. Frequência: 20-30 min. "
                    f"Compra bilhete {_title_from_porto_centre('Aeroporto')} "
                    f"({fares.format_price(fares.get_price(4))} "
                    f"+ cartão Andante {fares.format_price(fares.CARD_PRICE_BLUE)})."
                ),
                "tip_en": (
                    "Direct metro, ~35 min from Trindade. Frequency: 20-30 min. "
                    f"Buy a {_title_from_porto_centre('Aeroporto')} ticket "
                    f"({fares.format_price(fares.get_price(4))} "
                    f"+ Andante card {fares.format_price(fares.CARD_PRICE_BLUE)})."
                ),
            },
        ],
    },
    "stadium": {
        "title_pt": "Estádio do Dragão",
        "title_en": "Dragon Stadium",
        "emoji": "⚽",
        "destinations": [
            {
                "name_pt": "Estádio do Dragão (FC Porto)",
                "name_en": "Estádio do Dragão (FC Porto)",
                "best_transport": "metro",
                "station": "Estádio do Dragão",
                "line": "A",
                "line_name": "Linha Azul",
                "bus_alt": "300, 305, 400, 401",
                "zone": _title_from_porto_centre("Estádio do Dragão"),
                "walk_min": 2,
                "tip_pt": "Estação dedicada ao estádio nas linhas A, B e E. Em dias de jogo, há metro extra.",
                "tip_en": "Dedicated station on lines A, B and E. Extra metro service on match days.",
            },
        ],
    },
    "universities": {
        "title_pt": "Universidades",
        "title_en": "Universities",
        "emoji": "🎓",
        "destinations": [
            {
                "name_pt": "Universidade do Porto (Polo I - Reitoria)",
                "name_en": "University of Porto (Main Campus)",
                "best_transport": "metro",
                "station": "Polo Universitário",
                "line": "D",
                "line_name": "Linha Amarela",
                "bus_alt": "204, 300, 301",
                "zone": _title_from_porto_centre("Polo Universitário"),
                "walk_min": 3,
                "tip_pt": "Estação Polo Universitário serve diretamente o campus principal da UP.",
                "tip_en": "Polo Universitário station directly serves the main UP campus.",
            },
            {
                "name_pt": "FEUP - Faculdade de Engenharia",
                "name_en": "FEUP - Engineering Faculty",
                "best_transport": "bus",
                "station": "FEUP (via autocarro)",
                "line": "204, 300",
                "line_name": "Bus 204 / 300",
                "bus_alt": "204, 300, 301, 305",
                "zone": _title_from_porto_centre("FEUP (via autocarro)", "Z2"),
                "walk_min": 5,
                "tip_pt": "Autocarros 204 ou 300 desde a Trindade. Metro mais próximo: Polo Universitário (15 min a pé).",
                "tip_en": "Buses 204 or 300 from Trindade. Nearest metro: Polo Universitário (15 min walk).",
            },
            {
                "name_pt": "ISEP - Inst. Superior de Engenharia",
                "name_en": "ISEP - Engineering Institute",
                "best_transport": "bus",
                "station": "ISEP (via autocarro)",
                "line": "204, 300",
                "line_name": "Bus 204 / 300",
                "bus_alt": "204, 300, 305",
                "zone": _title_from_porto_centre("ISEP (via autocarro)", "Z2"),
                "walk_min": 5,
                "tip_pt": "Fica perto do FEUP. Autocarros 204 ou 300 são a melhor opção.",
                "tip_en": "Near FEUP. Buses 204 or 300 are the best option.",
            },
        ],
    },
    "hospitals": {
        "title_pt": "Hospitais",
        "title_en": "Hospitals",
        "emoji": "🏥",
        "destinations": [
            {
                "name_pt": "Hospital de São João",
                "name_en": "São João Hospital",
                "best_transport": "metro",
                "station": "Hospital de São João",
                "line": "D",
                "line_name": "Linha Amarela",
                "bus_alt": "204, 300, 301",
                "zone": _title_from_porto_centre("Hospital de São João"),
                "walk_min": 2,
                "tip_pt": "Estação de metro dedicada. Linha D desde a Trindade (~12 min).",
                "tip_en": "Dedicated metro station. Line D from Trindade (~12 min).",
            },
            {
                "name_pt": "Hospital de Santo António (CHP)",
                "name_en": "Santo António Hospital",
                "best_transport": "metro",
                "station": "Aliados",
                "line": "D",
                "line_name": "Linha Amarela",
                "bus_alt": "200, 201, 207, 501",
                "zone": _title_from_porto_centre("Aliados"),
                "walk_min": 8,
                "tip_pt": "Metro até Aliados, depois 8 min a pé. Ou autocarro 200/201 até ao Hospital.",
                "tip_en": "Metro to Aliados, then 8 min walk. Or bus 200/201 to the Hospital.",
            },
            {
                "name_pt": "IPO Porto (Oncologia)",
                "name_en": "IPO Porto (Oncology)",
                "best_transport": "metro",
                "station": "IPO",
                "line": "D",
                "line_name": "Linha Amarela",
                "bus_alt": "204, 300",
                "zone": _title_from_porto_centre("IPO"),
                "walk_min": 2,
                "tip_pt": "Estação de metro IPO na linha D. Muito perto do hospital.",
                "tip_en": "IPO metro station on line D. Very close to the hospital.",
            },
        ],
    },
    "tickets": {
        "title_pt": "Bilhetes e Andante",
        "title_en": "Tickets & Andante",
        "emoji": "🎫",
        "destinations": [],  # Ticket info is handled specially
    },
}


# Ticket / Andante zone information
TICKET_INFO = {
    "pt": {
        "title": "🎫 *Bilhetes e Cartão Andante*",
        "sections": [
            {
                "heading": "💳 Cartão Andante",
                "text": (
                    "O Andante é o cartão recarregável usado no metro, "
                    "autocarros STCP e outros transportes do Porto\\.\n"
                    "• Cartão: €0\\.60 \\(compra única\\)\n"
                    "• Recarregável com títulos de viagem"
                ),
            },
            {
                "heading": "🗺 Sistema de Zonas",
                "text": (
                    "O Porto usa um sistema de zonas concêntricas:\n"
                    "• *Z2* — Centro do Porto \\(a maioria dos pontos turísticos\\)\n"
                    "• *Z3* — Subúrbios próximos \\(Gaia, Gondomar\\)\n"
                    "• *Z4* — Matosinhos, Aeroporto\n"
                    "• *Z5\\-Z10* — Zonas mais afastadas\n\n"
                    "O preço depende do número de zonas que atravessas\\."
                ),
            },
            {
                "heading": "💰 Preços \\(título ocasional\\)",
                "text": (
                    "• Z2 \\(1 zona\\): €1\\.25\n"
                    "• Z3 \\(2 zonas\\): €1\\.65\n"
                    "• Z4 \\(3 zonas\\): €2\\.00\n"
                    "• Z5 \\(4 zonas\\): €2\\.50\n\n"
                    "Cada título é válido por 1 hora\\."
                ),
            },
            {
                "heading": "📅 Passe Diário",
                "text": (
                    "• *Andante 24*: viagens ilimitadas por 24h\n"
                    "  Z2: €4\\.15 \\| Z3: €5\\.50 \\| Z4: €7\\.00\n"
                    "• *Andante Tour 1*: 24h todas as zonas — €7\\.00\n"
                    "• *Andante Tour 3*: 72h todas as zonas — €15\\.00"
                ),
            },
            {
                "heading": "🏪 Onde comprar",
                "text": (
                    "• Máquinas automáticas em todas as estações de metro\n"
                    "• Lojas Andante \\(Trindade, Casa da Música\\)\n"
                    "• Papelarias e quiosques com sinal Andante\n"
                    "• Aeroporto: máquinas na estação de metro"
                ),
            },
            {
                "heading": "✈️ Bilhete Aeroporto",
                "text": (
                    "O aeroporto está na *Zona Z4*\\.\n"
                    "Título Z4: *€2\\.00* \\+ cartão €0\\.60 se não tiveres\\.\n"
                    "Compra na máquina automática à entrada do metro no aeroporto\\."
                ),
            },
        ],
    },
    "en": {
        "title": "🎫 *Tickets \\& Andante Card*",
        "sections": [
            {
                "heading": "💳 Andante Card",
                "text": (
                    "The Andante is the rechargeable card used on metro, "
                    "STCP buses and other Porto transport\\.\n"
                    "• Card: €0\\.60 \\(one\\-time purchase\\)\n"
                    "• Rechargeable with travel titles"
                ),
            },
            {
                "heading": "🗺 Zone System",
                "text": (
                    "Porto uses a concentric zone system:\n"
                    "• *Z2* — Porto center \\(most tourist spots\\)\n"
                    "• *Z3* — Near suburbs \\(Gaia, Gondomar\\)\n"
                    "• *Z4* — Matosinhos, Airport\n"
                    "• *Z5\\-Z10* — Further zones\n\n"
                    "The price depends on how many zones you cross\\."
                ),
            },
            {
                "heading": "💰 Prices \\(single ticket\\)",
                "text": (
                    "• Z2 \\(1 zone\\): €1\\.25\n"
                    "• Z3 \\(2 zones\\): €1\\.65\n"
                    "• Z4 \\(3 zones\\): €2\\.00\n"
                    "• Z5 \\(4 zones\\): €2\\.50\n\n"
                    "Each title is valid for 1 hour\\."
                ),
            },
            {
                "heading": "📅 Day Pass",
                "text": (
                    "• *Andante 24*: unlimited travel for 24h\n"
                    "  Z2: €4\\.15 \\| Z3: €5\\.50 \\| Z4: €7\\.00\n"
                    "• *Andante Tour 1*: 24h all zones — €7\\.00\n"
                    "• *Andante Tour 3*: 72h all zones — €15\\.00"
                ),
            },
            {
                "heading": "🏪 Where to buy",
                "text": (
                    "• Ticket machines at all metro stations\n"
                    "• Andante shops \\(Trindade, Casa da Música\\)\n"
                    "• Paper shops and kiosks with Andante sign\n"
                    "• Airport: machines at metro station entrance"
                ),
            },
            {
                "heading": "✈️ Airport Ticket",
                "text": (
                    "The airport is in *Zone Z4*\\.\n"
                    "Z4 title: *€2\\.00* \\+ card €0\\.60 if you don't have one\\.\n"
                    "Buy at the ticket machine at the metro entrance in the airport\\."
                ),
            },
        ],
    },
}


def get_categories() -> list[str]:
    """Return all POI category keys."""
    return list(TOURIST_POIS.keys())


def get_category(key: str) -> dict | None:
    """Return a category dict by key, or None."""
    return TOURIST_POIS.get(key)


def get_destination(category_key: str, dest_index: int) -> dict | None:
    """Return a specific destination from a category by index."""
    cat = TOURIST_POIS.get(category_key)
    if not cat:
        return None
    dests = cat.get("destinations", [])
    if 0 <= dest_index < len(dests):
        return dests[dest_index]
    return None


def get_ticket_info(lang: str = "pt") -> dict:
    """Return the ticket info for the given language."""
    return TICKET_INFO.get(lang, TICKET_INFO["pt"])
