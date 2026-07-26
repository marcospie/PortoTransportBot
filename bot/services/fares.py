"""Andante fares -- the single source of truth for every price in the bot.

Nothing else in the code base may hard-code an Andante price.  Both the zone
calculator (:mod:`bot.services.zones`) and the tourist guide
(:mod:`bot.services.tourist`) read their numbers from here, so the two features
can never quote different prices for the same ticket again.

How Andante pricing actually works
----------------------------------
An Andante *title* is named ``Z<n>`` where ``n`` is the number of zone **rings**
it covers, counted outwards from the zone in which you first validate.  Quoting
andante.pt: *"São válidos para um conjunto de anéis de zonas que se contam à
volta da zona onde começou a sua viagem [...] Z2 se forem 2 anéis, Z3 se forem
3 anéis, ... Todos os títulos ocasionais são válidos para um mínimo de 2
zonas."*

Two consequences that the bot used to get wrong:

* ``Z2`` is **not** "zone number 2" and it is **not** "1 zone".  It is the
  cheapest title and it already covers 2 rings, so a trip inside a single zone
  still costs the ``Z2`` fare.
* Zone *names* are things like ``PRT1``, ``VNG1``, ``MTS1`` -- never ``Z2``.
  See :mod:`bot.services.zones`.

Sources (all fetched and cross-checked on the LAST_VERIFIED date below)
----------------------------------------------------------------------
* https://www.metrodoporto.pt/pages/287 -- "Preço": occasional + Andante 24
  tables, Andante Tour, card costs.  States *"Tarifário em vigor a partir do dia
  1 de Janeiro de 2026"*.
* https://andante.pt/comprar/andante-azul/ -- identical occasional / 24h table,
  *"Valores em Euros e com IVA incluído à taxa legal em vigor desde 1 de janeiro
  de 2026"*.
* https://andante.pt/comprar/andante-tour/ -- Andante Tour 1 / Tour 3.
* https://andante.pt/titulos-ocasionais/ -- maximum trip duration per title and
  the "minimum 2 zones" rule.
* https://www.metrodoporto.pt/assets/metrodoporto/metroporto/javascripts/\
metro_viajar_fares-v202601-63159a6437.min.js -- machine-readable copy of the
  2026-01 occasional table (agrees exactly) plus the monthly pass values.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Provenance -- surface these in user-facing output so stale prices are visible
# ---------------------------------------------------------------------------

#: Date on which a human/agent last checked these numbers against the sources.
LAST_VERIFIED = "2026-07-26"

#: Date from which the operator says this tariff is in force.
TARIFF_EFFECTIVE_FROM = "2026-01-01"

#: Primary citable source for the numbers in this module.
SOURCE_URL = "https://www.metrodoporto.pt/pages/287"

#: Every source consulted, in order of authority.
SOURCE_URLS: tuple[str, ...] = (
    "https://www.metrodoporto.pt/pages/287",
    "https://andante.pt/comprar/andante-azul/",
    "https://andante.pt/comprar/andante-tour/",
    "https://andante.pt/titulos-ocasionais/",
)

# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------

#: "Andante Azul" -- non-personalised paper card for occasional travel.
CARD_PRICE_BLUE = 0.60

#: "Andante Azul" is also the card the Andante 24 loads onto.
CARD_PRICE_DAY_PASS = 0.60

#: "Andante Prateado" -- personalised card (photo + name) needed for passes.
CARD_PRICE_SILVER = 6.00

# ---------------------------------------------------------------------------
# Title numbering
# ---------------------------------------------------------------------------

#: Cheapest title available: every occasional title covers at least 2 zones.
MIN_TITLE_ZONES = 2

#: Highest title the operator sells (the zone map offers Z2..Z19).
MAX_TITLE_ZONES = 19

#: Highest title with a *published* price.  Z10..Z19 exist but the operator
#: does not publish their price on any page we can read, so we must not invent
#: one -- :func:`get_price` returns ``None`` above this.
MAX_PRICED_ZONES = 9

# ---------------------------------------------------------------------------
# Occasional titles ("Viagem Ocasional Simples" / Andante Azul)
# ---------------------------------------------------------------------------

#: title zone-count -> single-journey price in EUR.
OCCASIONAL_PRICES: dict[int, float] = {
    2: 1.40,
    3: 1.85,
    4: 2.30,
    5: 2.80,
    6: 3.25,
    7: 3.75,
    8: 4.20,
    9: 4.65,
}

#: title zone-count -> price of a "10+1" bundle (buy 10, get 1 free).
OCCASIONAL_BUNDLE_PRICES: dict[int, float] = {
    2: 14.00,
    3: 18.50,
    4: 23.00,
    5: 28.00,
    6: 32.50,
    7: 37.50,
    8: 42.00,
    9: 46.50,
}

#: Number of journeys in a "10+1" bundle.
BUNDLE_SIZE = 11

#: title zone-count -> maximum trip duration after the first validation.
MAX_TRIP_DURATION: dict[int, str] = {
    2: "1h00",
    3: "1h00",
    4: "1h15",
    5: "1h30",
    6: "1h45",
    7: "2h00",
    8: "2h15",
    9: "2h30",
}

# ---------------------------------------------------------------------------
# Andante 24 (24 consecutive hours in the purchased zones)
# ---------------------------------------------------------------------------

#: title zone-count -> Andante 24 price in EUR.
DAY_PASS_PRICES: dict[int, float] = {
    2: 5.35,
    3: 6.85,
    4: 8.55,
    5: 10.25,
    6: 12.20,
    7: 13.90,
    8: 15.60,
    9: 17.30,
}

DAY_PASS_DURATION_HOURS = 24

# ---------------------------------------------------------------------------
# Andante Tour (tourist passes, valid on the whole intermodal network)
# ---------------------------------------------------------------------------

#: number of days -> price in EUR.
TOUR_PRICES: dict[int, float] = {
    1: 7.75,
    3: 16.55,
}

ANDANTE_TOUR_1_PRICE = TOUR_PRICES[1]
ANDANTE_TOUR_3_PRICE = TOUR_PRICES[3]

#: Backwards-compatible alias -- historically this name meant the 3-day pass.
ANDANTE_TOUR_PRICE = ANDANTE_TOUR_3_PRICE

TOUR_DURATION_HOURS: dict[int, int] = {1: 24, 3: 72}

#: The Tour passes are not accepted on these two heritage services.
TOUR_EXCLUSIONS = ("Funicular dos Guindais", "Elétrico STCP")

# ---------------------------------------------------------------------------
# Monthly passes ("Assinatura Mensal", loaded on an Andante Prateado card)
# ---------------------------------------------------------------------------

#: pass key -> monthly price in EUR.
MONTHLY_PRICES: dict[str, float] = {
    "3Z": 30.00,            # any 3 contiguous zones
    "metropolitano": 40.00,  # every zone in the Área Metropolitana do Porto
}

#: Human labels for the monthly passes, per language.
MONTHLY_LABELS: dict[str, dict[str, str]] = {
    "pt": {"3Z": "Andante 3 Zonas", "metropolitano": "Andante Metropolitano"},
    "en": {"3Z": "Andante 3 Zones", "metropolitano": "Andante Metropolitan"},
}


# ---------------------------------------------------------------------------
# Title / price helpers
# ---------------------------------------------------------------------------

def title_zones(num_zones: int | None) -> int | None:
    """Return the zone-count of the title needed to cross ``num_zones`` zones.

    Applies the official minimum of 2 zones, so a trip that never leaves one
    zone still needs a ``Z2``.  Returns ``None`` when ``num_zones`` is unknown
    or beyond the largest title the operator sells.
    """
    if num_zones is None:
        return None
    n = max(MIN_TITLE_ZONES, int(num_zones))
    if n > MAX_TITLE_ZONES:
        return None
    return n


def title_for_zones(num_zones: int | None) -> str | None:
    """Return the title name (``"Z2"``, ``"Z4"``, ...) for a zone count."""
    n = title_zones(num_zones)
    return None if n is None else f"Z{n}"


def get_price(num_zones: int | None) -> float | None:
    """Single-journey price for a trip crossing ``num_zones`` zones.

    Returns ``None`` when no price is published for the required title (Z10 and
    above) -- callers must say so rather than show a made-up number.
    """
    n = title_zones(num_zones)
    return None if n is None else OCCASIONAL_PRICES.get(n)


def get_day_pass_price(num_zones: int | None) -> float | None:
    """Andante 24 price for a trip crossing ``num_zones`` zones."""
    n = title_zones(num_zones)
    return None if n is None else DAY_PASS_PRICES.get(n)


def get_bundle_price(num_zones: int | None) -> float | None:
    """Price of a 10+1 bundle of the title needed for ``num_zones`` zones."""
    n = title_zones(num_zones)
    return None if n is None else OCCASIONAL_BUNDLE_PRICES.get(n)


def get_max_trip_duration(num_zones: int | None) -> str | None:
    """Maximum trip duration of the title needed for ``num_zones`` zones."""
    n = title_zones(num_zones)
    return None if n is None else MAX_TRIP_DURATION.get(n)


def get_tour_price(days: int) -> float | None:
    """Price of the Andante Tour pass valid for ``days`` days."""
    return TOUR_PRICES.get(int(days))


def get_monthly_price(kind: str = "3Z") -> float | None:
    """Price of a monthly pass (``"3Z"`` or ``"metropolitano"``)."""
    return MONTHLY_PRICES.get(kind)


def has_published_price(num_zones: int | None) -> bool:
    """True when we can quote a real, sourced price for this zone count."""
    return get_price(num_zones) is not None


def format_price(value: float | None, lang: str = "pt") -> str:
    """Format a price for display, or a clear placeholder when unknown."""
    if value is None:
        return "?" if lang != "pt" else "?"
    return f"{value:.2f}€"


def verified_note(lang: str = "pt") -> str:
    """Plain-text "prices verified on <date>" line for user-facing output.

    Returned unescaped -- escape it yourself before putting it in MarkdownV2.
    """
    if lang == "en":
        return (
            f"Fares in force since {TARIFF_EFFECTIVE_FROM} — "
            f"checked on {LAST_VERIFIED} at {SOURCE_URL}"
        )
    return (
        f"Tarifário em vigor desde {TARIFF_EFFECTIVE_FROM} — "
        f"verificado a {LAST_VERIFIED} em {SOURCE_URL}"
    )


def all_prices() -> dict[str, dict]:
    """Every fare table in one structure (handy for tests and debugging)."""
    return {
        "occasional": dict(OCCASIONAL_PRICES),
        "occasional_bundle": dict(OCCASIONAL_BUNDLE_PRICES),
        "day_pass": dict(DAY_PASS_PRICES),
        "tour": dict(TOUR_PRICES),
        "monthly": dict(MONTHLY_PRICES),
        "cards": {
            "blue": CARD_PRICE_BLUE,
            "silver": CARD_PRICE_SILVER,
        },
    }
