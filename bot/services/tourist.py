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


# ---------------------------------------------------------------------------
# Ticket / Andante information
#
# Built at import time from bot.services.fares so that this guide and the zone
# calculator can never quote different prices for the same ticket.  Strings are
# pre-escaped for Telegram MarkdownV2 because handlers/tourist.py inserts them
# verbatim.
# ---------------------------------------------------------------------------


def _esc(text: str) -> str:
    """Escape text for Telegram MarkdownV2."""
    from bot.utils.formatting import escape_md
    return escape_md(text)


def _money(value: float | None) -> str:
    """A price, MarkdownV2-escaped, or a clear 'not published' marker."""
    if value is None:
        return _esc("n/d")
    return _esc(f"{value:.2f}\u20ac")


def _occasional_lines(lang: str) -> str:
    """One bullet per priced occasional title, straight from the fare table."""
    zones_word = "zonas" if lang == "pt" else "zones"
    out = []
    for n in sorted(fares.OCCASIONAL_PRICES):
        out.append(
            f"\u2022 *{_esc(f'Z{n}')}* \\({n} {zones_word}\\): "
            f"{_money(fares.OCCASIONAL_PRICES[n])} "
            f"\u2014 {_esc(fares.MAX_TRIP_DURATION[n])}"
        )
    return "\n".join(out)


def _day_pass_lines() -> str:
    out = []
    for n in sorted(fares.DAY_PASS_PRICES):
        out.append(f"\u2022 *{_esc(f'Z{n}')}*: {_money(fares.DAY_PASS_PRICES[n])}")
    return "\n".join(out)


def _build_ticket_info(lang: str) -> dict:
    tour1 = _money(fares.get_tour_price(1))
    tour3 = _money(fares.get_tour_price(3))
    blue = _money(fares.CARD_PRICE_BLUE)
    silver = _money(fares.CARD_PRICE_SILVER)
    airport_title = _title_from_porto_centre("Aeroporto")
    airport_price = _money(fares.get_price(fares.title_zones(4)))
    monthly_3z = _money(fares.get_monthly_price("3Z"))
    monthly_metro = _money(fares.get_monthly_price("metropolitano"))
    labels = fares.MONTHLY_LABELS.get(lang, fares.MONTHLY_LABELS["pt"])
    max_priced = fares.MAX_PRICED_ZONES
    verified = _esc(fares.verified_note(lang))

    if lang == "en":
        return {
            "title": "\U0001f3ab *Tickets \\& Andante Card*",
            "sections": [
                {
                    "heading": "\U0001f4b3 Andante Card",
                    "text": (
                        "Andante is the card used on the metro, STCP buses, CP "
                        "urban trains and the MetroBus\\.\n"
                        f"\u2022 Andante Azul \\(occasional\\): {blue}\n"
                        f"\u2022 Andante Prateado \\(monthly passes\\): {silver}"
                    ),
                },
                {
                    "heading": "\U0001f5fa How zones work",
                    "text": (
                        "Andante zones are *not* numbered rings\\. They have real "
                        "names such as *PRT1* \\(central Porto\\), *VNG1* "
                        "\\(Gaia riverside\\) or *VCD8* \\(the airport\\), and they "
                        "are printed at every station\\.\n\n"
                        "*Z2*, *Z3*, *Z4*\\.\\.\\. are *ticket* names: the number of "
                        "zones the ticket covers, counted outwards from where "
                        "you validate\\. Every ticket covers at least 2 zones, "
                        "so a trip inside one zone still needs a *Z2*\\."
                    ),
                },
                {
                    "heading": "\U0001f4b0 Single tickets",
                    "text": (
                        _occasional_lines("en")
                        + "\n\nBuy 10 and get 1 free\\.\n"
                        + _esc(f"Titles above Z{max_priced} exist but their price "
                               "is not published online — check at a machine.")
                    ),
                },
                {
                    "heading": "\U0001f4c5 Andante 24 \\(24h\\)",
                    "text": _day_pass_lines(),
                },
                {
                    "heading": "\U0001f9f3 Andante Tour \\(tourists\\)",
                    "text": (
                        f"\u2022 *Tour 1* — 24h, all zones: {tour1}\n"
                        f"\u2022 *Tour 3* — 72h, all zones: {tour3}\n"
                        + _esc("Not valid on the Guindais funicular or the STCP tram.")
                    ),
                },
                {
                    "heading": "\U0001f4c6 Monthly passes",
                    "text": (
                        f"\u2022 *{_esc(labels['3Z'])}*: {monthly_3z}\n"
                        f"\u2022 *{_esc(labels['metropolitano'])}*: {monthly_metro}"
                    ),
                },
                {
                    "heading": "\U0001f3ea Where to buy",
                    "text": (
                        "\u2022 Ticket machines at every metro station\n"
                        "\u2022 Andante shops \\(Trindade, Casa da M\u00fasica\\)\n"
                        "\u2022 CP ticket offices and Payshop agents\n"
                        "\u2022 Airport: machines at the metro entrance"
                    ),
                },
                {
                    "heading": "\u2708\ufe0f Airport ticket",
                    "text": (
                        f"The airport is in zone *VCD8*\\. From central Porto that "
                        f"is a *{_esc(airport_title)}* ticket: *{airport_price}* "
                        f"\\+ {blue} for the card if you do not have one\\."
                    ),
                },
                {
                    "heading": "\u2705 Price check",
                    "text": f"_{verified}_",
                },
            ],
        }

    return {
        "title": "\U0001f3ab *Bilhetes e Cart\u00e3o Andante*",
        "sections": [
            {
                "heading": "\U0001f4b3 Cart\u00e3o Andante",
                "text": (
                    "O Andante \u00e9 o cart\u00e3o usado no metro, autocarros STCP, "
                    "comboios urbanos da CP e MetroBus\\.\n"
                    f"\u2022 Andante Azul \\(ocasional\\): {blue}\n"
                    f"\u2022 Andante Prateado \\(passes\\): {silver}"
                ),
            },
            {
                "heading": "\U0001f5fa Como funcionam as zonas",
                "text": (
                    "As zonas Andante *n\u00e3o* s\u00e3o an\u00e9is numerados\\. T\u00eam nomes "
                    "reais como *PRT1* \\(centro do Porto\\), *VNG1* \\(cais de "
                    "Gaia\\) ou *VCD8* \\(aeroporto\\), e est\u00e3o afixados em "
                    "todas as esta\u00e7\u00f5es\\.\n\n"
                    "*Z2*, *Z3*, *Z4*\\.\\.\\. s\u00e3o nomes de *t\u00edtulo*: o n\u00famero de "
                    "zonas que o t\u00edtulo cobre, contadas a partir de onde "
                    "validas\\. Todos os t\u00edtulos cobrem no m\u00ednimo 2 zonas, "
                    "por isso uma viagem dentro de uma s\u00f3 zona j\u00e1 precisa de "
                    "um *Z2*\\."
                ),
            },
            {
                "heading": "\U0001f4b0 T\u00edtulos ocasionais",
                "text": (
                    _occasional_lines("pt")
                    + "\n\nNa compra de 10 t\u00edtulos recebes 1 gr\u00e1tis\\.\n"
                    + _esc(f"Existem t\u00edtulos acima de Z{max_priced}, mas o pre\u00e7o "
                           "n\u00e3o \u00e9 publicado online — confirma na m\u00e1quina.")
                ),
            },
            {
                "heading": "\U0001f4c5 Andante 24 \\(24h\\)",
                "text": _day_pass_lines(),
            },
            {
                "heading": "\U0001f9f3 Andante Tour \\(turistas\\)",
                "text": (
                    f"\u2022 *Tour 1* — 24h, todas as zonas: {tour1}\n"
                    f"\u2022 *Tour 3* — 72h, todas as zonas: {tour3}\n"
                    + _esc("N\u00e3o \u00e9 v\u00e1lido no Funicular dos Guindais nem no "
                           "El\u00e9trico da STCP.")
                ),
            },
            {
                "heading": "\U0001f4c6 Passes mensais",
                "text": (
                    f"\u2022 *{_esc(labels['3Z'])}*: {monthly_3z}\n"
                    f"\u2022 *{_esc(labels['metropolitano'])}*: {monthly_metro}"
                ),
            },
            {
                "heading": "\U0001f3ea Onde comprar",
                "text": (
                    "\u2022 M\u00e1quinas autom\u00e1ticas em todas as esta\u00e7\u00f5es de metro\n"
                    "\u2022 Lojas Andante \\(Trindade, Casa da M\u00fasica\\)\n"
                    "\u2022 Bilheteiras da CP e agentes Payshop\n"
                    "\u2022 Aeroporto: m\u00e1quinas na entrada do metro"
                ),
            },
            {
                "heading": "\u2708\ufe0f Bilhete do aeroporto",
                "text": (
                    f"O aeroporto est\u00e1 na zona *VCD8*\\. Do centro do Porto "
                    f"precisas de um t\u00edtulo *{_esc(airport_title)}*: "
                    f"*{airport_price}* \\+ {blue} do cart\u00e3o se n\u00e3o tiveres\\."
                ),
            },
            {
                "heading": "\u2705 Verifica\u00e7\u00e3o de pre\u00e7os",
                "text": f"_{verified}_",
            },
        ],
    }


TICKET_INFO = {
    "pt": _build_ticket_info("pt"),
    "en": _build_ticket_info("en"),
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
