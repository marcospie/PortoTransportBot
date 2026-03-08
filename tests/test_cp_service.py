"""Tests for CP Comboios de Portugal service."""

from datetime import datetime, time

from bot.services.cp import (
    search_stations,
    get_station_info,
    get_next_departures,
    get_nearby_stations,
    get_all_lines,
    get_line_stations,
    get_frequency_info,
    _is_operating,
    _get_frequency_type,
    _haversine,
    STATIONS,
    CP_LINES,
    FREQUENCIES,
)


class TestSearchStations:
    def test_exact_match(self):
        results = search_stations("Porto-Campanha")
        assert len(results) >= 1
        assert results[0]["name"] == "Porto-Campanha"

    def test_partial_match(self):
        results = search_stations("campanha")
        assert len(results) >= 1
        assert any("Campanha" in r["name"] for r in results)

    def test_case_insensitive(self):
        results = search_stations("ermesinde")
        assert len(results) >= 1
        assert results[0]["name"] == "Ermesinde"

    def test_no_match(self):
        results = search_stations("xyznonexistent")
        assert len(results) == 0

    def test_empty_query(self):
        results = search_stations("")
        assert len(results) == 0

    def test_results_have_lines(self):
        results = search_stations("Porto-Campanha")
        assert len(results) >= 1
        station = results[0]
        assert len(station["lines"]) > 0
        assert all("id" in l for l in station["lines"])
        assert all("name" in l for l in station["lines"])
        assert all("emoji" in l for l in station["lines"])

    def test_results_have_coordinates(self):
        results = search_stations("Espinho")
        assert len(results) >= 1
        station = results[0]
        assert "lat" in station
        assert "lon" in station
        assert station["lat"] != 0
        assert station["lon"] != 0


class TestGetStationInfo:
    def test_campanha_info(self):
        info = get_station_info("Porto-Campanha")
        assert info is not None
        assert info["name"] == "Porto-Campanha"
        assert len(info["lines"]) >= 4  # Campanha is the main hub
        assert info["lat"] != 0
        assert info["lon"] != 0

    def test_lines_have_details(self):
        info = get_station_info("Porto-Campanha")
        assert info is not None
        for line in info["lines"]:
            assert "id" in line
            assert "name" in line
            assert "emoji" in line
            assert "route" in line
            assert "type" in line

    def test_unknown_station(self):
        info = get_station_info("Nonexistent Station XYZ")
        assert info is None

    def test_fuzzy_match(self):
        info = get_station_info("campanha")
        assert info is not None
        assert "Campanha" in info["name"]


class TestGetNextDepartures:
    def test_returns_departures(self):
        deps = get_next_departures("Porto-Campanha")
        # Should return something (either departures or closed message)
        assert len(deps) > 0

    def test_specific_line(self):
        deps = get_next_departures("Porto-Campanha", line_id="aveiro")
        assert len(deps) > 0
        for d in deps:
            if d.get("line_id"):
                assert d["line_id"] == "aveiro"

    def test_unknown_station(self):
        deps = get_next_departures("Nonexistent Station XYZ")
        assert len(deps) == 0

    def test_departure_has_fields(self):
        deps = get_next_departures("Ermesinde")
        assert len(deps) > 0
        dep = deps[0]
        assert "direction" in dep
        assert "time" in dep
        assert "line" in dep


class TestGetNearbyStations:
    def test_near_campanha(self):
        # Porto-Campanha coordinates
        nearby = get_nearby_stations(41.1489, -8.5856, radius_km=1.0)
        assert len(nearby) >= 1
        names = [s["name"] for s in nearby]
        assert "Porto-Campanha" in names

    def test_sorted_by_distance(self):
        nearby = get_nearby_stations(41.1489, -8.5856, radius_km=5.0)
        if len(nearby) >= 2:
            for i in range(len(nearby) - 1):
                assert nearby[i]["distance_m"] <= nearby[i + 1]["distance_m"]

    def test_no_nearby(self):
        # Middle of Atlantic Ocean
        nearby = get_nearby_stations(0.0, -30.0, radius_km=1.0)
        assert len(nearby) == 0

    def test_nearby_has_fields(self):
        nearby = get_nearby_stations(41.1489, -8.5856, radius_km=1.0)
        assert len(nearby) >= 1
        station = nearby[0]
        assert "name" in station
        assert "distance_m" in station
        assert "lines" in station
        assert "lat" in station
        assert "lon" in station


class TestGetAllLines:
    def test_returns_all_lines(self):
        lines = get_all_lines()
        assert len(lines) == len(CP_LINES)
        ids = {l["id"] for l in lines}
        assert ids == set(CP_LINES.keys())

    def test_line_has_station_count(self):
        lines = get_all_lines()
        for line in lines:
            assert "station_count" in line
            assert line["station_count"] > 0

    def test_line_has_type(self):
        lines = get_all_lines()
        for line in lines:
            assert "type" in line
            assert line["type"] in ("urbano", "regional")


class TestGetLineStations:
    def test_aveiro_line(self):
        stations = get_line_stations("aveiro")
        assert len(stations) > 3
        assert any("Campanha" in s for s in stations)
        assert any("Espinho" in s for s in stations)
        assert any("Aveiro" in s for s in stations)

    def test_braga_line(self):
        stations = get_line_stations("braga")
        assert len(stations) > 3
        assert any("Bento" in s for s in stations)
        assert any("Braga" in s for s in stations)

    def test_unknown_line(self):
        stations = get_line_stations("nonexistent")
        assert len(stations) == 0


class TestGetFrequencyInfo:
    def test_aveiro_freq(self):
        freq = get_frequency_info("aveiro")
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
        assert _is_operating(time(0, 15))

    def test_early_morning_closed(self):
        assert not _is_operating(time(3, 0))

    def test_before_opening(self):
        assert not _is_operating(time(4, 0))


class TestGetFrequencyType:
    def test_weekday_peak(self):
        dt = datetime(2026, 3, 2, 8, 0)  # Monday 8am
        assert _get_frequency_type(dt) == "peak"

    def test_weekday_off_peak(self):
        dt = datetime(2026, 3, 2, 14, 0)  # Monday 2pm
        assert _get_frequency_type(dt) == "off_peak"

    def test_weekend(self):
        dt = datetime(2026, 3, 7, 10, 0)  # Saturday
        assert _get_frequency_type(dt) == "weekend"


class TestHaversine:
    def test_same_point(self):
        assert _haversine(41.0, -8.0, 41.0, -8.0) == 0.0

    def test_known_distance(self):
        # Porto-Campanha to Ermesinde: roughly 7-8 km
        dist = _haversine(41.1489, -8.5856, 41.2141, -8.5524)
        assert 5 < dist < 10


class TestStationsData:
    def test_all_stations_have_lines(self):
        for name, data in STATIONS.items():
            assert "lines" in data, f"Station {name} missing lines"
            assert len(data["lines"]) > 0, f"Station {name} has no lines"

    def test_all_lines_referenced_exist(self):
        for name, data in STATIONS.items():
            for line in data["lines"]:
                assert line in CP_LINES, (
                    f"Station {name} references unknown line {line}"
                )

    def test_all_stations_have_coordinates(self):
        for name, data in STATIONS.items():
            assert "lat" in data, f"Station {name} missing lat"
            assert "lon" in data, f"Station {name} missing lon"
            assert data["lat"] != 0, f"Station {name} has zero lat"
            assert data["lon"] != 0, f"Station {name} has zero lon"

    def test_campanha_is_hub(self):
        """Porto-Campanha should serve multiple lines as it's the main station."""
        data = STATIONS.get("Porto-Campanha")
        assert data is not None
        assert len(data["lines"]) >= 4


class TestKeyboards:
    def test_trains_menu_keyboard(self):
        from bot.keyboards.inline import trains_menu_keyboard
        kb = trains_menu_keyboard("pt")
        assert kb is not None
        assert len(kb.inline_keyboard) >= 2

    def test_train_station_results_keyboard(self):
        from bot.keyboards.inline import train_station_results_keyboard
        stations = search_stations("Porto")
        kb = train_station_results_keyboard(stations, "pt")
        assert kb is not None
        assert len(kb.inline_keyboard) >= 1

    def test_train_lines_keyboard(self):
        from bot.keyboards.inline import train_lines_keyboard
        kb = train_lines_keyboard("pt")
        assert kb is not None
        # Should have line buttons + back button
        assert len(kb.inline_keyboard) >= 2

    def test_train_station_actions_keyboard(self):
        from bot.keyboards.inline import train_station_actions_keyboard
        kb = train_station_actions_keyboard("Porto-Campanha", is_fav=False, lang="pt")
        assert kb is not None
        assert len(kb.inline_keyboard) >= 3
