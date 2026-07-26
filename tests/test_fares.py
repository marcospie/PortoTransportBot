"""Tests for bot.services.fares -- the single source of truth for prices.

The bug these guard against: the zone calculator and the tourist guide used to
carry their own hardcoded price tables and quoted different amounts for the same
Andante ticket depending on which menu the user came from.
"""

import re

import pytest


# ===================================================================
# The fare tables themselves
# ===================================================================

class TestFareTables:
    def test_occasional_prices_match_published_tariff(self):
        """https://www.metrodoporto.pt/pages/287, in force since 2026-01-01."""
        from bot.services import fares
        assert fares.OCCASIONAL_PRICES == {
            2: 1.40, 3: 1.85, 4: 2.30, 5: 2.80,
            6: 3.25, 7: 3.75, 8: 4.20, 9: 4.65,
        }

    def test_day_pass_prices_match_published_tariff(self):
        from bot.services import fares
        assert fares.DAY_PASS_PRICES == {
            2: 5.35, 3: 6.85, 4: 8.55, 5: 10.25,
            6: 12.20, 7: 13.90, 8: 15.60, 9: 17.30,
        }

    def test_tour_prices(self):
        from bot.services import fares
        assert fares.TOUR_PRICES == {1: 7.75, 3: 16.55}
        assert fares.ANDANTE_TOUR_PRICE == 16.55

    def test_card_prices(self):
        from bot.services import fares
        assert fares.CARD_PRICE_BLUE == 0.60
        assert fares.CARD_PRICE_SILVER == 6.00

    def test_monthly_prices(self):
        from bot.services import fares
        assert fares.MONTHLY_PRICES == {"3Z": 30.00, "metropolitano": 40.00}

    def test_every_priced_title_has_a_duration_and_a_bundle(self):
        from bot.services import fares
        assert set(fares.OCCASIONAL_PRICES) == set(fares.MAX_TRIP_DURATION)
        assert set(fares.OCCASIONAL_PRICES) == set(fares.OCCASIONAL_BUNDLE_PRICES)
        assert set(fares.OCCASIONAL_PRICES) == set(fares.DAY_PASS_PRICES)

    def test_prices_increase_with_zones(self):
        from bot.services import fares
        for table in (fares.OCCASIONAL_PRICES, fares.DAY_PASS_PRICES,
                      fares.OCCASIONAL_BUNDLE_PRICES):
            values = [table[n] for n in sorted(table)]
            assert values == sorted(values)
            assert len(set(values)) == len(values)

    def test_bundle_is_ten_times_the_single_fare(self):
        """"Buy 10, get 1 free" -- the bundle must be exactly 10x."""
        from bot.services import fares
        for n, single in fares.OCCASIONAL_PRICES.items():
            assert fares.OCCASIONAL_BUNDLE_PRICES[n] == pytest.approx(single * 10)

    def test_day_pass_is_never_cheaper_than_a_single(self):
        from bot.services import fares
        for n, single in fares.OCCASIONAL_PRICES.items():
            assert fares.DAY_PASS_PRICES[n] > single


# ===================================================================
# Provenance
# ===================================================================

class TestProvenance:
    def test_last_verified_is_an_iso_date(self):
        from bot.services import fares
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", fares.LAST_VERIFIED)
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", fares.TARIFF_EFFECTIVE_FROM)

    def test_source_urls_are_real_urls(self):
        from bot.services import fares
        assert fares.SOURCE_URL in fares.SOURCE_URLS
        for url in fares.SOURCE_URLS:
            assert url.startswith("https://")

    def test_verified_note_mentions_date_and_source(self):
        from bot.services import fares
        for lang in ("pt", "en"):
            note = fares.verified_note(lang)
            assert fares.LAST_VERIFIED in note
            assert fares.TARIFF_EFFECTIVE_FROM in note
            assert fares.SOURCE_URL in note

    def test_verified_note_differs_per_language(self):
        from bot.services import fares
        assert fares.verified_note("pt") != fares.verified_note("en")


# ===================================================================
# Title arithmetic
# ===================================================================

class TestTitleRules:
    def test_minimum_title_is_z2(self):
        """Every occasional title covers at least 2 zones (andante.pt)."""
        from bot.services import fares
        assert fares.MIN_TITLE_ZONES == 2
        assert fares.title_for_zones(0) == "Z2"
        assert fares.title_for_zones(1) == "Z2"
        assert fares.title_for_zones(2) == "Z2"

    def test_title_tracks_zone_count(self):
        from bot.services import fares
        assert fares.title_for_zones(3) == "Z3"
        assert fares.title_for_zones(9) == "Z9"
        assert fares.title_for_zones(15) == "Z15"

    def test_no_title_beyond_the_largest_sold(self):
        from bot.services import fares
        assert fares.title_for_zones(fares.MAX_TITLE_ZONES) == "Z19"
        assert fares.title_for_zones(fares.MAX_TITLE_ZONES + 1) is None

    def test_title_of_unknown_zone_count(self):
        from bot.services import fares
        assert fares.title_for_zones(None) is None
        assert fares.title_zones(None) is None

    def test_price_for_single_zone_trip_is_the_z2_fare(self):
        from bot.services import fares
        assert fares.get_price(1) == fares.OCCASIONAL_PRICES[2]
        assert fares.get_day_pass_price(1) == fares.DAY_PASS_PRICES[2]

    def test_unpublished_prices_return_none_rather_than_a_guess(self):
        from bot.services import fares
        for zones in (10, 15, 19, 40, None):
            assert fares.get_price(zones) is None
            assert fares.get_day_pass_price(zones) is None
            assert fares.has_published_price(zones) is False

    def test_max_priced_zones_is_consistent_with_the_table(self):
        from bot.services import fares
        assert max(fares.OCCASIONAL_PRICES) == fares.MAX_PRICED_ZONES
        assert fares.has_published_price(fares.MAX_PRICED_ZONES) is True

    def test_helper_lookups(self):
        from bot.services import fares
        assert fares.get_bundle_price(4) == 23.00
        assert fares.get_max_trip_duration(4) == "1h15"
        assert fares.get_tour_price(1) == 7.75
        assert fares.get_tour_price(2) is None
        assert fares.get_monthly_price("3Z") == 30.00
        assert fares.get_monthly_price("nope") is None

    def test_format_price(self):
        from bot.services import fares
        assert fares.format_price(1.4) == "1.40€"
        assert fares.format_price(None) == "?"

    def test_all_prices_snapshot_covers_every_table(self):
        from bot.services import fares
        snapshot = fares.all_prices()
        assert set(snapshot) == {"occasional", "occasional_bundle", "day_pass",
                                "tour", "monthly", "cards"}
        assert snapshot["occasional"] == fares.OCCASIONAL_PRICES


# ===================================================================
# One source of truth: nobody may hardcode a price
# ===================================================================

class TestSingleSourceOfTruth:
    def test_zones_module_reuses_the_fare_tables(self):
        from bot.services import fares
        import bot.services.zones as zones
        assert zones.ZONE_PRICES is fares.OCCASIONAL_PRICES
        assert zones.DAY_PASS_PRICES is fares.DAY_PASS_PRICES
        assert zones.get_price(4) == fares.get_price(4)
        assert zones.get_day_pass_price(4) == fares.get_day_pass_price(4)

    def test_zone_calculator_and_tourist_guide_agree(self):
        """The exact bug: two features, two different prices, same ticket."""
        from bot.services import fares
        from bot.services.tourist import get_ticket_info
        from bot.services.zones import calculate_zones

        result = calculate_zones("Trindade", "Aeroporto")
        assert result["title"] == "Z4"
        assert result["price"] == fares.OCCASIONAL_PRICES[4]

        for lang in ("pt", "en"):
            text = " ".join(s["text"] for s in get_ticket_info(lang)["sections"])
            # The guide quotes the same Z4 fare the calculator just returned.
            assert _has_price(text, result["price"])
            assert not _has_price(text, 1.25)   # old tourist.py Z2 price
            assert not _has_price(text, 1.65)   # old tourist.py Z3 price
            assert not _has_price(text, 2.00)   # old tourist.py Z4 price
            assert not _has_price(text, 1.95)   # old zones.py 2-zone price
            assert not _has_price(text, 5.50)   # old tourist.py day pass
            assert not _has_price(text, 5.80)   # old zones.py day pass
            assert not _has_price(text, 15.30)  # old zones.py all-zones pass

    def test_tourist_guide_lists_every_published_fare(self):
        from bot.services import fares
        from bot.services.tourist import get_ticket_info
        for lang in ("pt", "en"):
            text = " ".join(s["text"] for s in get_ticket_info(lang)["sections"])
            for price in fares.OCCASIONAL_PRICES.values():
                assert _has_price(text, price), (lang, price)
            for price in fares.DAY_PASS_PRICES.values():
                assert _has_price(text, price), (lang, price)
            for price in fares.TOUR_PRICES.values():
                assert _has_price(text, price), (lang, price)

    def test_tourist_guide_shows_the_verification_date(self):
        from bot.services import fares
        from bot.services.tourist import get_ticket_info
        for lang in ("pt", "en"):
            text = " ".join(s["text"] for s in get_ticket_info(lang)["sections"])
            assert fares.LAST_VERIFIED.replace("-", "\\-") in text

    def test_no_module_hardcodes_an_andante_price(self):
        """zones.py / tourist.py must not carry their own price literals."""
        import ast
        import inspect
        from bot.services import tourist
        import bot.services.zones as zones

        stale = ("1.25", "1.65", "1.95", "2.50", "3.05", "5.80", "5.50",
                 "15.30", "€2.00", "4.15")
        for module in (zones, tourist):
            source = inspect.getsource(module)
            # Drop the module docstring and comments: those legitimately
            # describe the old, wrong values.
            tree = ast.parse(source)
            if (tree.body and isinstance(tree.body[0], ast.Expr)
                    and isinstance(tree.body[0].value, ast.Constant)):
                source = "\n".join(
                    source.splitlines()[tree.body[0].end_lineno:])
            code = "\n".join(line for line in source.splitlines()
                             if not line.lstrip().startswith("#"))
            for token in stale:
                assert token not in code, f"{module.__name__} still has {token}"

    def test_tourist_zone_labels_come_from_the_calculator(self):
        """POI "zone" fields are titles computed from official zone data."""
        from bot.services.tourist import TOURIST_POIS
        from bot.services.zones import calculate_zones
        for category in TOURIST_POIS.values():
            for dest in category.get("destinations", []):
                zone = dest["zone"]
                assert re.fullmatch(r"Z\d+", zone), zone
                result = calculate_zones("Trindade", dest["station"])
                if result and result.get("title"):
                    assert zone == result["title"], dest["station"]

    def test_airport_title_is_z4_everywhere(self):
        """Airport = VCD8 = 4 zones from central Porto = Z4 = 2.30 EUR."""
        from bot.services import fares
        from bot.services.tourist import TOURIST_POIS, get_ticket_info
        from bot.services.zones import calculate_zones

        assert calculate_zones("Trindade", "Aeroporto")["title"] == "Z4"
        airport = TOURIST_POIS["airport"]["destinations"][0]
        assert airport["zone"] == "Z4"
        assert _has_price(airport["tip_pt"], fares.OCCASIONAL_PRICES[4],
                          escaped=False)
        assert _has_price(airport["tip_en"], fares.OCCASIONAL_PRICES[4],
                          escaped=False)
        for lang in ("pt", "en"):
            text = " ".join(s["text"] for s in get_ticket_info(lang)["sections"])
            assert "VCD8" in text


def _has_price(text: str, value: float, escaped: bool = True) -> bool:
    """Is this euro amount present, allowing for MarkdownV2 escaping?"""
    plain = f"{value:.2f}"
    if escaped:
        return plain.replace(".", "\\.") in text or plain in text
    return plain in text
