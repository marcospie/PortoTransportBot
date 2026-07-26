"""Tests for real CP departures, the fallback chain and CP data quality.

CP departures used to be pure fiction: the service synthesised a departure at a
precise minute from a guessed frequency anchored to the top of the hour, and
emitted *both* terminal destinations for every slot.  They now come from CP's
own GTFS timetable via the MOTIS API, and the frequency estimate is only a
clearly-labelled last resort.

Every network call is mocked -- these tests never touch the network.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.services import cp


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clear_cp_cache():
    cp._cache.clear()
    yield
    cp._cache.clear()


def _stop_time(headsign="Aveiro", departure="2026-07-26T14:10:00Z",
               route="Linha de Aveiro", agency="CP - Comboios de Portugal",
               agency_id="1094_CP", trip="15737", direction_id="0",
               cancelled=False, realtime=False):
    return {
        "place": {
            "name": "Porto Campanha",
            "stopId": "pt-Comboios-de-Portugal(CP)_94_2006",
            "departure": departure,
            "scheduledDeparture": departure,
        },
        "mode": "METRO",
        "realTime": realtime,
        "headsign": headsign,
        "agencyId": agency_id,
        "agencyName": agency,
        "routeShortName": route,
        "tripShortName": trip,
        "directionId": direction_id,
        "cancelled": cancelled,
        "tripCancelled": False,
    }


# A realistic MOTIS payload for Porto-Campanhã (shape verified against the live
# endpoint on 2026-07-26), covering both directions of two lines.
SAMPLE_STOP_TIMES = [
    _stop_time("Aveiro", "2026-07-26T14:10:00Z", "Linha de Aveiro", trip="15737"),
    _stop_time("Porto Sao Bento", "2026-07-26T14:25:00Z", "Linha de Aveiro",
               trip="15633", direction_id="1"),
    _stop_time("Marco de Canaveses", "2026-07-26T14:35:00Z", "Linha do Marco",
               trip="15533"),
    _stop_time("Porto Sao Bento", "2026-07-26T14:31:00Z", "Linha do Marco",
               trip="15532", direction_id="1"),
    _stop_time("Regua", "2026-07-26T14:25:00Z", "IR", trip="871"),
]

def _now():
    from datetime import datetime, timezone
    return datetime(2026, 7, 26, 14, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Parsing the real source
# ---------------------------------------------------------------------------

class TestParseStoptimes:
    def test_parses_real_payload(self):
        deps = cp._parse_stoptimes(SAMPLE_STOP_TIMES, now=_now())
        assert len(deps) == 5
        for dep in deps:
            assert dep["estimated"] is False
            assert dep["scheduled"] is True
            assert "direction" in dep and dep["direction"]
            assert "time" in dep and dep["time"]
            assert "line" in dep and dep["line"]

    def test_sorted_by_time(self):
        deps = cp._parse_stoptimes(SAMPLE_STOP_TIMES, now=_now())
        minutes = [d["minutes"] for d in deps]
        assert minutes == sorted(minutes)

    def test_uses_real_headsign_for_direction(self):
        deps = cp._parse_stoptimes(SAMPLE_STOP_TIMES, now=_now())
        directions = {d["direction"] for d in deps}
        # Headsigns are accent-normalised in CP's feed; we restore ours.
        assert "Aveiro" in directions
        assert "Porto-São Bento" in directions
        assert "Marco de Canaveses" in directions

    def test_both_directions_present(self):
        """Real data gives both ways of a line, not guessed route endpoints."""
        deps = cp._parse_stoptimes(SAMPLE_STOP_TIMES, line_id="aveiro",
                                   now=_now())
        directions = {d["direction"] for d in deps}
        assert directions == {"Aveiro", "Porto-São Bento"}

    def test_maps_line_id_and_label(self):
        deps = cp._parse_stoptimes(SAMPLE_STOP_TIMES, now=_now())
        by_trip = {d["train"]: d for d in deps}
        assert by_trip["15737"]["line_id"] == "aveiro"
        assert "Linha de Aveiro" in by_trip["15737"]["line"]
        assert by_trip["15533"]["line_id"] == "marco"

    def test_long_distance_service_label(self):
        deps = cp._parse_stoptimes(SAMPLE_STOP_TIMES, now=_now())
        ir = [d for d in deps if d["train"] == "871"][0]
        assert ir["line_id"] == ""
        assert "Inter-Regional" in ir["line"]

    def test_line_filter(self):
        deps = cp._parse_stoptimes(SAMPLE_STOP_TIMES, line_id="marco",
                                   now=_now())
        assert deps
        assert all(d["line_id"] == "marco" for d in deps)

    def test_relative_minutes_for_near_departures(self):
        deps = cp._parse_stoptimes(
            [_stop_time("Aveiro", "2026-07-26T14:07:00Z")], now=_now())
        assert deps[0]["time"] == "7 min"
        assert deps[0]["minutes"] == 7

    def test_sub_minute_departure(self):
        deps = cp._parse_stoptimes(
            [_stop_time("Aveiro", "2026-07-26T14:00:20Z")], now=_now())
        assert deps[0]["time"] == "< 1 min"

    def test_past_departures_dropped(self):
        deps = cp._parse_stoptimes(
            [_stop_time("Aveiro", "2026-07-26T13:30:00Z")], now=_now())
        assert deps == []

    def test_non_cp_agency_dropped(self):
        deps = cp._parse_stoptimes(
            [_stop_time("Vigo-Guixar", route="TRENCELTA 00421",
                        agency="RENFE OPERADORA", agency_id="1071")],
            now=_now())
        assert deps == []

    def test_cancelled_dropped(self):
        deps = cp._parse_stoptimes(
            [_stop_time("Aveiro", cancelled=True)], now=_now())
        assert deps == []

    def test_malformed_entries_ignored(self):
        deps = cp._parse_stoptimes(
            ["nonsense", None, {}, {"place": {}}, {"place": {"departure": "x"}}],
            now=_now())
        assert deps == []

    def test_realtime_flag_passed_through(self):
        deps = cp._parse_stoptimes(
            [_stop_time("Aveiro", realtime=True)], now=_now())
        assert deps[0]["realtime"] is True


# ---------------------------------------------------------------------------
# The fetch layer
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status = status
        self._payload = payload if payload is not None else {}

    async def json(self, content_type=None):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeSession:
    def __init__(self, response, recorder=None):
        self._response = response
        self._recorder = recorder

    def get(self, url, params=None):
        if self._recorder is not None:
            self._recorder.append((url, params))
        return self._response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class TestFetchStoptimes:
    @pytest.mark.asyncio
    async def test_successful_fetch(self):
        calls = []
        session = _FakeSession(
            _FakeResponse(200, {"stopTimes": SAMPLE_STOP_TIMES}), calls)
        with patch("bot.services.cp.aiohttp.ClientSession",
                   return_value=session):
            out = await cp._fetch_stoptimes("stop-1", count=5)
        assert out == SAMPLE_STOP_TIMES
        url, params = calls[0]
        assert url == cp.MOTIS_STOPTIMES_URL
        assert params["stopId"] == "stop-1"
        assert params["n"] == "5"
        assert params["time"].endswith("Z")

    @pytest.mark.asyncio
    async def test_http_error_returns_empty(self):
        session = _FakeSession(_FakeResponse(503, {}))
        with patch("bot.services.cp.aiohttp.ClientSession",
                   return_value=session):
            assert await cp._fetch_stoptimes("stop-1") == []

    @pytest.mark.asyncio
    async def test_exception_returns_empty(self):
        with patch("bot.services.cp.aiohttp.ClientSession",
                   side_effect=OSError("network down")):
            assert await cp._fetch_stoptimes("stop-1") == []

    @pytest.mark.asyncio
    async def test_unexpected_payload_returns_empty(self):
        session = _FakeSession(_FakeResponse(200, ["not", "a", "dict"]))
        with patch("bot.services.cp.aiohttp.ClientSession",
                   return_value=session):
            assert await cp._fetch_stoptimes("stop-1") == []


class TestGeocodeStopId:
    @pytest.mark.asyncio
    async def test_finds_cp_stop(self):
        payload = [
            {"type": "PLACE", "id": "node/[1]", "name": "Whatever"},
            {"type": "STOP", "id": "es-RENFE_94346", "name": "Porto Campanha"},
            {"type": "STOP", "id": "pt-Comboios-de-Portugal(CP)_94_2006",
             "name": "Porto Campanha"},
        ]
        session = _FakeSession(_FakeResponse(200, payload))
        with patch("bot.services.cp.aiohttp.ClientSession",
                   return_value=session):
            got = await cp._geocode_stop_id("Porto-Campanha")
        assert got == "pt-Comboios-de-Portugal(CP)_94_2006"

    @pytest.mark.asyncio
    async def test_no_cp_stop_returns_none_and_caches(self):
        session = _FakeSession(_FakeResponse(200, []))
        with patch("bot.services.cp.aiohttp.ClientSession",
                   return_value=session) as mock_session:
            assert await cp._geocode_stop_id("São Félix da Marinha") is None
            # Second call must be served from cache (no extra request).
            assert await cp._geocode_stop_id("São Félix da Marinha") is None
            assert mock_session.call_count == 1

    @pytest.mark.asyncio
    async def test_http_error_returns_none(self):
        session = _FakeSession(_FakeResponse(403, []))
        with patch("bot.services.cp.aiohttp.ClientSession",
                   return_value=session):
            assert await cp._geocode_stop_id("Ermesinde") is None


# ---------------------------------------------------------------------------
# get_realtime_departures / the fallback chain
# ---------------------------------------------------------------------------

class TestRealtimeDepartures:
    @pytest.mark.asyncio
    async def test_returns_real_departures(self):
        with patch("bot.services.cp._fetch_stoptimes",
                   new_callable=AsyncMock, return_value=SAMPLE_STOP_TIMES):
            deps = await cp.get_realtime_departures("Porto-Campanha", count=6)
        assert deps
        assert all(d["estimated"] is False for d in deps)

    @pytest.mark.asyncio
    async def test_unknown_station_returns_empty(self):
        with patch("bot.services.cp._fetch_stoptimes",
                   new_callable=AsyncMock, return_value=SAMPLE_STOP_TIMES):
            assert await cp.get_realtime_departures("Nowhere XYZ 123") == []

    @pytest.mark.asyncio
    async def test_alias_resolves_to_real_stop_id(self):
        fetch = AsyncMock(return_value=SAMPLE_STOP_TIMES)
        with patch("bot.services.cp._fetch_stoptimes", fetch):
            deps = await cp.get_realtime_departures("Porto-Campanhã")
        assert deps
        assert fetch.await_args[0][0] == cp.MOTIS_STOP_IDS["Porto-Campanha"]

    @pytest.mark.asyncio
    async def test_geocode_used_when_no_static_stop_id(self):
        fetch = AsyncMock(return_value=SAMPLE_STOP_TIMES)
        geocode = AsyncMock(return_value="pt-Comboios-de-Portugal(CP)_94_39057")
        with patch("bot.services.cp._fetch_stoptimes", fetch), \
             patch("bot.services.cp._geocode_stop_id", geocode):
            deps = await cp.get_realtime_departures("São Félix da Marinha")
        geocode.assert_awaited_once()
        assert deps

    @pytest.mark.asyncio
    async def test_no_stop_id_anywhere_returns_empty(self):
        with patch("bot.services.cp._geocode_stop_id",
                   new_callable=AsyncMock, return_value=None), \
             patch("bot.services.cp._fetch_stoptimes",
                   new_callable=AsyncMock, return_value=[]) as fetch:
            assert await cp.get_realtime_departures("São Félix da Marinha") == []
            fetch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_results_are_cached(self):
        fetch = AsyncMock(return_value=SAMPLE_STOP_TIMES)
        with patch("bot.services.cp._fetch_stoptimes", fetch):
            first = await cp.get_realtime_departures("Porto-Campanha")
            second = await cp.get_realtime_departures("Porto-Campanha")
        assert first == second
        assert fetch.await_count == 1

    @pytest.mark.asyncio
    async def test_empty_source_not_cached(self):
        fetch = AsyncMock(return_value=[])
        with patch("bot.services.cp._fetch_stoptimes", fetch):
            await cp.get_realtime_departures("Porto-Campanha")
            await cp.get_realtime_departures("Porto-Campanha")
        assert fetch.await_count == 2

    @pytest.mark.asyncio
    async def test_count_is_respected_and_directions_kept(self):
        with patch("bot.services.cp._fetch_stoptimes",
                   new_callable=AsyncMock, return_value=SAMPLE_STOP_TIMES):
            deps = await cp.get_realtime_departures("Porto-Campanha", count=2)
        assert len(deps) == 2
        assert len({d["direction"] for d in deps}) == 2


class TestFallbackChain:
    @pytest.mark.asyncio
    async def test_prefers_real_data(self):
        with patch("bot.services.cp._fetch_stoptimes",
                   new_callable=AsyncMock, return_value=SAMPLE_STOP_TIMES):
            deps = await cp.get_next_departures_async("Porto-Campanha")
        assert deps
        assert all(not d.get("estimated") for d in deps)

    @pytest.mark.asyncio
    async def test_falls_back_to_estimates_when_source_empty(self):
        with patch("bot.services.cp._fetch_stoptimes",
                   new_callable=AsyncMock, return_value=[]):
            deps = await cp.get_next_departures_async("Porto-Campanha")
        assert deps
        assert all(d["estimated"] for d in deps)

    @pytest.mark.asyncio
    async def test_falls_back_when_source_raises(self):
        with patch("bot.services.cp.get_realtime_departures",
                   new_callable=AsyncMock, side_effect=RuntimeError("boom")):
            deps = await cp.get_next_departures_async("Ermesinde")
        assert deps
        assert all(d["estimated"] for d in deps)

    @pytest.mark.asyncio
    async def test_unknown_station_returns_empty_through_the_chain(self):
        with patch("bot.services.cp._fetch_stoptimes",
                   new_callable=AsyncMock, return_value=[]):
            assert await cp.get_next_departures_async("Nowhere XYZ 123") == []


# ---------------------------------------------------------------------------
# Honest labelling of estimates
# ---------------------------------------------------------------------------

class TestHonestEstimates:
    def test_estimates_are_flagged(self):
        deps = cp.get_next_departures("Porto-Campanha")
        assert deps
        for dep in deps:
            assert dep["estimated"] is True
            assert dep["realtime"] is False
            assert dep["scheduled"] is False

    def test_estimates_never_fabricate_a_clock_time(self):
        """The old code invented "~14:35"; a frequency must stay a frequency."""
        import re
        deps = cp.get_next_departures("Porto-Campanha")
        assert deps
        for dep in deps:
            assert not re.search(r"\d{1,2}:\d{2}", dep["time"]), dep

    def test_estimates_carry_the_interval(self):
        deps = cp.get_next_departures("Ermesinde")
        assert deps
        for dep in deps:
            assert dep["interval_min"] > 0
            assert str(dep["interval_min"]) in dep["time"]

    def test_interval_wording(self):
        assert cp.format_interval(30) == "a cada ~30 min"
        assert cp.format_interval(30, "en") == "every ~30 min"

    def test_not_anchored_to_the_top_of_the_hour(self):
        """Results must not depend on the current minute."""
        from datetime import datetime
        seen = []
        for minute in (0, 7, 29, 44, 59):
            with patch("bot.services.cp.datetime") as mock_dt:
                mock_dt.now.return_value = datetime(2026, 3, 9, 10, minute, 0)
                mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
                seen.append(cp.get_next_departures("Porto-Campanha"))
        assert all(entry == seen[0] for entry in seen[1:])

    def test_closed_service_is_marked(self):
        from datetime import datetime
        with patch("bot.services.cp.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 3, 9, 3, 0, 0)
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            deps = cp.get_next_departures("Porto-Campanha")
        assert len(deps) == 1
        assert deps[0]["closed"] is True
        assert deps[0]["direction"] == cp.CLOSED_DIRECTION

    def test_frequency_info_declares_itself_an_estimate(self):
        assert cp.get_frequency_info("aveiro")["estimated"] is True


# ---------------------------------------------------------------------------
# Directions come from real route order, not endpoint guessing
# ---------------------------------------------------------------------------

class TestDirections:
    def test_mid_line_station_shows_both_directions(self):
        directions = cp.get_line_directions("aveiro", "Espinho")
        assert directions == ["Porto-São Bento", "Aveiro"]

    def test_first_terminus_shows_one_direction(self):
        assert cp.get_line_directions("braga", "Porto-São Bento") == ["Braga"]

    def test_last_terminus_shows_one_direction(self):
        assert cp.get_line_directions("braga", "Braga") == ["Porto-São Bento"]

    def test_directions_use_display_names(self):
        assert "Porto-Campanhã" in cp.get_line_directions("minho", "Nine")

    def test_unknown_line_has_no_directions(self):
        assert cp.get_line_directions("nope", "Porto-Campanha") == []

    def test_no_duplicate_direction_entries(self):
        """Every slot used to be emitted twice, once per terminal."""
        deps = cp.get_next_departures("Espinho", line_id="aveiro")
        keys = [(d["direction"], d["line_id"]) for d in deps]
        assert len(keys) == len(set(keys))

    def test_terminus_departures_have_a_single_direction(self):
        deps = cp.get_next_departures("Braga")
        assert len({d["direction"] for d in deps}) == 1


# ---------------------------------------------------------------------------
# Station name data quality
# ---------------------------------------------------------------------------

class TestStationNames:
    def test_typos_are_gone_from_canonical_keys(self):
        assert "Lousãdo" not in cp.STATIONS
        assert "Receão" not in cp.STATIONS
        assert "Lousado" in cp.STATIONS
        assert "Recarei - Sobreira" in cp.STATIONS

    @pytest.mark.parametrize("alias,expected", [
        ("Lousãdo", "Lousado"),
        ("Lousado", "Lousado"),
        ("lousado", "Lousado"),
        ("Receão", "Recarei - Sobreira"),
        ("Receção", "Recarei - Sobreira"),
        ("Recarei", "Recarei - Sobreira"),
        ("Porto-Campanhã", "Porto-Campanha"),
        ("Porto-Campanha", "Porto-Campanha"),
        ("Campanhã", "Porto-Campanha"),
        ("campanha", "Porto-Campanha"),
        ("São Bento", "Porto-São Bento"),
        ("Porto Sao Bento", "Porto-São Bento"),
        ("guimaraes", "Guimarães"),
        ("Caide", "Caíde"),
        ("leca do balio", "Leça do Balio"),
    ])
    def test_alias_resolution(self, alias, expected):
        assert cp.resolve_station_name(alias) == expected

    def test_unknown_name_is_not_resolved(self):
        assert cp.resolve_station_name("Nowhere XYZ 123") is None
        assert cp.resolve_station_name("") is None
        assert cp.resolve_station_name(None) is None

    def test_campanha_display_name_is_accented(self):
        assert cp.display_name("Porto-Campanha") == "Porto-Campanhã"
        assert cp.display_name("Porto-Campanhã") == "Porto-Campanhã"

    def test_display_name_passes_unknown_through(self):
        assert cp.display_name("Ovar") == "Ovar"

    def test_search_prefers_the_resolved_station(self):
        """A typo must not let fuzzy matching pick a different station."""
        for query in ("Campanhã", "campanha", "Porto-Campanhã"):
            results = cp.search_stations(query)
            assert results, query
            assert results[0]["name"] == "Porto-Campanha", query

    def test_search_results_expose_display_names(self):
        results = cp.search_stations("Porto-Campanha")
        assert results[0]["display"] == "Porto-Campanhã"

    def test_station_info_via_alias(self):
        info = cp.get_station_info("Lousãdo")
        assert info is not None
        assert info["name"] == "Lousado"

    def test_departures_via_alias(self):
        assert cp.get_next_departures("Receão")
        assert cp.get_next_departures("Lousãdo")

    def test_nearby_exposes_display_names(self):
        nearby = cp.get_nearby_stations(41.1487, -8.5848, radius_km=1.0)
        assert nearby
        assert nearby[0]["name"] == "Porto-Campanha"
        assert nearby[0]["display"] == "Porto-Campanhã"

    def test_coordinates_match_the_real_stations(self):
        """Several coordinates were 5-20 km off before."""
        assert cp.STATIONS["Caíde"]["lat"] == pytest.approx(41.2526, abs=0.01)
        assert cp.STATIONS["Nine"]["lat"] == pytest.approx(41.4555, abs=0.01)
        assert cp.STATIONS["Lordelo"]["lat"] == pytest.approx(41.3655, abs=0.01)


class TestStopIdCoverage:
    def test_every_station_has_a_stop_id_except_the_known_gap(self):
        missing = [n for n in cp.STATIONS if n not in cp.MOTIS_STOP_IDS]
        # CP has no station called "São Félix da Marinha" (the stop there is
        # Aguda), so it can only ever fall back to the frequency estimate.
        assert missing == ["São Félix da Marinha"]

    def test_stop_ids_belong_to_cps_feed(self):
        for name, stop_id in cp.MOTIS_STOP_IDS.items():
            assert stop_id.startswith(cp.MOTIS_CP_STOP_PREFIX), name

    def test_stop_ids_are_unique(self):
        ids = list(cp.MOTIS_STOP_IDS.values())
        assert len(ids) == len(set(ids))

    def test_get_stop_id_resolves_aliases(self):
        assert cp.get_stop_id("Porto-Campanhã") == \
            cp.MOTIS_STOP_IDS["Porto-Campanha"]
        assert cp.get_stop_id("Nowhere XYZ 123") is None


# ---------------------------------------------------------------------------
# Ordered line stations
# ---------------------------------------------------------------------------

class TestLineOrder:
    def test_aveiro_line_is_in_route_order(self):
        stations = cp.get_line_stations("aveiro")
        assert stations[0] == "Porto-São Bento"
        assert stations[-1] == "Aveiro"
        assert (stations.index("Porto-Campanha")
                < stations.index("Espinho")
                < stations.index("Aveiro"))

    def test_marco_line_is_in_route_order(self):
        stations = cp.get_line_stations("marco")
        assert (stations.index("Ermesinde")
                < stations.index("Valongo")
                < stations.index("Paredes")
                < stations.index("Marco de Canaveses"))

    def test_order_is_not_dict_insertion_order(self):
        """Insertion order put Valongo before Espinho etc.; route order must not."""
        insertion = [n for n in cp.STATIONS if "marco" in cp.STATIONS[n]["lines"]]
        assert cp.get_line_stations("marco") != insertion

    def test_returns_a_copy(self):
        stations = cp.get_line_stations("aveiro")
        stations.append("Bogus")
        assert "Bogus" not in cp.get_line_stations("aveiro")

    def test_unknown_line_is_empty(self):
        assert cp.get_line_stations("nope") == []

    def test_display_variant(self):
        assert "Porto-Campanhã" in cp.get_line_stations_display("aveiro")

    def test_membership_matches_order(self):
        for line_id, ordered in cp.LINE_STATION_ORDER.items():
            for name in ordered:
                assert name in cp.STATIONS, f"{line_id}: unknown {name}"
                assert line_id in cp.STATIONS[name]["lines"]
            assert len(ordered) == len(set(ordered)), line_id

    def test_every_station_belongs_to_a_line(self):
        for name, data in cp.STATIONS.items():
            assert data["lines"], name

    def test_every_line_has_frequency_data(self):
        for line_id in cp.CP_LINES:
            for bucket in ("peak", "off_peak", "weekend"):
                assert line_id in cp.FREQUENCIES[bucket], (line_id, bucket)

    def test_all_lines_report_ordered_station_counts(self):
        for line in cp.get_all_lines():
            assert line["station_count"] == len(cp.get_line_stations(line["id"]))
            assert line["station_count"] > 1


class TestBalanceDirections:
    def test_keeps_every_direction_when_trimming(self):
        deps = [
            {"direction": "A", "minutes": 1},
            {"direction": "A", "minutes": 2},
            {"direction": "A", "minutes": 3},
            {"direction": "B", "minutes": 40},
        ]
        out = cp._balance_directions(deps, 2)
        assert {d["direction"] for d in out} == {"A", "B"}

    def test_no_trim_when_short_enough(self):
        deps = [{"direction": "A", "minutes": 1}]
        assert cp._balance_directions(deps, 5) == deps

    def test_fills_remaining_slots_with_soonest(self):
        deps = [
            {"direction": "A", "minutes": 1},
            {"direction": "A", "minutes": 2},
            {"direction": "B", "minutes": 3},
        ]
        out = cp._balance_directions(deps, 3)
        assert [d["minutes"] for d in out] == [1, 2, 3]


# ---------------------------------------------------------------------------
# Handler integration
# ---------------------------------------------------------------------------

def _make_query(data="train:station:Porto-Campanha"):
    query = MagicMock()
    query.data = data
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.edit_message_reply_markup = AsyncMock()
    query.from_user = MagicMock()
    query.from_user.id = 42
    query.from_user.language_code = "pt"
    query.message = MagicMock()
    query.message.chat_id = 99
    return query


def _make_update(data="train:station:Porto-Campanha"):
    update = MagicMock()
    update.callback_query = _make_query(data)
    update.effective_user = MagicMock()
    update.effective_user.id = 42
    update.effective_user.language_code = "pt"
    return update


def _make_context():
    ctx = MagicMock()
    ctx.user_data = {}
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()
    ctx.bot.send_location = AsyncMock()
    return ctx


class TestTrainHandlers:
    @pytest.mark.asyncio
    async def test_station_callback_shows_real_timetable_note(self):
        from bot.handlers import trains

        update, ctx = _make_update(), _make_context()
        real = [{"direction": "Aveiro", "time": "4 min", "minutes": 4,
                 "line": "🟢 Linha de Aveiro", "estimated": False,
                 "scheduled": True, "realtime": False}]
        with patch("bot.handlers.trains.cp.get_next_departures_async",
                   new_callable=AsyncMock, return_value=real), \
             patch("bot.handlers.trains.is_favorite",
                   new_callable=AsyncMock, return_value=False):
            await trains.train_station_callback(update, ctx)

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Aveiro" in text
        assert "Horário oficial CP" in text
        assert "não é horário real" not in text

    @pytest.mark.asyncio
    async def test_station_callback_labels_estimates_honestly(self):
        from bot.handlers import trains

        update, ctx = _make_update(), _make_context()
        estimated = [{"direction": "Aveiro", "time": "a cada ~30 min",
                      "minutes": 30, "interval_min": 30,
                      "line": "🟢 Linha de Aveiro", "estimated": True}]
        with patch("bot.handlers.trains.cp.get_next_departures_async",
                   new_callable=AsyncMock, return_value=estimated), \
             patch("bot.handlers.trains.is_favorite",
                   new_callable=AsyncMock, return_value=False):
            await trains.train_station_callback(update, ctx)

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "não é horário real" in text
        assert "Horário oficial CP" not in text

    @pytest.mark.asyncio
    async def test_station_callback_uses_accented_header(self):
        from bot.handlers import trains

        update, ctx = _make_update(), _make_context()
        with patch("bot.handlers.trains.cp.get_next_departures_async",
                   new_callable=AsyncMock, return_value=[]), \
             patch("bot.handlers.trains.is_favorite",
                   new_callable=AsyncMock, return_value=False):
            await trains.train_station_callback(update, ctx)

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Campanhã" in text

    @pytest.mark.asyncio
    async def test_station_callback_survives_message_not_modified(self):
        from telegram.error import BadRequest
        from bot.handlers import trains

        update, ctx = _make_update(), _make_context()
        update.callback_query.edit_message_text = AsyncMock(
            side_effect=BadRequest("Message is not modified"))
        with patch("bot.handlers.trains.cp.get_next_departures_async",
                   new_callable=AsyncMock, return_value=[]), \
             patch("bot.handlers.trains.is_favorite",
                   new_callable=AsyncMock, return_value=False):
            await trains.train_station_callback(update, ctx)  # must not raise

    @pytest.mark.asyncio
    async def test_station_callback_falls_back_when_async_raises(self):
        from bot.handlers import trains

        update, ctx = _make_update(), _make_context()
        with patch("bot.handlers.trains.cp.get_next_departures_async",
                   new_callable=AsyncMock, side_effect=RuntimeError("boom")), \
             patch("bot.handlers.trains.is_favorite",
                   new_callable=AsyncMock, return_value=False):
            await trains.train_station_callback(update, ctx)

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Campanhã" in text

    @pytest.mark.asyncio
    async def test_closed_service_message(self):
        from bot.handlers import trains

        update, ctx = _make_update(), _make_context()
        closed = [{"direction": cp.CLOSED_DIRECTION, "time": "x", "line": "",
                   "estimated": True, "closed": True}]
        with patch("bot.handlers.trains.cp.get_next_departures_async",
                   new_callable=AsyncMock, return_value=closed), \
             patch("bot.handlers.trains.is_favorite",
                   new_callable=AsyncMock, return_value=False):
            await trains.train_station_callback(update, ctx)

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "encerrado" in text

    @pytest.mark.asyncio
    async def test_frequencies_view(self):
        from bot.handlers import trains

        update, ctx = _make_update(trains.FREQ_CALLBACK), _make_context()
        await trains.train_line_callback(update, ctx)

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Frequências CP" in text
        assert "não é horário real" in text
        for data in cp.CP_LINES.values():
            assert data["name"] in text, data["name"]

    @pytest.mark.asyncio
    async def test_menu_keyboard_has_frequencies_button(self):
        from bot.handlers import trains

        kb = trains._trains_menu_keyboard("pt")
        callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert trains.FREQ_CALLBACK in callbacks

    @pytest.mark.asyncio
    async def test_lines_keyboard_has_frequencies_button(self):
        from bot.handlers import trains

        kb = trains._lines_list_keyboard("pt")
        callbacks = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert trains.FREQ_CALLBACK in callbacks

    @pytest.mark.asyncio
    async def test_line_view_lists_stations_in_route_order(self):
        from bot.handlers import trains

        update, ctx = _make_update("train:line:aveiro"), _make_context()
        await trains.train_line_callback(update, ctx)

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert text.index("Campanhã") < text.index("Espinho")
        assert text.index("Espinho") < text.rindex("Aveiro")
        assert text.index("General Torres") < text.index("Granja")

    @pytest.mark.asyncio
    async def test_unknown_line(self):
        from bot.handlers import trains

        update, ctx = _make_update("train:line:bogus"), _make_context()
        await trains.train_line_callback(update, ctx)
        update.callback_query.edit_message_text.assert_called_once()


class TestI18nFallbacks:
    def test_missing_keys_never_leak_raw_key_names(self):
        from bot.handlers import trains

        for key in trains._FALLBACK_STRINGS:
            for lang in ("pt", "en"):
                value = trains._t(key, lang)
                assert value
                assert value != key, (key, lang)

    def test_existing_i18n_keys_win(self):
        from bot.handlers import trains
        from bot.utils.i18n import t as real_t

        assert trains._t("trains_title", "pt") == real_t("trains_title", "pt")

    def test_unknown_key_returns_the_key_without_crashing(self):
        from bot.handlers import trains
        assert trains._t("definitely_not_a_key_xyz", "pt") == \
            "definitely_not_a_key_xyz"

    def test_formatting_is_applied(self):
        from bot.handlers import trains
        assert "30" in trains._t("trains_every_n_min", "pt", n=30)
