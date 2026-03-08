"""Comprehensive tests for the multimodal trip planner."""

import math

from bot.services.trip_planner import (
    TripOption,
    TripStep,
    _haversine,
    _walk_time,
    _ride_time,
    resolve_location,
    plan_trip,
    plan_trip_from_coords,
    _get_nearby_all,
    _collect_zones,
    _build_direct_metro,
    _build_metro_with_transfer,
    _build_direct_train,
    _build_direct_metrobus,
    _find_common_metro_lines,
    _find_metro_transfer_station,
)
from bot.services.metro import STATIONS as METRO_STATIONS
from bot.services.cp import STATIONS as CP_STATIONS
from bot.services.metrobus import STOPS as METROBUS_STOPS


class TestResolveLocation:
    """Test location resolution from text queries."""

    def test_resolve_metro_station(self):
        result = resolve_location("Trindade")
        assert result is not None
        assert result["name"] == "Trindade"
        assert result["type"] == "metro"
        assert "lat" in result
        assert "lon" in result

    def test_resolve_metro_station_fuzzy(self):
        result = resolve_location("bolhao")
        assert result is not None
        assert result["name"] == "Bolhão"
        assert result["type"] == "metro"

    def test_resolve_train_station(self):
        result = resolve_location("Ermesinde")
        # This could match metro or CP; it appears in CP_STATIONS
        assert result is not None
        assert "lat" in result
        assert "lon" in result

    def test_resolve_metrobus_stop(self):
        result = resolve_location("Rotunda da Boavista")
        assert result is not None
        assert result["type"] == "metrobus"
        assert result["name"] == "Rotunda da Boavista"

    def test_resolve_unknown(self):
        result = resolve_location("xyznonexistent12345")
        assert result is None

    def test_resolve_empty_string(self):
        result = resolve_location("")
        assert result is None

    def test_resolve_none(self):
        result = resolve_location(None)
        assert result is None

    def test_resolve_returns_coordinates(self):
        result = resolve_location("Casa da Música")
        assert result is not None
        # Casa da Musica is a metro station
        assert abs(result["lat"] - 41.1585) < 0.01
        assert abs(result["lon"] - (-8.6305)) < 0.01


class TestDirectMetroRouting:
    """Test direct metro routes (same line)."""

    def test_same_line_route(self):
        # Bolhão and Trindade are both on lines A, B, C, E
        options = plan_trip("Bolhão", "Trindade")
        assert len(options) > 0
        # Should find at least a direct metro option
        direct = [o for o in options if o.transfers == 0]
        assert len(direct) > 0

    def test_direct_metro_has_correct_steps(self):
        options = plan_trip("Bolhão", "Trindade")
        assert len(options) > 0
        option = options[0]
        # Should have metro step(s), possibly walk steps
        metro_steps = [s for s in option.steps if s.mode == "metro"]
        assert len(metro_steps) >= 1

    def test_direct_metro_time_reasonable(self):
        options = plan_trip("Bolhão", "Trindade")
        assert len(options) > 0
        # Bolhão to Trindade is very close, should be under 15 min total
        assert options[0].total_time_min < 15


class TestMetroWithTransfer:
    """Test metro routes requiring transfers."""

    def test_different_lines_requires_transfer(self):
        # Hospital de São João (line D) to Senhor de Matosinhos (line A)
        # These don't share a line, so need a transfer at Trindade or Casa da Música
        options = plan_trip("Hospital de São João", "Senhor de Matosinhos")
        assert len(options) > 0
        # At least one option should have a transfer
        transfer_opts = [o for o in options if o.transfers >= 1]
        assert len(transfer_opts) > 0

    def test_transfer_station_found(self):
        origin_lines = {"D"}
        dest_lines = {"A"}
        result = _find_metro_transfer_station(
            "Hospital de São João", origin_lines,
            "Senhor de Matosinhos", dest_lines,
        )
        assert result is not None
        transfer_name, line_from, line_to = result
        assert transfer_name in METRO_STATIONS
        assert line_from == "D"
        assert line_to in dest_lines


class TestMultimodalRoutes:
    """Test multimodal route combinations."""

    def test_metro_plan_returns_options(self):
        # Both are metro stations on different lines
        options = plan_trip("Aeroporto", "São Bento")
        assert isinstance(options, list)
        # Should find at least one option
        assert len(options) > 0

    def test_plan_between_cp_stations(self):
        # Both are CP stations
        options = plan_trip("Porto-Campanhã", "Braga")
        assert isinstance(options, list)
        # Porto-Campanhã is both a metro and CP station area
        # Should find at least one route
        assert len(options) > 0


class TestWalkingTimeEstimation:
    """Test walking time calculations."""

    def test_walk_time_short(self):
        # 100m = 0.1km -> ~1.25 min -> rounds to 1
        assert _walk_time(0.1) == 1

    def test_walk_time_medium(self):
        # 500m = 0.5km -> ~6.25 min -> rounds to 6
        result = _walk_time(0.5)
        assert 5 <= result <= 8

    def test_walk_time_long(self):
        # 1km -> ~12.5 min
        result = _walk_time(1.0)
        assert 10 <= result <= 15

    def test_walk_time_zero(self):
        # Very short distance should be at least 1 min
        assert _walk_time(0.0) >= 1


class TestTripTimeEstimation:
    """Test ride time estimates."""

    def test_metro_ride_time(self):
        # 3 km at 30 km/h -> 6 min
        result = _ride_time(3.0, "metro")
        assert result == 6

    def test_train_ride_time(self):
        # 10 km at 50 km/h -> 12 min
        result = _ride_time(10.0, "train")
        assert result == 12

    def test_metrobus_ride_time(self):
        # 2 km at 20 km/h -> 6 min
        result = _ride_time(2.0, "metrobus")
        assert result == 6

    def test_minimum_ride_time(self):
        # Very short distance should be at least 1 min
        assert _ride_time(0.01, "metro") >= 1


class TestCoordinateBasedPlanning:
    """Test planning from coordinates."""

    def test_plan_from_coords_trindade_to_bolhao(self):
        # Trindade coords
        o_lat, o_lon = 41.1519, -8.6102
        # Bolhão coords
        d_lat, d_lon = 41.1499, -8.6056
        options = plan_trip_from_coords(o_lat, o_lon, d_lat, d_lon)
        assert len(options) > 0
        assert options[0].total_time_min > 0

    def test_plan_from_coords_no_nearby(self):
        # Middle of the ocean - no nearby stops
        options = plan_trip_from_coords(0.0, 0.0, 0.0, 0.0)
        assert options == []

    def test_plan_from_coords_returns_sorted(self):
        # Campanhã to Casa da Música
        o_lat, o_lon = 41.1487, -8.5853
        d_lat, d_lon = 41.1585, -8.6305
        options = plan_trip_from_coords(o_lat, o_lon, d_lat, d_lon)
        if len(options) > 1:
            for i in range(len(options) - 1):
                assert options[i].total_time_min <= options[i + 1].total_time_min


class TestErrorHandling:
    """Test error handling edge cases."""

    def test_unknown_origin(self):
        options = plan_trip("xyznonexistent", "Trindade")
        assert options == []

    def test_unknown_destination(self):
        options = plan_trip("Trindade", "xyznonexistent")
        assert options == []

    def test_both_unknown(self):
        options = plan_trip("xyzfoo", "xyzbar")
        assert options == []

    def test_empty_strings(self):
        options = plan_trip("", "")
        assert options == []


class TestHaversine:
    """Test haversine distance calculation."""

    def test_same_point(self):
        dist = _haversine(41.15, -8.61, 41.15, -8.61)
        assert dist == 0.0

    def test_known_distance(self):
        # Trindade to Bolhão ~ about 0.5 km
        dist = _haversine(41.1519, -8.6102, 41.1499, -8.6056)
        assert 0.3 < dist < 0.8

    def test_longer_distance(self):
        # Porto to Braga ~ about 50km
        dist = _haversine(41.15, -8.61, 41.55, -8.43)
        assert 40 < dist < 60


class TestGetNearbyAll:
    """Test finding nearby transport nodes."""

    def test_finds_metro_near_trindade(self):
        nodes = _get_nearby_all(41.1519, -8.6102, radius_km=0.3)
        metro_nodes = [n for n in nodes if n["type"] == "metro"]
        assert len(metro_nodes) > 0
        names = [n["name"] for n in metro_nodes]
        assert "Trindade" in names

    def test_nodes_sorted_by_distance(self):
        nodes = _get_nearby_all(41.1519, -8.6102, radius_km=1.0)
        for i in range(len(nodes) - 1):
            assert nodes[i]["dist_km"] <= nodes[i + 1]["dist_km"]

    def test_no_nodes_in_ocean(self):
        nodes = _get_nearby_all(0.0, 0.0, radius_km=1.0)
        assert nodes == []


class TestCollectZones:
    """Test zone collection."""

    def test_collect_zones(self):
        n1 = {"zone": "PRT"}
        n2 = {"zone": "MTS"}
        zones = _collect_zones(n1, n2)
        assert "PRT" in zones
        assert "MTS" in zones

    def test_collect_zones_no_duplicates(self):
        n1 = {"zone": "PRT"}
        n2 = {"zone": "PRT"}
        zones = _collect_zones(n1, n2)
        assert zones == ["PRT"]

    def test_collect_zones_empty(self):
        n1 = {"zone": ""}
        zones = _collect_zones(n1)
        assert zones == []


class TestTripOptionDataclass:
    """Test TripOption and TripStep dataclasses."""

    def test_trip_step_creation(self):
        step = TripStep(mode="metro", from_name="A", to_name="B",
                        line="Linha Azul", duration_min=5, direction="X")
        assert step.mode == "metro"
        assert step.duration_min == 5

    def test_trip_option_defaults(self):
        opt = TripOption()
        assert opt.steps == []
        assert opt.total_time_min == 0
        assert opt.transfers == 0
        assert opt.zones == []

    def test_trip_option_with_steps(self):
        steps = [
            TripStep(mode="walk", from_name="", to_name="Station", duration_min=3),
            TripStep(mode="metro", from_name="Station", to_name="End",
                     line="Linha A", duration_min=10),
        ]
        opt = TripOption(steps=steps, total_time_min=13, transfers=0, zones=["PRT"])
        assert len(opt.steps) == 2
        assert opt.total_time_min == 13


class TestBuildDirectRoutes:
    """Test building direct single-mode routes."""

    def test_build_direct_metro(self):
        origin = {
            "name": "Bolhão", "lat": 41.1499, "lon": -8.6056,
            "type": "metro", "lines": ["A", "B", "C", "E"], "zone": "PRT",
        }
        dest = {
            "name": "Trindade", "lat": 41.1519, "lon": -8.6102,
            "type": "metro", "lines": ["A", "B", "C", "D", "E", "F"], "zone": "PRT",
        }
        result = _build_direct_metro(origin, dest, 0, 0)
        assert result is not None
        assert result.transfers == 0
        assert result.total_time_min > 0
        metro_steps = [s for s in result.steps if s.mode == "metro"]
        assert len(metro_steps) == 1

    def test_build_direct_metro_no_common_line(self):
        origin = {
            "name": "Senhor de Matosinhos", "lat": 41.1826, "lon": -8.6873,
            "type": "metro", "lines": ["A"], "zone": "MTS",
        }
        dest = {
            "name": "Hospital de São João", "lat": 41.1856, "lon": -8.6020,
            "type": "metro", "lines": ["D"], "zone": "PRT",
        }
        result = _build_direct_metro(origin, dest, 0, 0)
        assert result is None

    def test_build_direct_train(self):
        origin = {
            "name": "Porto-Campanhã", "lat": 41.1489, "lon": -8.5856,
            "type": "train", "lines": ["braga"], "zone": "",
        }
        dest = {
            "name": "Braga", "lat": 41.5495, "lon": -8.4340,
            "type": "train", "lines": ["braga"], "zone": "",
        }
        result = _build_direct_train(origin, dest, 0, 0)
        assert result is not None
        assert result.transfers == 0
        train_steps = [s for s in result.steps if s.mode == "train"]
        assert len(train_steps) == 1

    def test_build_direct_metrobus(self):
        origin = {
            "name": "Casa da Música (MetroBus)", "lat": 41.1585, "lon": -8.6305,
            "type": "metrobus", "lines": ["1"], "zone": "PRT",
        }
        dest = {
            "name": "Matosinhos (MetroBus)", "lat": 41.1820, "lon": -8.6750,
            "type": "metrobus", "lines": ["1"], "zone": "MTS",
        }
        result = _build_direct_metrobus(origin, dest, 0, 0)
        assert result is not None
        assert result.transfers == 0


class TestFindCommonMetroLines:
    """Test helper for finding common metro lines."""

    def test_common_lines(self):
        result = _find_common_metro_lines(["A", "B", "C"], ["B", "C", "D"])
        assert "B" in result
        assert "C" in result

    def test_no_common_lines(self):
        result = _find_common_metro_lines(["A"], ["D"])
        assert result == []
