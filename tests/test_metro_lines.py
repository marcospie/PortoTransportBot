"""Tests for Metro do Porto network correctness.

Covers the bugs this file was created for:

* station->line associations (users only saw one direction because a station was
  attributed to a single line it barely serves),
* honest ``realtime`` flags,
* MOTIS stop-id resolution and its fallback,
* the ``Bexp`` express-service mapping,
* ordered per-line station listings,
* GTFS post-midnight (``>24:00``) service-day offsets,
* Line C / Line D route endpoints.

Every expected value here was derived from the Metro do Porto GTFS feed dated
07-04-2026 (routes.txt/trips.txt/stop_times.txt/stops.txt), not from memory.
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from bot.config import METRO_LINES, parse_gtfs_resources
from bot.services import metro
from bot.services import metro_realtime
from bot.services.metro import (
    LINE_STATION_ORDER,
    STATIONS,
    get_line_stations,
    get_station_lines,
    _canonical_line_code,
    _gtfs_time_to_seconds,
)


# ===========================================================================
# 1. Station <-> line associations
# ===========================================================================

class TestMultiLineStationAssociations:
    """Stations served by several lines must list all of them.

    Attributing a shared station to one line is what makes the bot show a
    single direction: the "expected directions" come from the endpoints of the
    lines listed here.
    """

    # (station, lines that must be present) — from GTFS stop_times x trips.
    MULTI_LINE_STATIONS = [
        # Northern B/E corridor — these were all "Line E only" or "Line B only".
        ("Fonte do Cuco", {"B", "C", "E"}),
        ("Custóias", {"B", "E"}),
        ("Crestins", {"B", "E"}),
        ("Esposade", {"B", "E"}),
        ("Verdes", {"B", "E"}),
        # Pedras Rubras and Lidador are Line B, NOT Line E: the E branches off
        # to the airport at Verdes.
        ("Pedras Rubras", {"B"}),
        ("Lidador", {"B"}),
        # Shared trunk: Line F runs the whole way to Senhora da Hora, so every
        # trunk station serves it.
        ("Senhora da Hora", {"A", "B", "C", "E", "F"}),
        ("Sete Bicas", {"A", "B", "C", "E", "F"}),
        ("Viso", {"A", "B", "C", "E", "F"}),
        ("Ramalde", {"A", "B", "C", "E", "F"}),
        ("Francos", {"A", "B", "C", "E", "F"}),
        ("Casa da Música", {"A", "B", "C", "E", "F"}),
        ("Carolina Michaelis", {"A", "B", "C", "E", "F"}),
        ("Lapa", {"A", "B", "C", "E", "F"}),
        ("Trindade", {"A", "B", "C", "D", "E", "F"}),
        ("Bolhão", {"A", "B", "C", "E", "F"}),
        ("Campo 24 de Agosto", {"A", "B", "C", "E", "F"}),
        ("Heroísmo", {"A", "B", "C", "E", "F"}),
        ("Campanhã", {"A", "B", "C", "E", "F"}),
        ("Estádio do Dragão", {"A", "B", "E", "F"}),
    ]

    @pytest.mark.parametrize("station,expected_lines", MULTI_LINE_STATIONS)
    def test_station_lists_all_its_lines(self, station, expected_lines):
        assert station in STATIONS, f"{station} missing from STATIONS"
        actual = set(STATIONS[station]["lines"])
        assert actual == expected_lines, (
            f"{station}: expected lines {sorted(expected_lines)}, "
            f"got {sorted(actual)}"
        )

    @pytest.mark.parametrize("station,expected_lines", MULTI_LINE_STATIONS)
    def test_get_station_lines_agrees(self, station, expected_lines):
        codes = {line["code"] for line in get_station_lines(station)}
        assert codes == expected_lines

    def test_eastern_branch_is_line_f_not_c(self):
        """Line C terminates at Campanhã; the Gondomar branch is Line F."""
        for station in ("Nasoni", "Nau Vitória", "Levada", "Rio Tinto",
                        "Campainha", "Baguim", "Contumil", "Fânzeres",
                        "Venda Nova", "Carreira"):
            lines = set(STATIONS[station]["lines"])
            assert lines == {"F"}, f"{station} should be Line F only, got {lines}"

    def test_vasco_da_gama_is_line_a(self):
        """Vasco da Gama is on Line A — it is not a Line E station."""
        assert set(STATIONS["Vasco da Gama"]["lines"]) == {"A"}
        assert set(STATIONS["Estádio do Mar"]["lines"]) == {"A"}

    def test_casa_da_musica_has_no_line_d(self):
        """Line D runs Trindade->Aliados, bypassing Casa da Música."""
        assert "D" not in STATIONS["Casa da Música"]["lines"]

    def test_line_d_only_stations(self):
        assert set(STATIONS["Aliados"]["lines"]) == {"D"}
        assert set(STATIONS["Santo Ovídio"]["lines"]) == {"D"}

    def test_every_station_has_known_lines(self):
        for name, data in STATIONS.items():
            assert data["lines"], f"{name} has no lines"
            for code in data["lines"]:
                assert code in METRO_LINES, f"{name} references line {code}"

    def test_no_duplicate_coordinates(self):
        seen = {}
        for name, data in STATIONS.items():
            key = (data["lat"], data["lon"])
            assert key not in seen, f"{name} shares coordinates with {seen[key]}"
            seen[key] = name


# ===========================================================================
# 2. Line route endpoints (direction headsigns are generated from these)
# ===========================================================================

class TestLineRouteEndpoints:
    def test_line_d_covers_full_gaia_extension(self):
        """Line D runs past Santo Ovídio to Vila d'Este.

        The old endpoint "Sto. Ovídio" produced wrong headsigns for the three
        extension stations and made Santo Ovídio look like a terminus.
        """
        route = METRO_LINES["D"]["route"]
        assert route == "Vila d'Este ↔ Hospital de São João"
        for endpoint in route.split(" ↔ "):
            assert endpoint in STATIONS, (
                f"Line D endpoint '{endpoint}' is not a station name, so "
                f"terminal detection and headsigns will not match"
            )

    def test_line_c_terminates_at_campanha(self):
        """Campainha is a Line F station; Line C ends at Campanhã."""
        route = METRO_LINES["C"]["route"]
        assert route == "ISMAI ↔ Campanhã"
        assert "Campainha" not in route

    @pytest.mark.parametrize("code", sorted(METRO_LINES))
    def test_endpoints_are_real_station_names(self, code):
        route = METRO_LINES[code]["route"]
        for endpoint in route.split(" ↔ "):
            assert endpoint in STATIONS, (
                f"Line {code} endpoint '{endpoint}' is not in STATIONS"
            )

    @pytest.mark.parametrize("code", sorted(METRO_LINES))
    def test_endpoints_are_the_ends_of_the_ordered_line(self, code):
        stations = get_line_stations(code)
        endpoints = set(METRO_LINES[code]["route"].split(" ↔ "))
        assert {stations[0], stations[-1]} == endpoints, (
            f"Line {code}: ordered list runs {stations[0]}..{stations[-1]} "
            f"but route says {endpoints}"
        )


# ===========================================================================
# 3. Ordered line stations
# ===========================================================================

class TestOrderedLineStations:
    @pytest.mark.parametrize("code", sorted(METRO_LINES))
    def test_order_matches_membership(self, code):
        """The ordered list must contain exactly the line's stations."""
        ordered = get_line_stations(code)
        membership = {n for n, d in STATIONS.items() if code in d["lines"]}
        assert set(ordered) == membership, (
            f"Line {code}: ordered/membership mismatch. "
            f"missing={sorted(membership - set(ordered))} "
            f"extra={sorted(set(ordered) - membership)}"
        )

    @pytest.mark.parametrize("code", sorted(METRO_LINES))
    def test_no_duplicates_in_order(self, code):
        ordered = get_line_stations(code)
        assert len(ordered) == len(set(ordered))

    def test_line_b_does_not_put_dragao_mid_line(self):
        """The original bug: dict order put Estádio do Dragão in the middle."""
        stations = get_line_stations("B")
        idx = stations.index("Estádio do Dragão")
        assert idx in (0, len(stations) - 1), (
            f"Estádio do Dragão at position {idx} of {len(stations)} — a "
            f"terminus must render at one end of the line map"
        )

    def test_line_b_trunk_then_branch_order(self):
        """Consecutive stations must be geographically adjacent."""
        stations = get_line_stations("B")
        # Campanhã is adjacent to Estádio do Dragão and Heroísmo.
        i = stations.index("Campanhã")
        neighbours = {stations[i - 1], stations[i + 1]}
        assert neighbours == {"Estádio do Dragão", "Heroísmo"}

    def test_line_f_runs_fanzeres_to_senhora_da_hora(self):
        stations = get_line_stations("F")
        assert stations[0] == "Fânzeres"
        assert stations[-1] == "Senhora da Hora"
        # Contumil sits between the Gondomar branch and Estádio do Dragão.
        assert stations.index("Contumil") < stations.index("Estádio do Dragão")

    def test_line_d_extension_order(self):
        """Santo Ovídio -> Manuel Leão -> Hospital Santos Silva -> Vila d'Este."""
        stations = get_line_stations("D")
        order = [stations.index(n) for n in
                 ("Santo Ovídio", "Manuel Leão", "Hospital Santos Silva",
                  "Vila d'Este")]
        assert order == sorted(order, reverse=True) or order == sorted(order), (
            f"Line D extension is out of sequence: {order}"
        )
        # Adjacency: D. João II next to Santo Ovídio
        assert abs(stations.index("D. João II")
                   - stations.index("Santo Ovídio")) == 1

    def test_ordered_lists_are_used_not_insertion_order(self):
        assert LINE_STATION_ORDER, "LINE_STATION_ORDER fallback must exist"
        for code in METRO_LINES:
            assert code in LINE_STATION_ORDER

    def test_unknown_line_returns_empty(self):
        assert get_line_stations("Z") == []

    def test_line_code_is_case_insensitive(self):
        assert get_line_stations("a") == get_line_stations("A")

    def test_derived_order_takes_precedence(self):
        """A GTFS-derived order must override the hardcoded snapshot."""
        fake = ["Trindade", "Bolhão"]
        with patch.dict(metro._derived_line_order, {"A": fake}, clear=False):
            assert get_line_stations("A") == fake


# ===========================================================================
# 4. GTFS service-day offsets (post-midnight departures)
# ===========================================================================

class TestGtfsTimeParsing:
    @pytest.mark.parametrize("value,expected", [
        ("00:00:00", 0),
        ("06:30:00", 6 * 3600 + 30 * 60),
        ("23:59:59", 23 * 3600 + 59 * 60 + 59),
        # Past-midnight service-day offsets must NOT wrap to the same morning.
        ("24:00:00", 24 * 3600),
        ("24:30:00", 24 * 3600 + 30 * 60),
        ("25:10:00", 25 * 3600 + 10 * 60),
        ("06:30", 6 * 3600 + 30 * 60),
    ])
    def test_parses_service_day_seconds(self, value, expected):
        assert _gtfs_time_to_seconds(value) == expected

    @pytest.mark.parametrize("value", ["", "abc", "12", "aa:bb:cc", "12:99:00"])
    def test_rejects_garbage(self, value):
        assert _gtfs_time_to_seconds(value) is None

    def test_2430_is_after_2359(self):
        """The old string comparison made "24:30" sort before "23:59"."""
        assert _gtfs_time_to_seconds("24:30:00") > _gtfs_time_to_seconds("23:59:00")


class TestPostMidnightGtfsDepartures:
    """A 24:30 departure must be reachable at 23:55, not filtered out."""

    def _install_feed(self, dep_times):
        """Install a minimal fake GTFS feed at Trindade."""
        stop_id = "T1"
        metro._gtfs_stops = {stop_id: {"name": "Trindade",
                                       "lat": 41.15228, "lon": -8.609299}}
        metro._gtfs_trips = {}
        metro._gtfs_stop_times = {stop_id: []}
        metro._gtfs_calendar = {"ALL": {d: True for d in metro._DOW_NAMES}}
        for i, t in enumerate(dep_times):
            trip_id = f"trip{i}"
            metro._gtfs_trips[trip_id] = {
                "route_id": "A", "service_id": "ALL",
                "headsign": "Senhor de Matosinhos", "direction_id": "0",
            }
            metro._gtfs_stop_times[stop_id].append({
                "trip_id": trip_id, "time": t,
                "secs": _gtfs_time_to_seconds(t),
            })
        metro._gtfs_stop_times[stop_id].sort(key=lambda x: x["secs"])
        metro._station_to_gtfs = {"Trindade": [stop_id]}

    @pytest.fixture(autouse=True)
    def _restore_state(self):
        saved = (metro._gtfs_stops, metro._gtfs_trips, metro._gtfs_stop_times,
                 metro._gtfs_calendar, metro._station_to_gtfs, metro._gtfs_loaded)
        yield
        (metro._gtfs_stops, metro._gtfs_trips, metro._gtfs_stop_times,
         metro._gtfs_calendar, metro._station_to_gtfs,
         metro._gtfs_loaded) = saved

    def test_post_midnight_departure_is_found_before_midnight(self):
        self._install_feed(["24:10:00", "24:30:00"])
        now = datetime(2026, 3, 9, 23, 55, 0)  # Monday 23:55
        deps = metro._get_gtfs_departures("Trindade", None, 5, now)
        assert deps, "post-midnight GTFS departures were dropped"
        minutes = sorted(d["minutes"] for d in deps)
        # 24:10 is 15 min away, 24:30 is 35 min away.
        assert minutes == [15, 35], minutes

    def test_post_midnight_departure_found_after_midnight(self):
        """At 00:05 the 24:30 row belongs to *yesterday's* service day."""
        self._install_feed(["24:30:00"])
        now = datetime(2026, 3, 10, 0, 5, 0)  # Tuesday 00:05
        deps = metro._get_gtfs_departures("Trindade", None, 5, now)
        assert deps, "yesterday's service day was not consulted"
        assert deps[0]["minutes"] == 25

    def test_already_departed_is_excluded(self):
        self._install_feed(["06:00:00"])
        now = datetime(2026, 3, 9, 23, 55, 0)
        assert metro._get_gtfs_departures("Trindade", None, 5, now) == []

    def test_far_future_is_excluded(self):
        """A feed whose calendar starts weeks out must not look like "next"."""
        self._install_feed(["12:00:00"])
        now = datetime(2026, 3, 9, 0, 5, 0)
        # 12:00 is ~12h away, past the horizon.
        assert metro._get_gtfs_departures("Trindade", None, 5, now) == []

    def test_line_filter_accepts_bexp_as_b(self):
        self._install_feed(["10:00:00"])
        metro._gtfs_trips["trip0"]["route_id"] = "Bexp"
        now = datetime(2026, 3, 9, 9, 55, 0)
        deps = metro._get_gtfs_departures("Trindade", "B", 5, now)
        assert deps, "Bexp trips must be returned when filtering on line B"
        assert deps[0]["line_code"] == "B"
        assert "Vermelha" in deps[0]["line"]


# ===========================================================================
# 5. Route code canonicalisation (Bexp)
# ===========================================================================

class TestRouteCodeMapping:
    @pytest.mark.parametrize("route_id,expected", [
        ("A", "A"), ("B", "B"), ("Bexp", "B"), ("BEXP", "B"),
        ("C", "C"), ("D", "D"), ("E", "E"), ("F", "F"),
    ])
    def test_canonical_line_code(self, route_id, expected):
        assert _canonical_line_code(route_id) == expected

    @pytest.mark.parametrize("short_name", ["B", "Bexp", "BEXP", "Bx", "BX"])
    def test_bexp_maps_to_red_line(self, short_name):
        """Bexp/Bx must render as Linha Vermelha, not "🚇 Linha Bexp"."""
        assert metro_realtime._ROUTE_TO_LINE[short_name] == "B"

    def test_bexp_stoptime_renders_with_line_colour(self):
        future = (datetime.now().astimezone().replace(microsecond=0)
                  + timedelta(minutes=5))
        stoptimes = [{
            "place": {"departure": future.isoformat()},
            "mode": "SUBWAY",
            "agencyName": "Metro do Porto",
            "headsign": "Póvoa de Varzim",
            "routeShortName": "Bx",
            "realTime": False,
        }]
        deps = metro_realtime._parse_stoptimes(stoptimes)
        assert len(deps) == 1
        assert deps[0]["line_code"] == "B"
        assert deps[0]["line"] == "🔴 Linha Vermelha"
        assert "Bexp" not in deps[0]["line"]
        assert "Bx" not in deps[0]["line"]


# ===========================================================================
# 6. Realtime-flag honesty
# ===========================================================================

class TestRealtimeFlagHonesty:
    @staticmethod
    def _stoptime(realtime_flag, minutes=5):
        from datetime import timezone
        dep = (datetime.now(timezone.utc)
               + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
        st = {
            "place": {"departure": dep, "scheduledDeparture": dep},
            "mode": "SUBWAY",
            "agencyName": "Metro do Porto",
            "headsign": "Senhor de Matosinhos",
            "routeShortName": "A",
        }
        if realtime_flag is not None:
            st["realTime"] = realtime_flag
        return st

    def test_scheduled_data_is_not_flagged_realtime(self):
        """MOTIS reports realTime=false for Metro do Porto — respect it."""
        deps = metro_realtime._parse_stoptimes([self._stoptime(False)])
        assert len(deps) == 1
        assert deps[0]["realtime"] is False
        assert deps[0]["estimated"] is False

    def test_live_data_is_flagged_realtime(self):
        deps = metro_realtime._parse_stoptimes([self._stoptime(True)])
        assert deps[0]["realtime"] is True

    def test_missing_flag_defaults_to_not_realtime(self):
        """Absent flag must not be optimistically treated as live."""
        deps = metro_realtime._parse_stoptimes([self._stoptime(None)])
        assert deps[0]["realtime"] is False

    def test_scheduled_departure_is_preserved(self):
        deps = metro_realtime._parse_stoptimes([self._stoptime(False)])
        assert deps[0]["scheduled_departure"]

    def test_formatting_says_scheduled_not_updated(self):
        """The honest flag must make the UI stop claiming live tracking."""
        from bot.utils.formatting import format_metro_schedule
        deps = metro_realtime._parse_stoptimes([self._stoptime(False)])
        text = format_metro_schedule("Trindade", "🔵 Linha Azul", deps)
        assert "Atualizado" not in text, (
            "scheduled data must not be labelled as live"
        )

    def test_far_future_departures_dropped(self):
        """Feed with no service today returned departures 3 weeks out."""
        deps = metro_realtime._parse_stoptimes(
            [self._stoptime(False, minutes=60 * 24 * 21)])
        assert deps == []

    def test_stale_past_departures_dropped(self):
        deps = metro_realtime._parse_stoptimes([self._stoptime(False, minutes=-30)])
        assert deps == []


# ===========================================================================
# 7. Stop-id resolution and fallback
# ===========================================================================

class TestStopIdResolution:
    @pytest.fixture(autouse=True)
    def _clear(self):
        metro_realtime._stop_id_cache.clear()
        metro_realtime._cache.clear()
        metro_realtime._negative_cache.clear()
        yield
        metro_realtime._stop_id_cache.clear()
        metro_realtime._cache.clear()
        metro_realtime._negative_cache.clear()

    def test_every_station_has_a_fallback_id(self):
        missing = [n for n in STATIONS if n not in metro_realtime._STATION_STOP_IDS]
        assert not missing, f"Stations without a fallback MOTIS id: {missing}"

    def test_fallback_ids_are_unique_and_well_formed(self):
        ids = list(metro_realtime._STATION_STOP_IDS.values())
        assert len(ids) == len(set(ids))
        for name, sid in metro_realtime._STATION_STOP_IDS.items():
            assert sid.startswith("pt-Metro-Porto_"), f"{name}: {sid}"

    @pytest.mark.asyncio
    async def test_resolve_uses_fallback_without_network(self):
        """No network call when a hardcoded id exists."""
        with patch.object(metro_realtime, "_geocode_stop_id",
                          new_callable=AsyncMock) as geo:
            got = await metro_realtime.resolve_stop_id("Trindade")
        assert got == "pt-Metro-Porto_5726"
        geo.assert_not_called()

    @pytest.mark.asyncio
    async def test_force_refresh_geocodes_and_caches(self):
        with patch.object(metro_realtime, "_geocode_stop_id",
                          new_callable=AsyncMock,
                          return_value="pt-Metro-Porto_9999") as geo:
            first = await metro_realtime.resolve_stop_id("Trindade",
                                                         force_refresh=True)
            assert first == "pt-Metro-Porto_9999"
            assert geo.await_count == 1
            # Cached: a second (non-forced) call must not geocode again.
            second = await metro_realtime.resolve_stop_id("Trindade")
        assert second == "pt-Metro-Porto_9999"
        assert geo.await_count == 1

    @pytest.mark.asyncio
    async def test_resolution_failure_falls_back_and_warns(self, caplog):
        import logging
        with caplog.at_level(logging.WARNING):
            with patch.object(metro_realtime, "_geocode_stop_id",
                              new_callable=AsyncMock, return_value=None):
                got = await metro_realtime.resolve_stop_id("Trindade",
                                                           force_refresh=True)
        assert got == "pt-Metro-Porto_5726", "must fall back to the pinned id"
        assert any(r.levelno >= logging.WARNING for r in caplog.records), (
            "a failed stop-id resolution must WARN, not just debug-log"
        )

    @pytest.mark.asyncio
    async def test_unknown_station_never_geocodes(self):
        with patch.object(metro_realtime, "_geocode_stop_id",
                          new_callable=AsyncMock) as geo:
            got = await metro_realtime.resolve_stop_id("Nonexistent Station 42")
        assert got is None
        geo.assert_not_called()

    @pytest.mark.asyncio
    async def test_stale_id_is_repaired_and_retried(self):
        """Empty result -> re-resolve -> retry with the fresh id."""
        from datetime import timezone
        dep = (datetime.now(timezone.utc)
               + timedelta(minutes=4)).strftime("%Y-%m-%dT%H:%M:%SZ")
        good = [{
            "place": {"departure": dep},
            "mode": "SUBWAY", "agencyName": "Metro do Porto",
            "headsign": "Senhor de Matosinhos", "routeShortName": "A",
            "realTime": False,
        }]

        async def fake_query(stop_id, count=20):
            return good if stop_id == "pt-Metro-Porto_NEW" else []

        with patch.object(metro_realtime, "_query_stoptimes",
                          side_effect=fake_query), \
             patch.object(metro_realtime, "_geocode_stop_id",
                          new_callable=AsyncMock,
                          return_value="pt-Metro-Porto_NEW"):
            deps = await metro_realtime.get_realtime_departures("Trindade",
                                                                count=5)
        assert deps, "a shifted stop id must be re-resolved and retried"
        assert deps[0]["direction"] == "Senhor de Matosinhos"

    def test_get_stop_id_prefers_resolved_over_fallback(self):
        assert metro_realtime.get_stop_id("Trindade") == "pt-Metro-Porto_5726"
        metro_realtime._stop_id_cache.set("stopid:Trindade", "pt-Metro-Porto_X")
        assert metro_realtime.get_stop_id("Trindade") == "pt-Metro-Porto_X"

    def test_get_stop_id_unknown(self):
        assert metro_realtime.get_stop_id("Nope") is None


# ===========================================================================
# 8. Negative caching / request hygiene
# ===========================================================================

class TestRequestHygiene:
    @pytest.fixture(autouse=True)
    def _clear(self):
        metro_realtime._negative_cache.clear()
        metro_realtime._cache.clear()
        yield
        metro_realtime._negative_cache.clear()
        metro_realtime._cache.clear()

    @pytest.mark.asyncio
    async def test_http_failure_is_negatively_cached(self, caplog):
        import logging

        class FakeResp:
            status_code = 503

            def json(self):
                return {}

        calls = []

        class FakeClient:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, params=None):
                calls.append(params)
                return FakeResp()

        with caplog.at_level(logging.WARNING), \
             patch.object(metro_realtime.httpx, "AsyncClient", FakeClient):
            first = await metro_realtime._query_stoptimes("pt-Metro-Porto_5726")
            second = await metro_realtime._query_stoptimes("pt-Metro-Porto_5726")

        assert first == [] and second == []
        assert len(calls) == 1, (
            "a failing API must not be re-hit on the next request"
        )
        assert any("HTTP 503" in r.getMessage() for r in caplog.records), (
            "an API failure must be logged at WARNING"
        )

    @pytest.mark.asyncio
    async def test_request_filters_to_subway_mode(self):
        """Without mode=SUBWAY the response is all STCP buses, no metro."""
        captured = {}

        class FakeResp:
            status_code = 200

            def json(self):
                return {"stopTimes": []}

        class FakeClient:
            def __init__(self, *a, **kw):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, url, params=None):
                captured.update(params or {})
                return FakeResp()

        with patch.object(metro_realtime.httpx, "AsyncClient", FakeClient):
            await metro_realtime._query_stoptimes("pt-Metro-Porto_5726")

        assert captured.get("mode") == "SUBWAY"

    @pytest.mark.asyncio
    async def test_bus_departures_are_ignored(self):
        """Belt and braces: STCP rows must never become metro departures."""
        from datetime import timezone
        dep = (datetime.now(timezone.utc)
               + timedelta(minutes=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
        deps = metro_realtime._parse_stoptimes([{
            "place": {"departure": dep},
            "mode": "BUS",
            "agencyName": "Sociedade de Transportes Colectivos do Porto",
            "headsign": "Aliados", "routeShortName": "600",
        }])
        assert deps == []


# ===========================================================================
# 9. GTFS feed URL resolution (config)
# ===========================================================================

class TestGtfsResourceResolution:
    def test_skips_zero_byte_resources(self):
        """The portal's "Mais Recente" metro file is 0 bytes."""
        package = {"result": {"resources": [
            {"format": "ZIP", "size": 0, "last_modified": "2026-07-17T09:00:00",
             "url": "https://example.org/empty.zip"},
            {"format": "ZIP", "size": 379207,
             "last_modified": "2026-04-23T14:38:57",
             "url": "https://example.org/good.zip"},
        ]}}
        assert parse_gtfs_resources(package) == ["https://example.org/good.zip"]

    def test_orders_newest_first(self):
        package = {"result": {"resources": [
            {"format": "GTFS", "size": 5000, "last_modified": "2024-09-06",
             "url": "https://example.org/old.zip"},
            {"format": "ZIP", "size": 5000, "last_modified": "2026-04-23",
             "url": "https://example.org/new.zip"},
        ]}}
        assert parse_gtfs_resources(package)[0] == "https://example.org/new.zip"

    def test_ignores_non_archive_resources(self):
        package = {"result": {"resources": [
            {"format": "url", "url": "https://www.metrodoporto.pt/pages/337"},
            {"format": "ZIP", "size": 5000, "url": "https://example.org/a.zip"},
        ]}}
        assert parse_gtfs_resources(package) == ["https://example.org/a.zip"]

    def test_keeps_resources_with_unknown_size(self):
        package = {"result": {"resources": [
            {"format": "ZIP", "size": None, "url": "https://example.org/a.zip"},
        ]}}
        assert parse_gtfs_resources(package) == ["https://example.org/a.zip"]

    def test_empty_package(self):
        assert parse_gtfs_resources({"result": {"resources": []}}) == []
        assert parse_gtfs_resources({}) == []


# ===========================================================================
# 10. GTFS-derived network data overrides the fallback
# ===========================================================================

class TestGtfsDerivation:
    @pytest.fixture(autouse=True)
    def _restore(self):
        saved = (metro._gtfs_stops, metro._gtfs_trips, metro._gtfs_stop_times,
                 metro._gtfs_trip_stops, metro._gtfs_calendar,
                 dict(metro._derived_line_order),
                 dict(metro._derived_station_lines),
                 {k: dict(v) for k, v in metro._derived_headways.items()},
                 {n: dict(d) for n, d in STATIONS.items()})
        yield
        (metro._gtfs_stops, metro._gtfs_trips, metro._gtfs_stop_times,
         metro._gtfs_trip_stops, metro._gtfs_calendar,
         metro._derived_line_order, metro._derived_station_lines,
         metro._derived_headways, restored) = saved
        for name, data in restored.items():
            STATIONS[name] = data

    def test_derivation_updates_lines_and_order(self):
        metro._gtfs_stops = {
            "1": {"name": "Trindade", "lat": 41.15228, "lon": -8.609299},
            "2": {"name": "Bolhão", "lat": 41.14978, "lon": -8.605901},
        }
        metro._gtfs_trips = {
            "t1": {"route_id": "Bexp", "service_id": "S", "headsign": "X",
                   "direction_id": "0"},
        }
        metro._gtfs_stop_times = {
            "1": [{"trip_id": "t1", "time": "10:00:00", "secs": 36000}],
            "2": [{"trip_id": "t1", "time": "10:02:00", "secs": 36120}],
        }
        metro._gtfs_trip_stops = {"t1": ["1", "2"]}
        metro._gtfs_calendar = {"S": {d: True for d in metro._DOW_NAMES}}

        metro._derive_network_from_gtfs()

        # Bexp is folded into B, and B is present for both stations.
        assert "B" in metro._derived_station_lines["Trindade"]
        assert "B" in STATIONS["Trindade"]["lines"]
        # Order comes straight from stop_sequence.
        assert metro._derived_line_order["B"] == ["Trindade", "Bolhão"]
        assert get_line_stations("B") == ["Trindade", "Bolhão"]

    def test_partial_feed_never_removes_a_line(self):
        """A feed missing a line must not drop it — that hides a direction.

        Regression guard for the reported bug class: losing a line association
        makes the station show departures in only one direction.
        """
        before = set(STATIONS["Trindade"]["lines"])
        assert {"A", "D"} <= before

        # Feed that only knows about Line B at Trindade.
        metro._gtfs_stops = {"1": {"name": "Trindade", "lat": 41.15228,
                                   "lon": -8.609299}}
        metro._gtfs_trips = {"t1": {"route_id": "B", "service_id": "S",
                                    "headsign": "X", "direction_id": "0"}}
        metro._gtfs_stop_times = {"1": [{"trip_id": "t1", "time": "10:00:00",
                                         "secs": 36000}]}
        metro._gtfs_trip_stops = {"t1": ["1"]}
        metro._gtfs_calendar = {"S": {d: True for d in metro._DOW_NAMES}}

        metro._derive_network_from_gtfs()

        after = set(STATIONS["Trindade"]["lines"])
        assert before <= after, (
            f"derivation removed line(s) {sorted(before - after)} from Trindade"
        )

    def test_feed_can_add_a_new_line_to_a_station(self):
        before = set(STATIONS["Aeroporto"]["lines"])
        assert "B" not in before

        metro._gtfs_stops = {"1": {"name": "Aeroporto", "lat": 41.23708,
                                   "lon": -8.669442}}
        metro._gtfs_trips = {"t1": {"route_id": "B", "service_id": "S",
                                    "headsign": "X", "direction_id": "0"}}
        metro._gtfs_stop_times = {"1": [{"trip_id": "t1", "time": "10:00:00",
                                         "secs": 36000}]}
        metro._gtfs_trip_stops = {"t1": ["1"]}
        metro._gtfs_calendar = {"S": {d: True for d in metro._DOW_NAMES}}

        metro._derive_network_from_gtfs()

        assert "B" in STATIONS["Aeroporto"]["lines"]

    def test_derivation_is_noop_without_feed(self):
        metro._gtfs_stops = {}
        metro._gtfs_trips = {}
        metro._derive_network_from_gtfs()
        assert metro._derived_station_lines == {}

    def test_unknown_feed_station_is_warned_not_added(self, caplog):
        import logging
        metro._gtfs_stops = {"9": {"name": "Estação Nova", "lat": 41.0,
                                   "lon": -8.0}}
        metro._gtfs_trips = {"t": {"route_id": "A", "service_id": "S",
                                    "headsign": "X", "direction_id": "0"}}
        metro._gtfs_stop_times = {"9": [{"trip_id": "t", "time": "10:00:00",
                                          "secs": 36000}]}
        metro._gtfs_trip_stops = {"t": ["9"]}
        metro._gtfs_calendar = {"S": {d: True for d in metro._DOW_NAMES}}

        with caplog.at_level(logging.WARNING):
            metro._derive_network_from_gtfs()

        assert "Estação Nova" not in STATIONS
        assert any("unknown to the bot" in r.getMessage() for r in caplog.records)

    def test_headways_measured_from_feed_are_used(self):
        metro._derived_headways = {"peak": {"A": 3}}
        assert metro._active_frequencies("peak")["A"] == 3
        info = metro.get_frequency_info("A")
        assert info["source"] == "gtfs"
        assert info["approximate"] is False
        assert "3 min" in info["peak"]

    def test_frequency_info_flags_approximation(self):
        metro._derived_headways = {}
        info = metro.get_frequency_info("A")
        assert info["source"] == "approximate"
        assert info["approximate"] is True


# ===========================================================================
# 11. Search threshold
# ===========================================================================

class TestSearchThreshold:
    def test_threshold_is_above_the_junk_tier(self):
        assert metro.SEARCH_MIN_SCORE >= 50

    @pytest.mark.parametrize("query,expected", [
        ("s bento", "São Bento"),
        ("sao joao", "Hospital de São João"),
        ("d joao 2", "D. João II"),
        ("camp", "Campanhã"),
        ("aero", "Aeroporto"),
        ("musica", "Casa da Música"),
        ("matosinhos", "Senhor de Matosinhos"),
        ("vila deste", "Vila d'Este"),
        ("sto ovidio", "Santo Ovídio"),
    ])
    def test_real_queries_still_resolve(self, query, expected):
        names = [r["name"] for r in metro.search_stations(query)]
        assert expected in names, f"'{query}' lost '{expected}': {names[:5]}"

    def test_junk_matches_are_rejected(self):
        """"s bento" must not surface Santo Ovídio / Santa Clara."""
        names = [r["name"] for r in metro.search_stations("s bento")]
        assert "Santo Ovídio" not in names
        assert "Santa Clara" not in names

    def test_nonsense_returns_nothing(self):
        assert metro.search_stations("xyzqwerty123") == []
