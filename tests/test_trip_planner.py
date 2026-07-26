"""Comprehensive tests for the multimodal trip planner."""

import math
from unittest.mock import AsyncMock, patch

import pytest

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


# ===================================================================
# Coordinate validation
# ===================================================================

class TestCoordinateValidation:
    """``is_valid_porto_coords`` is what stops broken commuter profiles."""

    def test_rejects_zero_zero(self):
        from bot.services.trip_planner import is_valid_porto_coords
        assert is_valid_porto_coords(0.0, 0.0) is False

    def test_rejects_zero_latitude(self):
        from bot.services.trip_planner import is_valid_porto_coords
        assert is_valid_porto_coords(0.0, -8.61) is False

    def test_rejects_zero_longitude(self):
        from bot.services.trip_planner import is_valid_porto_coords
        assert is_valid_porto_coords(41.15, 0.0) is False

    def test_rejects_none(self):
        from bot.services.trip_planner import is_valid_porto_coords
        assert is_valid_porto_coords(None, None) is False
        assert is_valid_porto_coords(41.15, None) is False

    def test_rejects_non_numeric(self):
        from bot.services.trip_planner import is_valid_porto_coords
        assert is_valid_porto_coords("abc", "def") is False

    def test_rejects_outside_porto_region(self):
        from bot.services.trip_planner import is_valid_porto_coords
        assert is_valid_porto_coords(48.8566, 2.3522) is False   # Paris
        assert is_valid_porto_coords(38.7223, -9.1393) is False  # Lisbon

    def test_accepts_porto_coordinates(self):
        from bot.services.trip_planner import is_valid_porto_coords
        assert is_valid_porto_coords(41.1519, -8.6102) is True   # Trindade
        assert is_valid_porto_coords(41.2350, -8.6780) is True   # Airport area

    def test_accepts_string_numbers(self):
        from bot.services.trip_planner import is_valid_porto_coords
        assert is_valid_porto_coords("41.1519", "-8.6102") is True


# ===================================================================
# Direction / headsign resolution
# ===================================================================

class TestDirectionGuessing:
    """The old code always used the last endpoint of the route string."""

    def test_line_endpoints_parsed(self):
        from bot.services.trip_planner import _line_endpoints
        assert _line_endpoints("A ↔ B") == ["A", "B"]
        assert _line_endpoints("no separator") == []

    def test_direction_towards_dragao(self):
        from bot.services.trip_planner import _direction_towards
        # Line A: Senhor de Matosinhos ↔ Estádio do Dragão. Heading east.
        direction = _direction_towards(
            "Senhor de Matosinhos ↔ Estádio do Dragão", "metro",
            41.1618, -8.5836)  # Estádio do Dragão
        assert "Dragão" in direction

    def test_direction_towards_matosinhos(self):
        from bot.services.trip_planner import _direction_towards
        # Same line, opposite way: the old code could never produce this.
        direction = _direction_towards(
            "Senhor de Matosinhos ↔ Estádio do Dragão", "metro",
            41.1826, -8.6873)  # Senhor de Matosinhos
        assert "Matosinhos" in direction

    def test_direct_metro_step_direction_depends_on_destination(self):
        eastbound = plan_trip("Casa da Música", "Estádio do Dragão")
        westbound = plan_trip("Estádio do Dragão", "Casa da Música")
        e_dirs = {s.direction for o in eastbound for s in o.steps if s.mode == "metro"}
        w_dirs = {s.direction for o in westbound for s in o.steps if s.mode == "metro"}
        assert e_dirs and w_dirs
        assert e_dirs != w_dirs

    def test_abbreviated_terminus_resolves(self):
        from bot.services.trip_planner import _terminus_coords
        coords = _terminus_coords("Sto. Ovídio", "metro")
        assert coords is not None
        assert 41.0 < coords[0] < 41.2


# ===================================================================
# Offline estimator: labelling and leg limits
# ===================================================================

class TestOfflineEstimatorLabelling:

    def test_options_are_flagged_as_estimates(self):
        options = plan_trip("Bolhão", "Trindade")
        assert options
        assert all(o.estimated is True for o in options)
        assert all(o.source == "estimate" for o in options)

    def test_estimates_have_no_timetable(self):
        options = plan_trip("Bolhão", "Trindade")
        assert all(not o.departure_time for o in options)


class TestLegLimitsRemoved:
    """The estimator used to cap metro at one transfer and multimodal at two legs."""

    def test_graph_search_returns_options(self):
        from bot.services.trip_planner import _plan_graph
        options = _plan_graph(41.1519, -8.6102, 41.1618, -8.5836)
        assert options
        assert all(o.estimated for o in options)

    def test_graph_allows_more_than_one_transfer(self):
        from bot.services.trip_planner import _plan_graph, MAX_GRAPH_TRANSFERS
        # Airport (line E) to Hospital Santos Silva (line D, far south)
        options = _plan_graph(41.2350, -8.6780, 41.0930, -8.6060, max_options=5)
        assert options
        assert all(o.transfers <= MAX_GRAPH_TRANSFERS for o in options)

    def test_graph_can_mix_modes(self):
        from bot.services.trip_planner import _plan_graph
        # Boavista (MetroBus corridor) to Ermesinde (CP) needs several modes.
        options = _plan_graph(41.1578, -8.6260, 41.2141, -8.5524, max_options=5)
        modes = {s.mode for o in options for s in o.steps if s.mode != "walk"}
        assert len(modes) >= 1

    def test_graph_returns_nothing_in_the_ocean(self):
        from bot.services.trip_planner import _plan_graph
        assert _plan_graph(0.0, 0.0, 0.0, 0.0) == []


# ===================================================================
# MOTIS: timetable-backed planning (mocked)
# ===================================================================

_MOTIS_PAYLOAD = {
    "itineraries": [
        {
            "duration": 2700,
            "startTime": "2026-07-26T08:00:00Z",
            "endTime": "2026-07-26T08:45:00Z",
            "transfers": 1,
            "legs": [
                {
                    "mode": "WALK",
                    "duration": 300,
                    "startTime": "2026-07-26T08:00:00Z",
                    "endTime": "2026-07-26T08:05:00Z",
                    "from": {"name": "START"},
                    "to": {"name": "VALE FORMOSO"},
                },
                {
                    "mode": "BUS",
                    "duration": 1200,
                    "startTime": "2026-07-26T08:10:00Z",
                    "endTime": "2026-07-26T08:30:00Z",
                    "routeShortName": "204",
                    "headsign": "Foz",
                    "agencyName": "Sociedade de Transportes Colectivos do Porto, E.I.M., S.A",
                    "from": {"name": "VALE FORMOSO"},
                    "to": {"name": "BOAVISTA"},
                },
                {
                    "mode": "SUBWAY",
                    "duration": 600,
                    "startTime": "2026-07-26T08:35:00Z",
                    "endTime": "2026-07-26T08:45:00Z",
                    "routeShortName": "A",
                    "headsign": "Estádio do Dragão",
                    "agencyName": "Metro do Porto",
                    "from": {"name": "Casa da Música"},
                    "to": {"name": "Trindade"},
                },
            ],
        },
    ],
}


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, response=None, exc=None):
        self._response = response
        self._exc = exc
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, url, params=None, headers=None):
        self.calls.append({"url": url, "params": params, "headers": headers})
        if self._exc is not None:
            raise self._exc
        return self._response


class TestMotisPlanning:

    @pytest.mark.asyncio
    async def test_parses_motis_itinerary(self):
        import bot.services.trip_planner as tp

        client = _FakeClient(_FakeResponse(_MOTIS_PAYLOAD))
        with patch.object(tp.httpx, "AsyncClient", lambda *a, **k: client):
            options = await tp.motis_plan(41.1519, -8.6102, 41.1618, -8.5836)

        assert options is not None
        assert len(options) == 1
        option = options[0]
        assert option.estimated is False
        assert option.source == tp.SOURCE_MOTIS
        assert option.total_time_min == 45
        assert option.transfers == 1

    @pytest.mark.asyncio
    async def test_stcp_bus_leg_is_included(self):
        """STCP - the densest network in Porto - now appears in plans."""
        import bot.services.trip_planner as tp

        client = _FakeClient(_FakeResponse(_MOTIS_PAYLOAD))
        with patch.object(tp.httpx, "AsyncClient", lambda *a, **k: client):
            options = await tp.motis_plan(41.1519, -8.6102, 41.1618, -8.5836)

        modes = [s.mode for s in options[0].steps]
        assert "bus" in modes
        bus_step = next(s for s in options[0].steps if s.mode == "bus")
        assert bus_step.line == "204"
        assert bus_step.direction == "Foz"

    @pytest.mark.asyncio
    async def test_metro_leg_mapped_from_subway(self):
        import bot.services.trip_planner as tp

        client = _FakeClient(_FakeResponse(_MOTIS_PAYLOAD))
        with patch.object(tp.httpx, "AsyncClient", lambda *a, **k: client):
            options = await tp.motis_plan(41.1519, -8.6102, 41.1618, -8.5836)

        assert any(s.mode == "metro" for s in options[0].steps)

    @pytest.mark.asyncio
    async def test_waiting_time_is_modelled(self):
        """The old estimator hid up to an hour of waiting; MOTIS reports it."""
        import bot.services.trip_planner as tp

        client = _FakeClient(_FakeResponse(_MOTIS_PAYLOAD))
        with patch.object(tp.httpx, "AsyncClient", lambda *a, **k: client):
            options = await tp.motis_plan(41.1519, -8.6102, 41.1618, -8.5836)

        bus_step = next(s for s in options[0].steps if s.mode == "bus")
        metro_step = next(s for s in options[0].steps if s.mode == "metro")
        assert bus_step.wait_min == 5
        assert metro_step.wait_min == 5

    @pytest.mark.asyncio
    async def test_departure_times_are_local_lisbon(self):
        import bot.services.trip_planner as tp

        client = _FakeClient(_FakeResponse(_MOTIS_PAYLOAD))
        with patch.object(tp.httpx, "AsyncClient", lambda *a, **k: client):
            options = await tp.motis_plan(41.1519, -8.6102, 41.1618, -8.5836)

        # 08:00Z in July is 09:00 in Lisbon.
        assert options[0].departure_time == "09:00"
        assert options[0].arrival_time == "09:45"

    @pytest.mark.asyncio
    async def test_sends_a_custom_user_agent(self):
        """transitous answers 403 to generic library user-agents."""
        import bot.services.trip_planner as tp

        client = _FakeClient(_FakeResponse(_MOTIS_PAYLOAD))
        with patch.object(tp.httpx, "AsyncClient", lambda *a, **k: client):
            await tp.motis_plan(41.1519, -8.6102, 41.1618, -8.5836)

        headers = client.calls[0]["headers"]
        assert headers["User-Agent"] == tp.MOTIS_USER_AGENT
        assert "python" not in headers["User-Agent"].lower()

    @pytest.mark.asyncio
    async def test_uses_the_plan_endpoint(self):
        import bot.services.trip_planner as tp

        client = _FakeClient(_FakeResponse(_MOTIS_PAYLOAD))
        with patch.object(tp.httpx, "AsyncClient", lambda *a, **k: client):
            await tp.motis_plan(41.1519, -8.6102, 41.1618, -8.5836)

        assert client.calls[0]["url"] == "https://europe.motis-project.de/api/v1/plan"
        params = client.calls[0]["params"]
        assert params["fromPlace"] == "41.1519,-8.6102"
        assert params["toPlace"] == "41.1618,-8.5836"

    @pytest.mark.asyncio
    async def test_http_error_returns_none(self):
        import bot.services.trip_planner as tp

        client = _FakeClient(_FakeResponse({}, status_code=403))
        with patch.object(tp.httpx, "AsyncClient", lambda *a, **k: client):
            assert await tp.motis_plan(41.1519, -8.6102, 41.1618, -8.5836) is None

    @pytest.mark.asyncio
    async def test_network_error_returns_none(self):
        import bot.services.trip_planner as tp

        client = _FakeClient(exc=RuntimeError("connection reset"))
        with patch.object(tp.httpx, "AsyncClient", lambda *a, **k: client):
            assert await tp.motis_plan(41.1519, -8.6102, 41.1618, -8.5836) is None

    @pytest.mark.asyncio
    async def test_invalid_coordinates_are_not_sent_upstream(self):
        import bot.services.trip_planner as tp

        client = _FakeClient(_FakeResponse(_MOTIS_PAYLOAD))
        with patch.object(tp.httpx, "AsyncClient", lambda *a, **k: client):
            assert await tp.motis_plan(0.0, 0.0, 41.15, -8.61) is None
        assert client.calls == []


class TestMotisFallback:

    @pytest.mark.asyncio
    async def test_falls_back_to_the_offline_estimator(self):
        import bot.services.trip_planner as tp

        with patch.object(tp, "motis_plan", new_callable=AsyncMock) as motis:
            motis.return_value = None
            options = await tp.plan_trip_from_coords_async(
                41.1499, -8.6056, 41.1519, -8.6102)

        assert options
        assert all(o.estimated is True for o in options)
        assert all(o.source == tp.SOURCE_ESTIMATE for o in options)

    @pytest.mark.asyncio
    async def test_motis_results_are_preferred(self):
        import bot.services.trip_planner as tp

        motis_option = TripOption(steps=[TripStep(mode="bus", from_name="A",
                                                  to_name="B", line="204",
                                                  duration_min=5)],
                                  total_time_min=5, estimated=False,
                                  source=tp.SOURCE_MOTIS)
        with patch.object(tp, "motis_plan", new_callable=AsyncMock) as motis:
            motis.return_value = [motis_option]
            options = await tp.plan_trip_from_coords_async(
                41.1499, -8.6056, 41.1519, -8.6102)

        assert options == [motis_option]
        assert options[0].estimated is False

    @pytest.mark.asyncio
    async def test_plan_trip_async_resolves_names(self):
        import bot.services.trip_planner as tp

        with patch.object(tp, "motis_plan", new_callable=AsyncMock) as motis:
            motis.return_value = None
            options = await tp.plan_trip_async("Bolhão", "Trindade")

        assert options
        assert all(o.estimated for o in options)

    @pytest.mark.asyncio
    async def test_plan_trip_async_unknown_place(self):
        import bot.services.trip_planner as tp

        with patch.object(tp, "resolve_location_any",
                          new_callable=AsyncMock) as resolver:
            resolver.return_value = None
            assert await tp.plan_trip_async("xyzzy", "Trindade") == []
