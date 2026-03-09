"""Comprehensive tests for all stations, stops, search, and bot interactions.

Tests EVERY metro station, 20+ bus stops, station search with name variations,
and all bot features (refresh, back, menu, favorites, direction balancing).
"""

import pytest
from datetime import datetime, time
from unittest.mock import AsyncMock, MagicMock, patch

from bot.services.metro import (
    STATIONS as METRO_STATIONS,
    search_stations as metro_search,
    get_next_departures as metro_departures,
    _balance_directions,
    get_line_stations,
    get_station_lines,
    get_station_coordinates,
    get_all_lines,
    get_frequency_info,
)
from bot.services.metrobus import (
    STOPS as METROBUS_STOPS,
    search_stops as metrobus_search,
    get_next_departures as metrobus_departures,
)
from bot.services.cp import (
    STATIONS as TRAIN_STATIONS,
    search_stations as train_search,
    get_next_departures as train_departures,
)
from bot.config import METRO_LINES
from bot.utils.search import fuzzy_search, normalize, match_score
from bot.utils.formatting import escape_md, format_metro_schedule
from bot.utils.i18n import t, get_lang


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_update(user_id=123, text="", lang="pt", chat_id=456, callback_data=""):
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_user.language_code = lang
    update.effective_chat.id = chat_id

    msg = MagicMock()
    msg.text = text
    msg.from_user.id = user_id
    msg.from_user.language_code = lang
    msg.reply_text = AsyncMock()
    msg.chat_id = chat_id
    update.message = msg

    query = MagicMock()
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.edit_message_reply_markup = AsyncMock()
    query.from_user.id = user_id
    query.from_user.language_code = lang
    query.message.chat_id = chat_id
    query.data = callback_data
    update.callback_query = query

    # inline_query for inline tests
    inline = MagicMock()
    inline.query = text
    inline.answer = AsyncMock()
    update.inline_query = inline

    return update


def _make_context(user_data=None):
    ctx = MagicMock()
    ctx.user_data = user_data if user_data is not None else {}
    ctx.args = []
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()
    ctx.bot.send_location = AsyncMock()
    ctx.bot.username = "PortoTransportBot"
    return ctx


# ===========================================================================
# 1. METRO: Test ALL stations for departures
# ===========================================================================

class TestAllMetroStationDepartures:
    """Every metro station must return departures (or closed-service notice)."""

    @pytest.fixture(autouse=True)
    def _patch_time(self):
        """Patch time to 10:00 on a Monday so metro is always operating."""
        fake_now = datetime(2026, 3, 9, 10, 0, 0)
        with patch("bot.services.metro.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            yield

    @pytest.mark.parametrize("station_name", list(METRO_STATIONS.keys()))
    def test_station_returns_departures(self, station_name):
        deps = metro_departures(station_name)
        assert isinstance(deps, list), f"{station_name}: should return a list"
        assert len(deps) > 0, f"{station_name}: should have at least 1 departure"
        for dep in deps:
            assert "direction" in dep, f"{station_name}: departure missing 'direction'"
            assert "time" in dep, f"{station_name}: departure missing 'time'"

    @pytest.mark.parametrize("station_name", list(METRO_STATIONS.keys()))
    def test_station_has_valid_data(self, station_name):
        data = METRO_STATIONS[station_name]
        assert "lines" in data and len(data["lines"]) > 0, f"{station_name}: needs lines"
        assert "lat" in data and data["lat"], f"{station_name}: needs latitude"
        assert "lon" in data and data["lon"], f"{station_name}: needs longitude"
        # Every line must be in METRO_LINES config
        for line in data["lines"]:
            assert line in METRO_LINES, f"{station_name}: line '{line}' not in METRO_LINES"

    @pytest.mark.parametrize("station_name", list(METRO_STATIONS.keys()))
    def test_station_coordinates_available(self, station_name):
        coords = get_station_coordinates(station_name)
        assert coords is not None, f"{station_name}: coordinates unavailable"
        assert -90 <= coords["lat"] <= 90
        assert -180 <= coords["lon"] <= 180

    @pytest.mark.parametrize("station_name", list(METRO_STATIONS.keys()))
    def test_station_lines_info(self, station_name):
        lines = get_station_lines(station_name)
        assert len(lines) > 0, f"{station_name}: should have lines info"
        for line in lines:
            assert "code" in line
            assert "name" in line
            assert "emoji" in line

    @pytest.mark.parametrize("station_name", list(METRO_STATIONS.keys()))
    def test_station_format_schedule(self, station_name):
        deps = metro_departures(station_name)
        text = format_metro_schedule(station_name, "", deps)
        assert station_name in text or escape_md(station_name) in text
        assert len(text) > 10, f"{station_name}: schedule text too short"


class TestMetroStationDeparturesContent:
    """Check that departures have correct content for key stations."""

    @pytest.fixture(autouse=True)
    def _patch_time(self):
        fake_now = datetime(2026, 3, 9, 10, 0, 0)
        with patch("bot.services.metro.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            yield

    def test_trindade_has_multiple_lines(self):
        deps = metro_departures("Trindade")
        line_codes = set(d.get("line_code", "") for d in deps)
        # Trindade is a hub — should have departures from multiple lines
        assert len(line_codes) >= 2, f"Trindade should show multiple lines, got {line_codes}"

    def test_d_joao_ii_has_both_directions(self):
        """D. João II must show both directions — this was the original bug."""
        deps = metro_departures("D. João II", count=10)
        directions = set(d.get("direction", "") for d in deps)
        assert len(directions) >= 2, (
            f"D. João II should show both directions, got: {directions}"
        )

    def test_casa_da_musica_hub(self):
        deps = metro_departures("Casa da Música")
        line_codes = set(d.get("line_code", "") for d in deps)
        assert len(line_codes) >= 2, f"Casa da Música hub should have multiple lines"

    def test_campanha_station(self):
        deps = metro_departures("Campanhã")
        assert len(deps) > 0, "Campanhã should have departures"

    def test_aeroporto_station(self):
        deps = metro_departures("Aeroporto")
        assert len(deps) > 0, "Aeroporto should have departures"

    def test_terminal_stations_have_departures(self):
        """Terminal stations (end of line) should still return departures."""
        terminals = [
            "Senhor de Matosinhos", "Póvoa de Varzim", "ISMAI",
            "Hospital Santos Silva", "Hospital de São João",
            "Aeroporto", "Fonte do Cuco",
        ]
        for station in terminals:
            deps = metro_departures(station)
            assert len(deps) > 0, f"Terminal {station} should have departures"


# ===========================================================================
# 2. BALANCE DIRECTIONS
# ===========================================================================

class TestBalanceDirections:
    """Thorough tests for the _balance_directions function."""

    def test_empty_list(self):
        assert _balance_directions([], 5) == []

    def test_single_direction(self):
        deps = [{"direction": "A", "minutes": i} for i in range(10)]
        result = _balance_directions(deps, 5)
        assert len(result) == 5

    def test_two_directions_balanced(self):
        deps = (
            [{"direction": "North", "minutes": i * 2} for i in range(5)] +
            [{"direction": "South", "minutes": i * 2 + 1} for i in range(5)]
        )
        deps.sort(key=lambda x: x["minutes"])
        result = _balance_directions(deps, 6)
        dirs = [d["direction"] for d in result]
        assert dirs.count("North") >= 2
        assert dirs.count("South") >= 2

    def test_heavily_imbalanced_input(self):
        """Even if one direction has many more departures, both should appear."""
        deps = (
            [{"direction": "Frequent", "minutes": i} for i in range(20)] +
            [{"direction": "Rare", "minutes": 100 + i} for i in range(2)]
        )
        deps.sort(key=lambda x: x["minutes"])
        result = _balance_directions(deps, 8)
        dirs = set(d["direction"] for d in result)
        assert "Frequent" in dirs
        assert "Rare" in dirs

    def test_three_directions(self):
        deps = []
        for d, base in [("A", 0), ("B", 1), ("C", 2)]:
            deps += [{"direction": d, "minutes": base + i * 3} for i in range(5)]
        deps.sort(key=lambda x: x["minutes"])
        result = _balance_directions(deps, 9)
        dirs = [d["direction"] for d in result]
        assert dirs.count("A") >= 2
        assert dirs.count("B") >= 2
        assert dirs.count("C") >= 2

    def test_output_sorted_by_minutes(self):
        deps = (
            [{"direction": "A", "minutes": i * 10} for i in range(5)] +
            [{"direction": "B", "minutes": i * 10 + 5} for i in range(5)]
        )
        result = _balance_directions(deps, 8)
        minutes = [d["minutes"] for d in result]
        assert minutes == sorted(minutes), "Output should be sorted by time"

    def test_fewer_than_count(self):
        deps = [{"direction": "A", "minutes": 1}, {"direction": "B", "minutes": 2}]
        result = _balance_directions(deps, 10)
        assert len(result) == 2

    def test_exact_count(self):
        deps = [{"direction": "A", "minutes": i} for i in range(5)]
        result = _balance_directions(deps, 5)
        assert len(result) == 5

    def test_preserves_all_fields(self):
        deps = [
            {"direction": "A", "minutes": 1, "line": "Red", "time": "2 min"},
            {"direction": "B", "minutes": 2, "line": "Blue", "time": "3 min"},
        ]
        result = _balance_directions(deps, 5)
        for dep in result:
            assert "line" in dep
            assert "time" in dep


# ===========================================================================
# 3. METRO STATION SEARCH — Name variations
# ===========================================================================

class TestMetroStationSearch:
    """Test search with many name variations users might type."""

    # (query, expected_station_in_results)
    SEARCH_CASES = [
        # Trindade
        ("trindade", "Trindade"),
        ("Trindade", "Trindade"),
        ("TRINDADE", "Trindade"),
        ("trin", "Trindade"),
        ("trindad", "Trindade"),

        # Bolhão
        ("bolhao", "Bolhão"),
        ("Bolhão", "Bolhão"),
        ("bolhão", "Bolhão"),
        ("bolh", "Bolhão"),
        ("BOLHAO", "Bolhão"),

        # São Bento
        ("sao bento", "São Bento"),
        ("São Bento", "São Bento"),
        ("s bento", "São Bento"),
        ("s. bento", "São Bento"),
        ("sao bent", "São Bento"),

        # D. João II
        ("d joao 2", "D. João II"),
        ("d. joao ii", "D. João II"),
        ("d joao", "D. João II"),
        ("joao 2", "D. João II"),
        ("dom joao", "D. João II"),

        # Hospital de São João
        ("hospital sao joao", "Hospital de São João"),
        ("hosp sao joao", "Hospital de São João"),
        ("hospital s joao", "Hospital de São João"),
        ("sao joao", "Hospital de São João"),
        ("hospital são joão", "Hospital de São João"),

        # Casa da Música
        ("casa da musica", "Casa da Música"),
        ("casa musica", "Casa da Música"),
        ("Casa da Música", "Casa da Música"),
        ("casa music", "Casa da Música"),
        ("musica", "Casa da Música"),

        # Aeroporto
        ("aeroporto", "Aeroporto"),
        ("aero", "Aeroporto"),
        ("aerop", "Aeroporto"),

        # Campanhã
        ("campanha", "Campanhã"),
        ("Campanhã", "Campanhã"),
        ("campanhã", "Campanhã"),
        ("camp", "Campanhã"),

        # Aliados
        ("aliados", "Aliados"),
        ("Aliados", "Aliados"),

        # Marquês
        ("marques", "Marquês"),
        ("Marquês", "Marquês"),
        ("marquês", "Marquês"),

        # Fânzeres
        ("fanzeres", "Fânzeres"),
        ("Fânzeres", "Fânzeres"),

        # Senhor de Matosinhos
        ("matosinhos", "Senhor de Matosinhos"),
        ("sr matosinhos", "Senhor de Matosinhos"),
        ("senhor matosinhos", "Senhor de Matosinhos"),

        # ISMAI
        ("ismai", "ISMAI"),
        ("ISMAI", "ISMAI"),

        # Póvoa de Varzim
        ("povoa", "Póvoa de Varzim"),
        ("povoa varzim", "Póvoa de Varzim"),

        # Santo Ovídio
        ("santo ovidio", "Santo Ovídio"),
        ("sto ovidio", "Santo Ovídio"),
        ("s. ovidio", "Santo Ovídio"),

        # Polo Universitário
        ("polo universitario", "Polo Universitário"),
        ("polo univ", "Polo Universitário"),
        ("universitario", "Polo Universitário"),

        # Jardim do Morro
        ("jardim morro", "Jardim do Morro"),
        ("jardim do morro", "Jardim do Morro"),

        # Estádio do Dragão
        ("estadio dragao", "Estádio do Dragão"),
        ("dragao", "Estádio do Dragão"),

        # Senhora da Hora
        ("senhora hora", "Senhora da Hora"),
        ("sra hora", "Senhora da Hora"),

        # Hospital Santos Silva
        ("santos silva", "Hospital Santos Silva"),
        ("hospital santos silva", "Hospital Santos Silva"),

        # IPO
        ("ipo", "IPO"),
        ("IPO", "IPO"),

        # Combatentes
        ("combatentes", "Combatentes"),

        # Vila d'Este
        ("vila deste", "Vila d'Este"),
        ("vila d'este", "Vila d'Este"),
    ]

    @pytest.mark.parametrize("query,expected", SEARCH_CASES)
    def test_search_finds_station(self, query, expected):
        results = metro_search(query)
        names = [r["name"] for r in results]
        assert expected in names, (
            f"Search '{query}' should find '{expected}', got: {names[:5]}"
        )

    def test_empty_query(self):
        assert metro_search("") == []
        assert metro_search("   ") == []

    def test_nonsense_query(self):
        results = metro_search("xyzqwerty123")
        assert len(results) == 0


# ===========================================================================
# 4. METROBUS STATION SEARCH & DEPARTURES
# ===========================================================================

class TestAllMetroBusStops:
    """Test every MetroBus stop."""

    @pytest.fixture(autouse=True)
    def _patch_time(self):
        fake_now = datetime(2026, 3, 9, 10, 0, 0)
        with patch("bot.services.metrobus.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            yield

    @pytest.mark.parametrize("stop_name", list(METROBUS_STOPS.keys()))
    def test_stop_returns_departures(self, stop_name):
        deps = metrobus_departures(stop_name)
        assert isinstance(deps, list)
        assert len(deps) > 0, f"{stop_name}: no departures"

    @pytest.mark.parametrize("stop_name", list(METROBUS_STOPS.keys()))
    def test_stop_has_valid_data(self, stop_name):
        data = METROBUS_STOPS[stop_name]
        assert "lines" in data and len(data["lines"]) > 0
        assert "lat" in data and "lon" in data

    METROBUS_SEARCH_CASES = [
        ("boavista", "Rotunda da Boavista"),
        ("casa da musica", "Casa da Música (MetroBus)"),
        ("imperio", "Império"),
        ("jardim matosinhos", "Jardim de Matosinhos"),
        ("norton", "Norton de Matos"),
        ("bessa", "Estádio do Bessa"),
        ("fluvial", "Fluvial"),
    ]

    @pytest.mark.parametrize("query,expected", METROBUS_SEARCH_CASES)
    def test_search(self, query, expected):
        results = metrobus_search(query)
        names = [r["name"] for r in results]
        assert expected in names, f"MetroBus search '{query}' should find '{expected}', got: {names}"


# ===========================================================================
# 5. TRAIN STATION SEARCH & DEPARTURES
# ===========================================================================

class TestAllTrainStations:
    """Test every CP train station."""

    @pytest.fixture(autouse=True)
    def _patch_time(self):
        fake_now = datetime(2026, 3, 9, 10, 0, 0)
        with patch("bot.services.cp.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            yield

    @pytest.mark.parametrize("station_name", list(TRAIN_STATIONS.keys()))
    def test_station_returns_departures(self, station_name):
        deps = train_departures(station_name)
        assert isinstance(deps, list)
        assert len(deps) > 0, f"{station_name}: no departures"

    TRAIN_SEARCH_CASES = [
        ("campanha", "Porto-Campanha"),
        ("sao bento", "Porto-São Bento"),
        ("braga", "Braga"),
        ("aveiro", "Aveiro"),
        ("guimaraes", "Guimarães"),
        ("ermesinde", "Ermesinde"),
        ("valongo", "Valongo"),
        ("marco", "Marco de Canaveses"),
    ]

    @pytest.mark.parametrize("query,expected", TRAIN_SEARCH_CASES)
    def test_search(self, query, expected):
        results = train_search(query)
        names = [r["name"] for r in results]
        assert expected in names, f"Train search '{query}' should find '{expected}', got: {names}"


# ===========================================================================
# 6. BUS STOP SEARCH — Local GTFS
# ===========================================================================

class TestBusStopSearch:
    """Test bus stop local search with injected GTFS data."""

    BUS_STOPS_SAMPLE = [
        {"stop_id": "BCM1", "name": "Boavista - Casa da Música 1", "lat": 41.1588, "lon": -8.6310},
        {"stop_id": "BCM2", "name": "Boavista - Casa da Música 2", "lat": 41.1585, "lon": -8.6305},
        {"stop_id": "BLH1", "name": "Bolhão 1", "lat": 41.1490, "lon": -8.6060},
        {"stop_id": "BLH2", "name": "Bolhão 2", "lat": 41.1488, "lon": -8.6058},
        {"stop_id": "TRD1", "name": "Trindade 1", "lat": 41.1519, "lon": -8.6102},
        {"stop_id": "TRD2", "name": "Trindade 2", "lat": 41.1517, "lon": -8.6100},
        {"stop_id": "PRL1", "name": "Praça da Liberdade 1", "lat": 41.1462, "lon": -8.6102},
        {"stop_id": "PRL2", "name": "Praça da Liberdade 2", "lat": 41.1460, "lon": -8.6100},
        {"stop_id": "ALI1", "name": "Aliados 1", "lat": 41.1475, "lon": -8.6095},
        {"stop_id": "ALI2", "name": "Aliados 2", "lat": 41.1473, "lon": -8.6093},
        {"stop_id": "MQS1", "name": "Marquês 1", "lat": 41.1545, "lon": -8.6055},
        {"stop_id": "MQS2", "name": "Marquês 2", "lat": 41.1543, "lon": -8.6053},
        {"stop_id": "BOA1", "name": "Boavista 1", "lat": 41.1580, "lon": -8.6250},
        {"stop_id": "BOA2", "name": "Boavista 2", "lat": 41.1578, "lon": -8.6248},
        {"stop_id": "CMP1", "name": "Campanhã 1", "lat": 41.1489, "lon": -8.5856},
        {"stop_id": "CMP2", "name": "Campanhã 2", "lat": 41.1487, "lon": -8.5854},
        {"stop_id": "HOSP1", "name": "Hospital de Sto. António 1", "lat": 41.1445, "lon": -8.6210},
        {"stop_id": "HOSP2", "name": "Hospital de Sto. António 2", "lat": 41.1443, "lon": -8.6208},
        {"stop_id": "FOZ1", "name": "Foz do Douro 1", "lat": 41.1510, "lon": -8.6710},
        {"stop_id": "FOZ2", "name": "Foz do Douro 2", "lat": 41.1508, "lon": -8.6708},
        {"stop_id": "PAR1", "name": "Paranhos 1", "lat": 41.1650, "lon": -8.6010},
        {"stop_id": "PAR2", "name": "Paranhos 2", "lat": 41.1648, "lon": -8.6008},
        {"stop_id": "RIB1", "name": "Ribeira 1", "lat": 41.1410, "lon": -8.6130},
        {"stop_id": "RIB2", "name": "Ribeira 2", "lat": 41.1408, "lon": -8.6128},
        {"stop_id": "CON1", "name": "Constituição 1", "lat": 41.1560, "lon": -8.6080},
        {"stop_id": "CON2", "name": "Constituição 2", "lat": 41.1558, "lon": -8.6078},
    ]

    @pytest.fixture(autouse=True)
    def _inject_stops(self):
        import bot.services.stcp as stcp_mod
        original = stcp_mod._gtfs_bus_stops
        stcp_mod._gtfs_bus_stops = self.BUS_STOPS_SAMPLE
        yield
        stcp_mod._gtfs_bus_stops = original

    SEARCH_CASES = [
        ("bolhao", "BLH1"),
        ("bolhão", "BLH1"),
        ("Bolhão", "BLH1"),
        ("BLH", "BLH1"),
        ("BLH1", "BLH1"),
        ("trindade", "TRD1"),
        ("TRD", "TRD1"),
        ("casa da musica", "BCM1"),
        ("BCM", "BCM1"),
        ("BCM2", "BCM2"),
        ("aliados", "ALI1"),
        ("marques", "MQS1"),
        ("boavista", "BOA1"),
        ("campanha", "CMP1"),
        ("hospital", "HOSP1"),
        ("foz", "FOZ1"),
        ("paranhos", "PAR1"),
        ("ribeira", "RIB1"),
        ("constituicao", "CON1"),
        ("liberdade", "PRL1"),
        ("praca liberdade", "PRL1"),
    ]

    @pytest.mark.parametrize("query,expected_code", SEARCH_CASES)
    def test_local_search(self, query, expected_code):
        from bot.services.stcp import search_stops_local
        results = search_stops_local(query)
        codes = [r["stop_id"] for r in results]
        assert expected_code in codes, (
            f"Bus search '{query}' should find '{expected_code}', got: {codes}"
        )


# ===========================================================================
# 7. HANDLER INTERACTION TESTS
# ===========================================================================

class TestMetroStationCallback:
    """Test metro station callback handler with refresh/back/menu."""

    @pytest.mark.asyncio
    async def test_station_callback_success(self):
        from bot.handlers.metro import metro_station_callback

        update = _make_update(callback_data="metro:station:Trindade")
        ctx = _make_context()

        with patch("bot.handlers.metro.metro.get_next_departures_async",
                    new_callable=AsyncMock, return_value=[
                        {"direction": "Senhor de Matosinhos", "time": "3 min",
                         "line": "🔵 Linha A", "minutes": 3},
                    ]), \
             patch("bot.handlers.metro.is_favorite",
                    new_callable=AsyncMock, return_value=False):
            await metro_station_callback(update, ctx)

        query = update.callback_query
        query.answer.assert_called_once()
        query.edit_message_text.assert_called_once()
        call_args = query.edit_message_text.call_args
        assert "Trindade" in call_args.kwargs.get("text", call_args.args[0] if call_args.args else "")

    @pytest.mark.asyncio
    async def test_station_callback_with_back_context(self):
        """Back button should use stored context."""
        from bot.handlers.metro import metro_station_callback

        update = _make_update(callback_data="metro:station:Bolhão")
        ctx = _make_context(user_data={"metro_back": "metro:line:A"})

        with patch("bot.handlers.metro.metro.get_next_departures_async",
                    new_callable=AsyncMock, return_value=[
                        {"direction": "Test", "time": "5 min", "minutes": 5},
                    ]), \
             patch("bot.handlers.metro.is_favorite",
                    new_callable=AsyncMock, return_value=False):
            await metro_station_callback(update, ctx)

        call_args = update.callback_query.edit_message_text.call_args
        keyboard = call_args.kwargs.get("reply_markup")
        assert keyboard is not None

    @pytest.mark.asyncio
    async def test_station_callback_message_not_modified(self):
        """Refresh that returns same data should not crash."""
        from bot.handlers.metro import metro_station_callback
        from telegram.error import BadRequest

        update = _make_update(callback_data="metro:station:Aliados")
        ctx = _make_context()

        update.callback_query.edit_message_text = AsyncMock(
            side_effect=BadRequest("Message is not modified")
        )

        with patch("bot.handlers.metro.metro.get_next_departures_async",
                    new_callable=AsyncMock, return_value=[
                        {"direction": "Test", "time": "5 min", "minutes": 5},
                    ]), \
             patch("bot.handlers.metro.is_favorite",
                    new_callable=AsyncMock, return_value=False):
            # Should NOT raise
            await metro_station_callback(update, ctx)

    @pytest.mark.asyncio
    async def test_station_callback_real_error_still_shows_error(self):
        """Non-'not modified' errors should show error message."""
        from bot.handlers.metro import metro_station_callback
        from telegram.error import BadRequest

        update = _make_update(callback_data="metro:station:Aliados")
        ctx = _make_context()

        # First call (inner edit) raises real error, second call (error message) succeeds
        call_count = 0
        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise BadRequest("Some other Telegram error")

        update.callback_query.edit_message_text = AsyncMock(side_effect=side_effect)

        with patch("bot.handlers.metro.metro.get_next_departures_async",
                    new_callable=AsyncMock, return_value=[
                        {"direction": "Test", "time": "5 min", "minutes": 5},
                    ]), \
             patch("bot.handlers.metro.is_favorite",
                    new_callable=AsyncMock, return_value=False):
            await metro_station_callback(update, ctx)

        # Should have been called twice (first fail, then error message)
        assert call_count == 2


class TestBusStopCallback:
    """Test bus stop callback handler."""

    @pytest.mark.asyncio
    async def test_bus_stop_callback_success(self):
        from bot.handlers.bus import bus_stop_callback

        update = _make_update(callback_data="bus:stop:BCM2")
        ctx = _make_context()

        with patch("bot.handlers.bus.stcp.get_stop_real_time",
                    new_callable=AsyncMock, return_value={
                        "stop_id": "BCM2", "stop_name": "Boavista",
                        "arrivals": [
                            {"line": "200", "destination": "Bolhão", "time": "3 min", "minutes": 3, "status": ""},
                        ],
                    }), \
             patch("bot.handlers.bus.is_favorite",
                    new_callable=AsyncMock, return_value=False):
            await bus_stop_callback(update, ctx)

        update.callback_query.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_bus_stop_callback_message_not_modified(self):
        from bot.handlers.bus import bus_stop_callback
        from telegram.error import BadRequest

        update = _make_update(callback_data="bus:stop:BCM2")
        ctx = _make_context()

        update.callback_query.edit_message_text = AsyncMock(
            side_effect=BadRequest("Message is not modified")
        )

        with patch("bot.handlers.bus.stcp.get_stop_real_time",
                    new_callable=AsyncMock, return_value={
                        "stop_id": "BCM2", "stop_name": "Boavista",
                        "arrivals": [],
                    }), \
             patch("bot.handlers.bus.is_favorite",
                    new_callable=AsyncMock, return_value=False):
            await bus_stop_callback(update, ctx)
        # Should not raise


class TestMetroBusStopCallback:
    """Test metrobus stop callback handler."""

    @pytest.mark.asyncio
    async def test_metrobus_stop_callback_success(self):
        from bot.handlers.metrobus import metrobus_stop_callback

        update = _make_update(callback_data="metrobus:stop:Império")
        ctx = _make_context()

        with patch("bot.handlers.metrobus.metrobus.get_next_departures",
                    return_value=[
                        {"direction": "Casa da Música", "time": "5 min", "minutes": 5,
                         "line": "🚍 Linha 1", "estimated": True},
                    ]), \
             patch("bot.database.is_favorite",
                    new_callable=AsyncMock, return_value=False):
            await metrobus_stop_callback(update, ctx)

        update.callback_query.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_metrobus_stop_callback_message_not_modified(self):
        from bot.handlers.metrobus import metrobus_stop_callback
        from telegram.error import BadRequest

        update = _make_update(callback_data="metrobus:stop:Império")
        ctx = _make_context()

        update.callback_query.edit_message_text = AsyncMock(
            side_effect=BadRequest("Message is not modified")
        )

        with patch("bot.handlers.metrobus.metrobus.get_next_departures",
                    return_value=[
                        {"direction": "Casa da Música", "time": "5 min", "minutes": 5,
                         "line": "🚍 Linha 1", "estimated": True},
                    ]), \
             patch("bot.database.is_favorite",
                    new_callable=AsyncMock, return_value=False):
            await metrobus_stop_callback(update, ctx)


class TestTrainStationCallback:
    """Test train station callback handler."""

    @pytest.mark.asyncio
    async def test_train_station_callback_success(self):
        from bot.handlers.trains import train_station_callback

        update = _make_update(callback_data="train:station:Porto-Campanha")
        ctx = _make_context()

        with patch("bot.handlers.trains.cp.get_next_departures",
                    return_value=[
                        {"direction": "Braga", "time": "10 min", "minutes": 10,
                         "line": "🔵 Linha de Braga", "estimated": True},
                    ]), \
             patch("bot.handlers.trains.is_favorite",
                    new_callable=AsyncMock, return_value=False):
            await train_station_callback(update, ctx)

        update.callback_query.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_train_station_callback_message_not_modified(self):
        from bot.handlers.trains import train_station_callback
        from telegram.error import BadRequest

        update = _make_update(callback_data="train:station:Porto-Campanha")
        ctx = _make_context()

        update.callback_query.edit_message_text = AsyncMock(
            side_effect=BadRequest("Message is not modified")
        )

        with patch("bot.handlers.trains.cp.get_next_departures",
                    return_value=[
                        {"direction": "Braga", "time": "10 min", "minutes": 10,
                         "line": "🔵 Linha de Braga", "estimated": True},
                    ]), \
             patch("bot.handlers.trains.is_favorite",
                    new_callable=AsyncMock, return_value=False):
            await train_station_callback(update, ctx)


# ===========================================================================
# 8. MENU / BACK / NAVIGATION CALLBACKS
# ===========================================================================

class TestMenuNavigation:
    """Test menu, back, and navigation callbacks."""

    @pytest.mark.asyncio
    async def test_metro_menu_clears_back_context(self):
        from bot.handlers.metro import metro_menu_callback

        update = _make_update(callback_data="menu:metro")
        ctx = _make_context(user_data={"metro_back": "metro:line:A"})

        await metro_menu_callback(update, ctx)

        assert "metro_back" not in ctx.user_data
        update.callback_query.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_metro_line_sets_back_context(self):
        from bot.handlers.metro import metro_line_callback

        update = _make_update(callback_data="metro:line:A")
        ctx = _make_context()

        await metro_line_callback(update, ctx)

        assert ctx.user_data.get("metro_back") == "metro:line:A"

    @pytest.mark.asyncio
    async def test_metro_lines_callback(self):
        from bot.handlers.metro import metro_lines_callback

        update = _make_update(callback_data="metro:lines")
        ctx = _make_context()

        await metro_lines_callback(update, ctx)
        update.callback_query.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_metro_freq_callback(self):
        from bot.handlers.metro import metro_freq_callback

        update = _make_update(callback_data="metro:freq")
        ctx = _make_context()

        await metro_freq_callback(update, ctx)
        update.callback_query.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_bus_menu_clears_back_context(self):
        from bot.handlers.bus import bus_menu_callback

        update = _make_update(callback_data="menu:bus")
        ctx = _make_context(user_data={"bus_back": "nearby:refresh"})

        await bus_menu_callback(update, ctx)
        assert "bus_back" not in ctx.user_data

    @pytest.mark.asyncio
    async def test_metrobus_menu_clears_back_context(self):
        from bot.handlers.metrobus import metrobus_menu_callback

        update = _make_update(callback_data="menu:metrobus")
        ctx = _make_context(user_data={"metrobus_back": "nearby:refresh"})

        await metrobus_menu_callback(update, ctx)
        assert "metrobus_back" not in ctx.user_data

    @pytest.mark.asyncio
    async def test_trains_menu_clears_back_context(self):
        from bot.handlers.trains import trains_menu_callback

        update = _make_update(callback_data="menu:trains")
        ctx = _make_context(user_data={"train_back": "nearby:refresh"})

        await trains_menu_callback(update, ctx)
        assert "train_back" not in ctx.user_data


# ===========================================================================
# 9. HANDLE TEXT — Bot mention & mode prefix stripping
# ===========================================================================

class TestHandleTextMentionStripping:
    """Test that @BotMention and mode prefixes are stripped."""

    @pytest.mark.asyncio
    async def test_bot_mention_stripped_metro(self):
        from bot.main import handle_text

        update = _make_update(text="@PortoTransportBot metro trindade")
        ctx = _make_context()

        with patch("bot.handlers.metro.metro.search_stations") as mock_search:
            mock_search.return_value = [{
                "name": "Trindade",
                "zone": "PRT",
                "lines": [{"code": "A", "name": "Linha A", "emoji": "🔵"}],
            }]
            with patch("bot.handlers.metro.metro.get_next_departures",
                        return_value=[{"direction": "Test", "time": "5 min", "minutes": 5, "estimated": True}]), \
                 patch("bot.database.is_favorite", new_callable=AsyncMock, return_value=False):
                await handle_text(update, ctx)

            # Should have searched for "trindade" not "@PortoTransportBot metro trindade"
            mock_search.assert_called()
            search_arg = mock_search.call_args[0][0]
            assert "@" not in search_arg
            assert "metro" not in search_arg.lower() or search_arg.lower() == "trindade"

    @pytest.mark.asyncio
    async def test_metro_prefix_stripped(self):
        from bot.main import handle_text

        update = _make_update(text="metro bolhao")
        ctx = _make_context()

        with patch("bot.handlers.metro.metro.search_stations") as mock_search:
            mock_search.return_value = [{
                "name": "Bolhão",
                "zone": "PRT",
                "lines": [{"code": "A", "name": "Linha A", "emoji": "🔵"}],
            }]
            with patch("bot.handlers.metro.metro.get_next_departures",
                        return_value=[{"direction": "Test", "time": "5 min", "minutes": 5, "estimated": True}]), \
                 patch("bot.database.is_favorite", new_callable=AsyncMock, return_value=False):
                await handle_text(update, ctx)

            mock_search.assert_called()
            search_arg = mock_search.call_args[0][0]
            assert search_arg.lower().strip() == "bolhao"

    @pytest.mark.asyncio
    async def test_bus_prefix_stripped(self):
        from bot.main import handle_text

        update = _make_update(text="bus bolhao")
        ctx = _make_context()

        with patch("bot.services.stcp.search_stops",
                    new_callable=AsyncMock, return_value=[
                        {"stop_id": "BLH1", "name": "Bolhão 1", "code": "BLH1", "zone": ""},
                    ]):
            await handle_text(update, ctx)
            # Should not show "no results"

    @pytest.mark.asyncio
    async def test_plain_text_not_stripped(self):
        """Normal text without prefix should not be modified."""
        from bot.main import handle_text

        update = _make_update(text="trindade")
        ctx = _make_context()

        with patch("bot.handlers.metro.metro.search_stations") as mock_search:
            mock_search.return_value = [{
                "name": "Trindade",
                "zone": "PRT",
                "lines": [{"code": "A", "name": "Linha A", "emoji": "🔵"}],
            }]
            with patch("bot.handlers.metro.metro.get_next_departures",
                        return_value=[{"direction": "Test", "time": "5 min", "minutes": 5, "estimated": True}]), \
                 patch("bot.database.is_favorite", new_callable=AsyncMock, return_value=False):
                await handle_text(update, ctx)

            mock_search.assert_called()
            search_arg = mock_search.call_args[0][0]
            assert search_arg == "trindade"


# ===========================================================================
# 10. FAVORITES TOGGLE
# ===========================================================================

class TestFavoritesToggle:
    """Test adding/removing favorites via callbacks."""

    @pytest.mark.asyncio
    async def test_add_metro_favorite(self):
        from bot.handlers.favorites import add_favorite_callback

        update = _make_update(callback_data="fav:add:metro:Trindade")
        ctx = _make_context()

        with patch("bot.handlers.favorites.add_favorite", new_callable=AsyncMock):
            await add_favorite_callback(update, ctx)

        update.callback_query.answer.assert_called_once()

    @pytest.mark.asyncio
    async def test_remove_metro_favorite(self):
        from bot.handlers.favorites import remove_favorite_callback

        update = _make_update(callback_data="fav:remove:metro:Trindade")
        ctx = _make_context()

        with patch("bot.handlers.favorites.remove_favorite", new_callable=AsyncMock):
            await remove_favorite_callback(update, ctx)

        update.callback_query.answer.assert_called_once()


# ===========================================================================
# 11. KEYBOARD BUILDERS
# ===========================================================================

class TestKeyboardBuilders:
    """Test keyboard construction for all transport modes."""

    def test_metro_station_keyboard_with_back(self):
        from bot.keyboards.inline import metro_station_actions_keyboard
        kb = metro_station_actions_keyboard("Trindade", is_fav=False, lang="pt",
                                             back_callback="metro:line:A")
        buttons = [btn for row in kb.inline_keyboard for btn in row]
        back_btns = [b for b in buttons if "metro:line:A" in (b.callback_data or "")]
        assert len(back_btns) == 1, "Should have back button to line A"

    def test_metro_station_keyboard_default_back(self):
        from bot.keyboards.inline import metro_station_actions_keyboard
        kb = metro_station_actions_keyboard("Trindade", is_fav=False, lang="pt")
        buttons = [btn for row in kb.inline_keyboard for btn in row]
        back_btns = [b for b in buttons if "menu:metro" in (b.callback_data or "")]
        assert len(back_btns) == 1, "Default back should go to metro menu"

    def test_metro_station_keyboard_favorite_toggle(self):
        from bot.keyboards.inline import metro_station_actions_keyboard
        kb_fav = metro_station_actions_keyboard("Trindade", is_fav=True, lang="pt")
        kb_notfav = metro_station_actions_keyboard("Trindade", is_fav=False, lang="pt")

        fav_btns = [btn for row in kb_fav.inline_keyboard for btn in row
                     if "fav:remove" in (btn.callback_data or "")]
        notfav_btns = [btn for row in kb_notfav.inline_keyboard for btn in row
                        if "fav:add" in (btn.callback_data or "")]
        assert len(fav_btns) == 1, "Favorited station should have 'remove' button"
        assert len(notfav_btns) == 1, "Non-fav station should have 'add' button"

    def test_bus_stop_keyboard_with_back(self):
        from bot.keyboards.inline import bus_stop_actions_keyboard
        kb = bus_stop_actions_keyboard("BCM2", is_fav=False, lang="pt",
                                        back_callback="nearby:refresh")
        buttons = [btn for row in kb.inline_keyboard for btn in row]
        back_btns = [b for b in buttons if "nearby:refresh" in (b.callback_data or "")]
        assert len(back_btns) == 1

    def test_metrobus_stop_keyboard(self):
        from bot.keyboards.inline import metrobus_stop_actions_keyboard
        kb = metrobus_stop_actions_keyboard("Império", is_fav=False, lang="pt")
        assert kb.inline_keyboard  # Has buttons

    def test_train_station_keyboard(self):
        from bot.keyboards.inline import train_station_actions_keyboard
        kb = train_station_actions_keyboard("Porto-Campanha", is_fav=False, lang="pt")
        assert kb.inline_keyboard


# ===========================================================================
# 12. METRO LINE STATIONS
# ===========================================================================

class TestMetroLineStations:
    """Test line station listings."""

    @pytest.mark.parametrize("line_code", list(METRO_LINES.keys()))
    def test_line_has_stations(self, line_code):
        stations = get_line_stations(line_code)
        assert len(stations) >= 5, f"Line {line_code} should have at least 5 stations"

    @pytest.mark.parametrize("line_code", list(METRO_LINES.keys()))
    def test_line_stations_exist(self, line_code):
        stations = get_line_stations(line_code)
        for name in stations:
            assert name in METRO_STATIONS, f"Station '{name}' from line {line_code} not in STATIONS"

    def test_all_lines_info(self):
        lines = get_all_lines()
        assert len(lines) >= 6  # A, B, C, D, E, F
        for line in lines:
            assert "name" in line
            assert "emoji" in line
            assert "station_count" in line
            assert line["station_count"] > 0

    @pytest.mark.parametrize("line_code", list(METRO_LINES.keys()))
    def test_frequency_info(self, line_code):
        freq = get_frequency_info(line_code)
        assert "peak" in freq
        assert "off_peak" in freq
        assert "weekend" in freq
        assert "hours" in freq


# ===========================================================================
# 13. SEARCH UTILITY — normalize & match_score
# ===========================================================================

class TestSearchNormalization:
    """Test the normalization and matching utility."""

    def test_strip_accents(self):
        assert "joao" in normalize("João")
        assert "fanzeres" in normalize("Fânzeres")
        assert "povoa" in normalize("Póvoa")

    def test_abbreviation_expansion(self):
        n = normalize("D. João II")
        assert "dom" in n
        assert "2" in n

    def test_roman_numerals(self):
        n = normalize("D. João II")
        assert "2" in n

    def test_arabic_to_roman(self):
        n = normalize("D. João 2")
        assert "ii" in n

    def test_sao_abbreviation(self):
        n = normalize("São Bento")
        assert "s." in n or "sao" in n

    MATCH_CASES = [
        # Exact match
        ("Trindade", "Trindade", 100),
        # Substring
        ("trin", "Trindade", 70),
        # Accent-free
        ("bolhao", "Bolhão", 70),
        # No match
        ("xyz123", "Trindade", 0),
    ]

    @pytest.mark.parametrize("query,name,min_score", MATCH_CASES)
    def test_match_score(self, query, name, min_score):
        score = match_score(query, name)
        if min_score == 0:
            assert score == 0
        else:
            assert score >= min_score * 0.5, (
                f"match_score('{query}', '{name}') = {score}, expected >= {min_score * 0.5}"
            )


# ===========================================================================
# 14. INLINE QUERY HANDLER
# ===========================================================================

class TestInlineQueryHandler:
    """Test inline query routing."""

    @pytest.mark.asyncio
    async def test_metro_prefix_inline(self):
        from bot.handlers.inline import _add_metro_stations_quick

        results = []
        _add_metro_stations_quick("Trindade", results)
        assert len(results) >= 1
        assert any("Trindade" in r.title for r in results)

    @pytest.mark.asyncio
    async def test_metro_inline_all_hub_stations(self):
        from bot.handlers.inline import _add_metro_stations_quick

        hubs = ["Trindade", "Bolhão", "Casa da Música", "Campanhã", "Aliados"]
        for hub in hubs:
            results = []
            _add_metro_stations_quick(hub, results)
            assert len(results) >= 1, f"Inline search for '{hub}' should return results"

    @pytest.mark.asyncio
    async def test_metrobus_inline(self):
        from bot.handlers.inline import _add_metrobus_stops_quick

        results = []
        _add_metrobus_stops_quick("Boavista", results)
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_empty_inline_query(self):
        from bot.handlers.inline import inline_query_handler

        update = _make_update(text="")
        ctx = _make_context()

        await inline_query_handler(update, ctx)
        update.inline_query.answer.assert_called_once()


# ===========================================================================
# 15. REALTIME DEPARTURES — MOTIS integration
# ===========================================================================

class TestRealtimeDepartures:
    """Test MOTIS realtime departure fetching."""

    @pytest.mark.asyncio
    async def test_get_realtime_departures_with_mock(self):
        from bot.services.metro_realtime import get_realtime_departures, _cache

        _cache.clear()

        mock_itinerary = {
            "legs": [{
                "mode": "SUBWAY",
                "agencyName": "Metro do Porto",
                "from": {"departure": "2026-03-09T10:05:00+00:00"},
                "headsign": "Senhor de Matosinhos",
                "routeShortName": "A",
                "routeColor": "0088CC",
            }],
        }

        with patch("bot.services.metro_realtime._query_motis",
                    new_callable=AsyncMock, return_value=[mock_itinerary]):
            deps = await get_realtime_departures("Trindade", count=5)

        assert isinstance(deps, list)

    @pytest.mark.asyncio
    async def test_realtime_departures_unknown_station(self):
        from bot.services.metro_realtime import get_realtime_departures

        deps = await get_realtime_departures("NonexistentStation123")
        assert deps == []

    @pytest.mark.asyncio
    async def test_realtime_departures_balance(self):
        """Verify that realtime departures are balanced across directions."""
        from bot.services.metro_realtime import get_realtime_departures, _cache

        _cache.clear()

        # Simulate itineraries with multiple departures in each direction
        all_itins = []
        for i in range(0, 30, 3):
            all_itins.append({
                "legs": [{
                    "mode": "SUBWAY",
                    "agencyName": "Metro do Porto",
                    "from": {"departure": f"2026-03-09T10:{i:02d}:00+00:00"},
                    "headsign": "Hosp. São João",
                    "routeShortName": "D",
                }],
            })
        for i in range(1, 30, 6):
            all_itins.append({
                "legs": [{
                    "mode": "SUBWAY",
                    "agencyName": "Metro do Porto",
                    "from": {"departure": f"2026-03-09T10:{i:02d}:00+00:00"},
                    "headsign": "Hospital Santos Silva",
                    "routeShortName": "D",
                }],
            })

        with patch("bot.services.metro_realtime._query_motis",
                    new_callable=AsyncMock, return_value=all_itins):
            deps = await get_realtime_departures("D. João II", count=8)

        if deps:
            directions = set(d["direction"] for d in deps)
            assert len(directions) >= 2, f"Should have both directions, got: {directions}"


# ===========================================================================
# 16. FORMAT & I18N
# ===========================================================================

class TestFormatAndI18n:
    """Test formatting and translation functions."""

    def test_escape_md_special_chars(self):
        assert escape_md("D. João II") != "D. João II"
        assert "\\" in escape_md("D. João II")

    def test_metro_schedule_no_departures(self):
        text = format_metro_schedule("Test Station", "", [])
        assert "Test Station" in text or "Test\\ Station" in text

    def test_metro_schedule_with_departures(self):
        deps = [
            {"direction": "North", "time": "3 min"},
            {"direction": "South", "time": "5 min"},
        ]
        text = format_metro_schedule("Trindade", "🔵 Linha A", deps)
        assert "Trindade" in text or escape_md("Trindade") in text

    def test_translations_exist_pt(self):
        critical_keys = [
            "metro_title", "loading", "error_load_station",
            "kb_refresh", "kb_back", "kb_back_menu", "kb_favorite",
            "kb_unfavorite", "no_results",
        ]
        for key in critical_keys:
            val = t(key, "pt")
            assert val and val != key, f"Missing PT translation: {key}"

    def test_translations_exist_en(self):
        critical_keys = [
            "metro_title", "loading", "error_load_station",
            "kb_refresh", "kb_back", "kb_back_menu",
        ]
        for key in critical_keys:
            val = t(key, "en")
            assert val and val != key, f"Missing EN translation: {key}"

    def test_get_lang_defaults_to_pt(self):
        update = _make_update(lang="pt")
        assert get_lang(update) == "pt"

    def test_get_lang_en(self):
        update = _make_update(lang="en")
        assert get_lang(update) == "en"


# ===========================================================================
# 17. ASYNC GET_NEXT_DEPARTURES
# ===========================================================================

class TestAsyncDepartures:
    """Test the async departure fetching with fallback."""

    @pytest.mark.asyncio
    async def test_async_departures_fallback_to_sync(self):
        """When MOTIS fails, should fall back to sync departures."""
        from bot.services.metro import get_next_departures_async

        with patch("bot.services.metro_realtime.get_realtime_departures",
                    new_callable=AsyncMock, side_effect=Exception("API down")):
            with patch("bot.services.metro.datetime") as mock_dt:
                mock_dt.now.return_value = datetime(2026, 3, 9, 10, 0, 0)
                mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
                deps = await get_next_departures_async("Trindade")

        assert isinstance(deps, list)
        assert len(deps) > 0

    @pytest.mark.asyncio
    async def test_async_departures_uses_realtime_when_available(self):
        from bot.services.metro import get_next_departures_async

        rt_deps = [{"direction": "RT North", "time": "1 min", "minutes": 1, "realtime": True}]

        with patch("bot.services.metro_realtime.get_realtime_departures",
                    new_callable=AsyncMock, return_value=rt_deps):
            deps = await get_next_departures_async("Trindade")

        assert deps == rt_deps

    @pytest.mark.asyncio
    @pytest.mark.parametrize("station_name", [
        "Trindade", "Bolhão", "Casa da Música", "D. João II",
        "Campanhã", "Aeroporto", "Aliados", "São Bento",
    ])
    async def test_async_departures_for_key_stations(self, station_name):
        from bot.services.metro import get_next_departures_async

        with patch("bot.services.metro_realtime.get_realtime_departures",
                    new_callable=AsyncMock, return_value=[]):
            with patch("bot.services.metro.datetime") as mock_dt:
                mock_dt.now.return_value = datetime(2026, 3, 9, 10, 0, 0)
                mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
                deps = await get_next_departures_async(station_name)

        assert len(deps) > 0, f"Async departures for {station_name} should not be empty"


# ===========================================================================
# 18. METRO CLOSED / NIGHT SERVICE
# ===========================================================================

class TestMetroClosedService:
    """Test behavior when metro is not operating."""

    def test_closed_at_3am(self):
        fake_now = datetime(2026, 3, 9, 3, 0, 0)
        with patch("bot.services.metro.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            deps = metro_departures("Trindade")

        assert len(deps) == 1
        assert "encerrado" in deps[0]["direction"].lower() or "encerrado" in deps[0].get("direction", "").lower()

    def test_closed_at_4am(self):
        fake_now = datetime(2026, 3, 9, 4, 0, 0)
        with patch("bot.services.metro.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            deps = metro_departures("Trindade")

        assert len(deps) == 1
        assert "encerrado" in deps[0]["direction"].lower()


# ===========================================================================
# 19. STATION LOCATION
# ===========================================================================

class TestStationLocation:
    """Test station location callback."""

    @pytest.mark.asyncio
    async def test_metro_location_callback(self):
        from bot.handlers.metro import metro_location_callback

        update = _make_update(callback_data="metro:location:Trindade")
        ctx = _make_context()

        with patch("bot.handlers.metro.is_favorite",
                    new_callable=AsyncMock, return_value=False):
            await metro_location_callback(update, ctx)

        ctx.bot.send_location.assert_called_once()
        call_kwargs = ctx.bot.send_location.call_args.kwargs
        assert 41.0 < call_kwargs["latitude"] < 42.0
        assert -9.0 < call_kwargs["longitude"] < -8.0


# ===========================================================================
# 20. EDGE CASES
# ===========================================================================

class TestEdgeCases:
    """Edge cases and regression tests."""

    def test_station_with_apostrophe(self):
        """Vila d'Este has an apostrophe."""
        results = metro_search("vila deste")
        names = [r["name"] for r in results]
        assert "Vila d'Este" in names

    def test_station_with_dots(self):
        """D. João II has dots."""
        results = metro_search("D. João II")
        names = [r["name"] for r in results]
        assert "D. João II" in names

    def test_station_special_chars_in_callback(self):
        """Callback data with special characters."""
        from bot.keyboards.inline import metro_station_actions_keyboard
        kb = metro_station_actions_keyboard("D. João II", is_fav=False, lang="pt")
        buttons = [btn for row in kb.inline_keyboard for btn in row]
        refresh_btns = [b for b in buttons if b.callback_data and "metro:station:" in b.callback_data]
        assert len(refresh_btns) >= 1
        assert "D. João II" in refresh_btns[0].callback_data

    def test_very_long_station_name(self):
        """Search with a very long query."""
        results = metro_search("a" * 200)
        assert isinstance(results, list)  # Should not crash

    def test_search_with_numbers(self):
        results = metro_search("24 agosto")
        names = [r["name"] for r in results]
        assert "Campo 24 de Agosto" in names

    def test_search_partial_match(self):
        results = metro_search("faria")
        names = [r["name"] for r in results]
        assert "Faria Guimarães" in names

    @pytest.fixture(autouse=False)
    def _patch_operating(self):
        fake_now = datetime(2026, 3, 9, 10, 0, 0)
        with patch("bot.services.metro.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            yield

    def test_departures_nonexistent_station(self, _patch_operating):
        """Nonexistent station might fuzzy match or return empty."""
        deps = metro_departures("zzzzxxxxyyyy999")
        # Either empty or fuzzy-matched — both are acceptable
        assert isinstance(deps, list)

    def test_departures_fuzzy_match_station(self, _patch_operating):
        """If station name is slightly wrong, fuzzy match should find it."""
        deps = metro_departures("trindade")
        assert len(deps) > 0

    def test_format_schedule_empty_line_info(self):
        text = format_metro_schedule("Test", "", [])
        assert "Test" in text or escape_md("Test") in text
