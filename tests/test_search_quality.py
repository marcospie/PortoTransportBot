"""Search quality: typo tolerance, aliases, and the bounded cache.

The existing ~70 real-world search variations live in
``tests/test_comprehensive.py`` and must all keep passing; this file covers the
cases that used to score exactly ZERO:

* a single-letter typo that is not a substring ("Trinidade", "Bulhao"),
* abbreviations users actually type ("est.", "hosp.", "aerop."),
* English/tourist phrasings ("airport", "oporto", "São Bento station",
  "dragon stadium").

It also pins the *negative* side: junk must still resolve to nothing, because
sending someone to the wrong station is worse than finding none.
"""

import time

import pytest

from bot.utils.cache import CLEANUP_INTERVAL, DEFAULT_MAX_SIZE, TTLCache
from bot.utils.search import (
    expand_query_aliases,
    fuzzy_search,
    match_score,
    normalize,
    normalize_simple,
    typo_score,
)
from bot.services.metro import STATIONS, search_stations


def _names(query):
    return [r["name"] for r in search_stations(query)]


# ===================================================================
# 1. Typo tolerance
# ===================================================================

class TestTypoTolerance:

    TYPO_CASES = [
        # (what the user typed, what they meant)
        ("Trinidade", "Trindade"),
        ("trinidade", "Trindade"),
        ("Trindadde", "Trindade"),
        ("Bulhao", "Bolhão"),
        ("bulhão", "Bolhão"),
        ("Aliadso", "Aliados"),
        ("marqes", "Marquês"),
        ("Campanhaa", "Campanhã"),
        ("Fanzers", "Fânzeres"),
        ("Matosinos", "Senhor de Matosinhos"),
    ]

    @pytest.mark.parametrize("query,expected", TYPO_CASES)
    def test_typo_finds_station(self, query, expected):
        names = _names(query)
        assert expected in names, (
            f"Typo {query!r} should still find {expected!r}, got {names[:5]}")

    @pytest.mark.parametrize("query,expected", TYPO_CASES)
    def test_typo_score_is_positive(self, query, expected):
        assert match_score(query, expected) > 0

    def test_typo_score_clears_the_detail_lookup_threshold(self):
        """Services resolve a single station with min_score=40."""
        for query, expected in self.TYPO_CASES:
            assert match_score(query, expected) >= 40, (
                f"{query!r} -> {expected!r} scores too low to resolve")

    def test_typo_tolerance_can_be_disabled(self):
        assert match_score("Trinidade", "Trindade", fuzzy=False) == 0
        assert match_score("Trinidade", "Trindade", fuzzy=True) > 0

    def test_typo_is_only_a_secondary_signal(self):
        """A query that already matched keeps exactly its previous score."""
        for query, name in [("trindade", "Trindade"), ("trin", "Trindade"),
                            ("bolhao", "Bolhão"), ("casa musica", "Casa da Música"),
                            ("d joao 2", "D. João II")]:
            assert match_score(query, name, fuzzy=True) == \
                   match_score(query, name, fuzzy=False)

    def test_departures_resolve_a_misspelled_station(self):
        from bot.services.metro import get_station_lines
        assert get_station_lines("Trinidade")


class TestTypoScoreDirectly:

    def test_returns_zero_for_junk(self):
        assert typo_score("xyzqwerty123", "Trindade") == 0.0

    def test_returns_zero_for_short_queries(self):
        # Two characters cannot be judged a typo of anything.
        assert typo_score("ab", "Aliados") == 0.0

    def test_returns_zero_for_a_genuinely_different_word(self):
        assert typo_score("Aeroporto", "Trindade") == 0.0

    def test_is_capped(self):
        assert typo_score("Trindadee", "Trindade") <= 70.0

    def test_one_lucky_word_out_of_many_is_not_a_match(self):
        """Coverage scaling: matching 1 of 4 words must not look like a hit."""
        assert typo_score("hospitl zzzz yyyy wwww", "Hospital de São João") == 0.0


# ===================================================================
# 2. Junk must stay junk
# ===================================================================

class TestNoFalsePositives:

    JUNK = [
        "xyzqwerty123", "zzzzzzzz", "12345678", "qqqqqqqqqq",
        "asdfghjkl", "%%%%%%", "aaaaaaaaaaaaaaaaaaaa",
    ]

    @pytest.mark.parametrize("query", JUNK)
    def test_junk_finds_nothing(self, query):
        assert search_stations(query) == [], f"{query!r} should match nothing"

    def test_empty_query(self):
        assert search_stations("") == []
        assert search_stations("   ") == []

    def test_very_long_query_does_not_crash(self):
        assert isinstance(search_stations("a" * 500), list)

    def test_unrelated_real_words_do_not_match(self):
        for query in ("lisboa", "madrid", "helsinki"):
            names = _names(query)
            assert "Trindade" not in names
            assert "Bolhão" not in names


# ===================================================================
# 3. Abbreviations
# ===================================================================

class TestAbbreviations:

    CASES = [
        ("est. sao bento", "São Bento"),
        ("hosp. sao joao", "Hospital de São João"),
        ("hosp sao joao", "Hospital de São João"),
        ("hosp santos silva", "Hospital Santos Silva"),
        ("aerop.", "Aeroporto"),
        ("aerop", "Aeroporto"),
        ("sto ovidio", "Santo Ovídio"),
        ("sra hora", "Senhora da Hora"),
        ("polo univ", "Polo Universitário"),
    ]

    @pytest.mark.parametrize("query,expected", CASES)
    def test_abbreviation_resolves(self, query, expected):
        names = _names(query)
        assert expected in names, f"{query!r} should find {expected!r}, got {names[:5]}"

    def test_new_abbreviations_are_registered(self):
        from bot.utils.search import _ABBREVIATIONS
        for abbr in ("est.", "hosp.", "aerop."):
            assert abbr in _ABBREVIATIONS

    def test_hospital_abbreviation_expands_in_normalize(self):
        assert "hospital" in normalize("hosp. de sao joao")

    def test_normalize_still_handles_previous_cases(self):
        n = normalize("D. João II")
        assert "dom" in n and "2" in n
        assert "joao" in normalize("João")


# ===================================================================
# 4. English / tourist aliases
# ===================================================================

class TestTouristAliases:

    CASES = [
        ("airport", "Aeroporto"),
        ("Airport", "Aeroporto"),
        ("the airport", "Aeroporto"),
        ("dragon stadium", "Estádio do Dragão"),
        ("Dragon Stadium", "Estádio do Dragão"),
        ("São Bento station", "São Bento"),
        ("sao bento station", "São Bento"),
        ("Trindade metro station", "Trindade"),
        ("bolhao stop", "Bolhão"),
        ("house of music", "Casa da Música"),
        ("music house", "Casa da Música"),
        ("city center", "Aliados"),
        ("downtown", "Aliados"),
    ]

    @pytest.mark.parametrize("query,expected", CASES)
    def test_alias_resolves(self, query, expected):
        names = _names(query)
        assert expected in names, f"{query!r} should find {expected!r}, got {names[:5]}"

    def test_oporto_finds_porto_named_places(self):
        """Tourists write "Oporto"; it must lead somewhere Porto-related."""
        assert search_stations("oporto")

    def test_expand_query_aliases_examples(self):
        assert expand_query_aliases("airport") == "aeroporto"
        assert expand_query_aliases("São Bento station") == "sao bento"
        assert expand_query_aliases("dragon stadium") == "estadio do dragao"

    def test_stopwords_never_empty_the_query(self):
        # "station" on its own must not become an empty query (which would
        # otherwise match everything or crash).
        assert expand_query_aliases("station") == "station"

    def test_alias_does_not_fire_inside_a_word(self):
        """"airport" must not be substituted inside e.g. "fairporto"."""
        assert "aeroporto" not in expand_query_aliases("fairportos")

    def test_portuguese_queries_are_unaffected_by_aliases(self):
        assert expand_query_aliases("Casa da Música") == "casa da musica"
        assert expand_query_aliases("Estádio do Dragão") == "estadio do dragao"


# ===================================================================
# 5. No regression on the primary scorer
# ===================================================================

class TestPrimaryScorerUnchanged:

    def test_exact_match_is_100(self):
        assert match_score("Trindade", "Trindade") == 100

    def test_substring_scores_high(self):
        assert match_score("trin", "Trindade") >= 70

    def test_accent_free_match(self):
        assert match_score("bolhao", "Bolhão") >= 70

    def test_no_match_is_exactly_zero(self):
        assert match_score("xyz123", "Trindade") == 0

    def test_normalize_simple_strips_punctuation(self):
        assert normalize_simple("Vila d'Este") == "vila deste"

    def test_fuzzy_search_respects_min_score(self):
        results = fuzzy_search("trindade", list(STATIONS), min_score=99)
        assert [n for n, _ in results] == ["Trindade"]

    def test_fuzzy_search_respects_max_results(self):
        assert len(fuzzy_search("a", list(STATIONS), min_score=1,
                                max_results=3)) <= 3

    def test_results_are_sorted_by_score(self):
        scores = [s for _, s in fuzzy_search("bolhao", list(STATIONS))]
        assert scores == sorted(scores, reverse=True)


class TestSearchIsFastEnough:
    """Typo tolerance must not make a junk query pathologically slow."""

    def test_junk_query_over_all_stations_is_quick(self):
        start = time.monotonic()
        for _ in range(20):
            search_stations("xyzqwerty123")
        assert time.monotonic() - start < 2.0


# ===================================================================
# 6. Bounded cache
# ===================================================================

class TestTTLCacheBackwardCompatible:

    def test_default_constructor(self):
        cache = TTLCache()
        cache.set("k", "v")
        assert cache.get("k") == "v"

    def test_default_ttl_keyword(self):
        cache = TTLCache(default_ttl=300)
        cache.set("k", 1)
        assert cache.get("k") == 1

    def test_missing_key_returns_none(self):
        assert TTLCache().get("nope") is None

    def test_explicit_ttl_expires(self):
        cache = TTLCache(default_ttl=300)
        cache.set("k", "v", ttl=-1)
        assert cache.get("k") is None

    def test_clear(self):
        cache = TTLCache()
        cache.set("a", 1)
        cache.clear()
        assert cache.get("a") is None
        assert len(cache) == 0

    def test_cleanup_is_still_callable(self):
        cache = TTLCache()
        cache.set("live", 1, ttl=300)
        cache.set("dead", 1, ttl=-1)
        cache.cleanup()
        assert len(cache) == 1
        assert cache.get("live") == 1

    def test_services_construct_it_the_same_way(self):
        """Services build TTLCache(default_ttl=N) — keep that working."""
        from bot.services import alerts, stcp
        for module in (alerts, stcp):
            assert isinstance(module._cache, TTLCache)
            assert module._cache.max_size > 0


class TestTTLCacheIsBounded:

    def test_never_exceeds_max_size(self):
        cache = TTLCache(default_ttl=300, max_size=10)
        for i in range(1000):
            cache.set(f"k{i}", i)
        assert len(cache) <= 10

    def test_evicts_least_recently_used(self):
        cache = TTLCache(default_ttl=300, max_size=3)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        cache.get("a")          # "a" is now the most recently used
        cache.set("d", 4)       # must evict "b", the coldest entry
        assert cache.get("a") == 1
        assert cache.get("b") is None
        assert cache.get("d") == 4

    def test_eviction_counter_increases(self):
        cache = TTLCache(default_ttl=300, max_size=2)
        for i in range(10):
            cache.set(f"k{i}", i)
        assert cache.evictions >= 8

    def test_expired_entries_are_dropped_before_live_ones(self):
        cache = TTLCache(default_ttl=300, max_size=3)
        cache.set("stale", 1, ttl=-1)
        cache.set("live1", 1)
        cache.set("live2", 2)
        cache._last_cleanup -= CLEANUP_INTERVAL + 1  # allow a sweep
        cache.set("live3", 3)
        assert cache.get("live1") == 1
        assert cache.get("live2") == 2
        assert cache.get("live3") == 3

    def test_overwriting_a_key_does_not_grow_the_cache(self):
        cache = TTLCache(default_ttl=300, max_size=5)
        for _ in range(100):
            cache.set("same", 1)
        assert len(cache) == 1

    def test_max_size_is_clamped_to_at_least_one(self):
        cache = TTLCache(default_ttl=300, max_size=0)
        cache.set("a", 1)
        assert cache.max_size == 1
        assert len(cache) <= 1

    def test_default_max_size_is_finite(self):
        assert 0 < DEFAULT_MAX_SIZE < 100_000
        assert TTLCache().max_size == DEFAULT_MAX_SIZE

    def test_expiry_sweep_happens_without_manual_cleanup(self):
        """The leak: cleanup() was never called from anywhere."""
        cache = TTLCache(default_ttl=300, max_size=1000)
        for i in range(50):
            cache.set(f"dead{i}", i, ttl=-1)
        cache._last_cleanup -= CLEANUP_INTERVAL + 1
        cache.set("trigger", 1)
        assert len(cache) < 51

    def test_contains_is_ttl_aware(self):
        cache = TTLCache(default_ttl=300)
        cache.set("live", 1)
        cache.set("dead", 1, ttl=-1)
        assert "live" in cache
        assert "dead" not in cache

    def test_realistic_per_stop_key_growth_is_bounded(self):
        """Simulate a long-running bot caching one key per stop lookup."""
        cache = TTLCache(default_ttl=60, max_size=DEFAULT_MAX_SIZE)
        for i in range(DEFAULT_MAX_SIZE * 5):
            cache.set(f"stop:{i}", {"arrivals": []})
        assert len(cache) <= DEFAULT_MAX_SIZE
