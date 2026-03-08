"""Tests for MetroBus (BRT) service."""

from datetime import datetime, time

from bot.services.metrobus import (
    search_stops,
    get_stop_info,
    get_next_departures,
    get_nearby_stops,
    get_all_lines,
    get_line_stops,
    get_frequency_info,
    get_stop_coordinates,
    _is_operating,
    _get_frequency_type,
    _haversine,
    STOPS,
    METROBUS_LINES,
    FREQUENCIES,
)


class TestSearchStops:
    def test_exact_match(self):
        results = search_stops("Rotunda da Boavista")
        assert len(results) >= 1
        assert results[0]["name"] == "Rotunda da Boavista"

    def test_partial_match(self):
        results = search_stops("boavi")
        assert len(results) >= 1
        assert any("Boavista" in r["name"] for r in results)

    def test_case_insensitive(self):
        results = search_stops("campanhã")
        assert len(results) >= 1
        assert any("Campanhã" in r["name"] for r in results)

    def test_no_match(self):
        results = search_stops("xyznonexistent")
        assert len(results) == 0

    def test_empty_query(self):
        results = search_stops("")
        assert len(results) == 0

    def test_results_have_lines(self):
        results = search_stops("Casa da Música")
        assert len(results) >= 1
        stop = results[0]
        assert len(stop["lines"]) > 0
        assert all("code" in l for l in stop["lines"])

    def test_limit_results(self):
        results = search_stops("a")  # matches many stops
        assert len(results) <= 15


class TestGetStopInfo:
    def test_known_stop(self):
        info = get_stop_info("Rotunda da Boavista")
        assert info is not None
        assert info["name"] == "Rotunda da Boavista"
        assert "lat" in info
        assert "lon" in info
        assert len(info["lines"]) > 0

    def test_unknown_stop(self):
        info = get_stop_info("Nonexistent Stop XYZ123")
        assert info is None

    def test_stop_has_route(self):
        info = get_stop_info("Rotunda da Boavista")
        assert info is not None
        for line in info["lines"]:
            assert "route" in line


class TestGetNextDepartures:
    def test_returns_departures(self):
        deps = get_next_departures("Rotunda da Boavista")
        # Should return something (either departures or closed message)
        assert len(deps) > 0

    def test_specific_line(self):
        deps = get_next_departures("Rotunda da Boavista", line_code="1")
        assert len(deps) > 0
        for d in deps:
            if d.get("line_code"):
                assert d["line_code"] == "1"

    def test_unknown_stop(self):
        deps = get_next_departures("Nonexistent")
        assert len(deps) == 0

    def test_departure_fields(self):
        deps = get_next_departures("Antas")
        assert len(deps) > 0
        dep = deps[0]
        assert "direction" in dep
        assert "time" in dep


class TestGetNearbyStops:
    def test_near_boavista(self):
        # Coordinates near Boavista area
        nearby = get_nearby_stops(41.1578, -8.6260, radius_km=0.5)
        assert len(nearby) > 0
        assert all("distance_m" in s for s in nearby)
        assert all("name" in s for s in nearby)

    def test_sorted_by_distance(self):
        nearby = get_nearby_stops(41.1578, -8.6260, radius_km=1.0)
        if len(nearby) >= 2:
            for i in range(len(nearby) - 1):
                assert nearby[i]["distance_m"] <= nearby[i + 1]["distance_m"]

    def test_no_nearby(self):
        # Coordinates far from Porto
        nearby = get_nearby_stops(0.0, 0.0, radius_km=0.5)
        assert len(nearby) == 0

    def test_max_results(self):
        # Very large radius to get many results
        nearby = get_nearby_stops(41.16, -8.62, radius_km=5.0)
        assert len(nearby) <= 10


class TestGetAllLines:
    def test_returns_all_lines(self):
        lines = get_all_lines()
        assert len(lines) == len(METROBUS_LINES)
        codes = {l["code"] for l in lines}
        assert codes == set(METROBUS_LINES.keys())

    def test_line_has_stop_count(self):
        lines = get_all_lines()
        for line in lines:
            assert "stop_count" in line
            assert line["stop_count"] > 0

    def test_line_has_info(self):
        lines = get_all_lines()
        for line in lines:
            assert "name" in line
            assert "emoji" in line
            assert "route" in line


class TestGetLineStops:
    def test_line_1(self):
        stops = get_line_stops("1")
        assert len(stops) >= 10
        assert any("Casa da Música" in s for s in stops)
        assert any("Matosinhos" in s for s in stops)

    def test_line_2(self):
        stops = get_line_stops("2")
        assert len(stops) >= 8
        assert any("Galiza" in s for s in stops)
        assert any("Antas" in s for s in stops)

    def test_line_3(self):
        stops = get_line_stops("3")
        assert len(stops) >= 8
        assert any("Campanhã" in s for s in stops)
        assert any("Ramalde" in s for s in stops)

    def test_invalid_line(self):
        stops = get_line_stops("99")
        assert len(stops) == 0


class TestGetFrequencyInfo:
    def test_line_1(self):
        freq = get_frequency_info("1")
        assert "peak" in freq
        assert "off_peak" in freq
        assert "weekend" in freq
        assert "hours" in freq
        assert "min" in freq["peak"]

    def test_all_lines(self):
        for code in METROBUS_LINES:
            freq = get_frequency_info(code)
            assert "peak" in freq
            assert "hours" in freq


class TestGetStopCoordinates:
    def test_known_stop(self):
        coords = get_stop_coordinates("Rotunda da Boavista")
        assert coords is not None
        assert "lat" in coords
        assert "lon" in coords
        assert 41.0 < coords["lat"] < 42.0
        assert -9.0 < coords["lon"] < -8.0

    def test_unknown_stop(self):
        coords = get_stop_coordinates("Nonexistent XYZ")
        assert coords is None


class TestIsOperating:
    def test_morning(self):
        assert _is_operating(time(8, 0))

    def test_evening(self):
        assert _is_operating(time(22, 0))

    def test_late_night(self):
        assert _is_operating(time(0, 30))

    def test_early_morning_closed(self):
        assert not _is_operating(time(3, 0))

    def test_before_opening(self):
        assert not _is_operating(time(5, 0))


class TestGetFrequencyType:
    def test_weekday_peak(self):
        # Monday 8am
        dt = datetime(2026, 3, 2, 8, 0)
        assert _get_frequency_type(dt) == "peak"

    def test_weekday_off_peak(self):
        # Monday 14pm
        dt = datetime(2026, 3, 2, 14, 0)
        assert _get_frequency_type(dt) == "off_peak"

    def test_weekend(self):
        # Saturday
        dt = datetime(2026, 3, 7, 10, 0)
        assert _get_frequency_type(dt) == "weekend"


class TestHaversine:
    def test_same_point(self):
        dist = _haversine(41.15, -8.61, 41.15, -8.61)
        assert dist == 0.0

    def test_known_distance(self):
        # Approximate distance between two nearby Porto points
        dist = _haversine(41.1585, -8.6305, 41.1578, -8.6260)
        assert 0.1 < dist < 1.0  # Should be a few hundred meters


class TestStopsData:
    def test_all_stops_have_lines(self):
        for name, data in STOPS.items():
            assert "lines" in data, f"Stop {name} missing lines"
            assert len(data["lines"]) > 0, f"Stop {name} has no lines"

    def test_all_lines_referenced_exist(self):
        for name, data in STOPS.items():
            for line in data["lines"]:
                assert line in METROBUS_LINES, (
                    f"Stop {name} references unknown line {line}"
                )

    def test_all_stops_have_zone(self):
        for name, data in STOPS.items():
            assert "zone" in data, f"Stop {name} missing zone"

    def test_all_stops_have_coordinates(self):
        for name, data in STOPS.items():
            assert "lat" in data, f"Stop {name} missing lat"
            assert "lon" in data, f"Stop {name} missing lon"
            assert 41.0 < data["lat"] < 42.0, f"Stop {name} lat out of range"
            assert -9.0 < data["lon"] < -8.0, f"Stop {name} lon out of range"

    def test_frequencies_cover_all_lines(self):
        for freq_type in ("peak", "off_peak", "weekend"):
            for line_code in METROBUS_LINES:
                assert line_code in FREQUENCIES[freq_type], (
                    f"Missing {freq_type} frequency for line {line_code}"
                )
