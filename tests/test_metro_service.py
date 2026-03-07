"""Tests for Metro do Porto service."""

from datetime import datetime, time

from bot.services.metro import (
    search_stations,
    get_station_lines,
    get_next_departures,
    get_line_stations,
    get_all_lines,
    get_frequency_info,
    _is_operating,
    _get_frequency_type,
    STATIONS,
    METRO_LINES,
)


class TestSearchStations:
    def test_exact_match(self):
        results = search_stations("Trindade")
        assert len(results) >= 1
        assert results[0]["name"] == "Trindade"

    def test_partial_match(self):
        results = search_stations("bolh")
        assert len(results) >= 1
        assert any("Bolhão" in r["name"] for r in results)

    def test_case_insensitive(self):
        results = search_stations("trindade")
        assert len(results) >= 1
        assert results[0]["name"] == "Trindade"

    def test_no_match(self):
        results = search_stations("xyznonexistent")
        assert len(results) == 0

    def test_results_have_lines(self):
        results = search_stations("Casa da Música")
        assert len(results) >= 1
        station = results[0]
        assert len(station["lines"]) > 0
        assert all("code" in l for l in station["lines"])

    def test_limit_results(self):
        results = search_stations("a")  # matches many stations
        assert len(results) <= 15


class TestGetStationLines:
    def test_trindade_is_hub(self):
        lines = get_station_lines("Trindade")
        assert len(lines) >= 4  # Trindade is a major hub
        codes = {l["code"] for l in lines}
        assert "A" in codes
        assert "D" in codes

    def test_unknown_station(self):
        lines = get_station_lines("Nonexistent Station")
        assert len(lines) == 0

    def test_line_has_info(self):
        lines = get_station_lines("Trindade")
        for line in lines:
            assert "code" in line
            assert "name" in line
            assert "emoji" in line


class TestGetNextDepartures:
    def test_returns_departures(self):
        deps = get_next_departures("Trindade")
        # Should return something (either departures or closed message)
        assert len(deps) > 0

    def test_specific_line(self):
        deps = get_next_departures("Trindade", line_code="A")
        assert len(deps) > 0
        # All departures should be for line A
        for d in deps:
            if d.get("line_code"):
                assert d["line_code"] == "A"

    def test_unknown_station(self):
        deps = get_next_departures("Nonexistent")
        assert len(deps) == 0


class TestGetLineStations:
    def test_line_a(self):
        stations = get_line_stations("A")
        assert len(stations) > 5
        assert any("Matosinhos" in s for s in stations)

    def test_line_d(self):
        stations = get_line_stations("D")
        assert len(stations) > 5
        assert any("São Bento" in s for s in stations)


class TestGetAllLines:
    def test_returns_all_lines(self):
        lines = get_all_lines()
        assert len(lines) == len(METRO_LINES)
        codes = {l["code"] for l in lines}
        assert codes == set(METRO_LINES.keys())

    def test_line_has_station_count(self):
        lines = get_all_lines()
        for line in lines:
            assert "station_count" in line
            assert line["station_count"] > 0


class TestGetFrequencyInfo:
    def test_line_a(self):
        freq = get_frequency_info("A")
        assert "peak" in freq
        assert "off_peak" in freq
        assert "weekend" in freq
        assert "hours" in freq
        assert "min" in freq["peak"]


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


class TestStationsData:
    def test_all_stations_have_lines(self):
        for name, data in STATIONS.items():
            assert "lines" in data, f"Station {name} missing lines"
            assert len(data["lines"]) > 0, f"Station {name} has no lines"

    def test_all_lines_referenced_exist(self):
        for name, data in STATIONS.items():
            for line in data["lines"]:
                assert line in METRO_LINES, (
                    f"Station {name} references unknown line {line}"
                )

    def test_all_stations_have_zone(self):
        for name, data in STATIONS.items():
            assert "zone" in data, f"Station {name} missing zone"
