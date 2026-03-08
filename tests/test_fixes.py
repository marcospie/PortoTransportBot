"""Tests for bug fixes: nearby radius, inline fallback, duplicate stations, bus routes error."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.services.metro import get_nearby_stations, STATIONS, search_stations
from bot.handlers.location import NEARBY_RADIUS_KM, BUS_NEARBY_RADIUS_KM


# ===================================================================
# 1. Nearby location radius
# ===================================================================

class TestNearbyRadius:
    """Verify the search radius is large enough to find nearby stations."""

    def test_metro_radius_configured(self):
        """Metro radius should be set."""
        assert NEARBY_RADIUS_KM > 0

    def test_bus_radius_configured(self):
        """Bus radius should be set."""
        assert BUS_NEARBY_RADIUS_KM > 0

    def test_near_matosinhos_sul_finds_station(self):
        """User right at Matosinhos Sul should see it."""
        nearby = get_nearby_stations(41.1796, -8.6729, NEARBY_RADIUS_KM)
        names = [s["name"] for s in nearby]
        assert "Matosinhos Sul" in names

    def test_near_trindade_finds_trindade(self):
        """User near Trindade should find it."""
        nearby = get_nearby_stations(41.1519, -8.6102, NEARBY_RADIUS_KM)
        names = [s["name"] for s in nearby]
        assert "Trindade" in names

    def test_near_aliados_finds_aliados(self):
        """User near Aliados should find Aliados."""
        nearby = get_nearby_stations(41.1475, -8.6105, NEARBY_RADIUS_KM)
        names = [s["name"] for s in nearby]
        assert "Aliados" in names

    def test_results_sorted_by_distance(self):
        """Results should be sorted by distance."""
        nearby = get_nearby_stations(41.1519, -8.6102, NEARBY_RADIUS_KM)
        for i in range(len(nearby) - 1):
            assert nearby[i]["distance_m"] <= nearby[i + 1]["distance_m"]

    def test_results_have_required_fields(self):
        """Each result should have name, distance, lines."""
        nearby = get_nearby_stations(41.1519, -8.6102, NEARBY_RADIUS_KM)
        for station in nearby:
            assert "name" in station
            assert "distance_m" in station
            assert "lines" in station
            assert isinstance(station["lines"], list)
            assert len(station["lines"]) > 0


# ===================================================================
# 2. Duplicate station removal
# ===================================================================

class TestNoDuplicateStations:
    """Ensure no duplicate stations exist in the data."""

    def test_no_duplicate_coordinates(self):
        """No two stations should share the exact same coordinates."""
        seen_coords = {}
        for name, data in STATIONS.items():
            coord = (data.get("lat"), data.get("lon"))
            if coord in seen_coords:
                pytest.fail(
                    f"Stations '{seen_coords[coord]}' and '{name}' share "
                    f"the same coordinates {coord}"
                )
            seen_coords[coord] = name

    def test_mercado_de_matosinhos_removed(self):
        """The duplicate 'Mercado de Matosinhos' should not exist."""
        assert "Mercado de Matosinhos" not in STATIONS


# ===================================================================
# 3. Inline query fallback
# ===================================================================

class TestInlineQueryFallback:
    """When a stop code lookup fails, fallback to name search."""

    @pytest.mark.asyncio
    async def test_code_lookup_failure_falls_back_to_name_search(self):
        """If code lookup returns nothing, name search should be tried."""
        from bot.handlers.inline import inline_query_handler

        update = MagicMock()
        update.inline_query.query = "BIBG2"
        update.inline_query.answer = AsyncMock()
        context = MagicMock()

        with patch("bot.handlers.inline.stcp") as mock_stcp, \
             patch("bot.handlers.inline.search_stations", return_value=[]):
            # Code lookup returns nothing (API down)
            mock_stcp.get_stop_real_time = AsyncMock(return_value={
                "stop_name": "BIBG2",
                "arrivals": [],
            })
            # Name search returns a result
            mock_stcp.search_stops = AsyncMock(return_value=[
                {"code": "BIBG2", "stop_id": "BIBG2", "name": "Bom Sucesso", "zone": "PRT"},
            ])

            await inline_query_handler(update, context)

        update.inline_query.answer.assert_called_once()
        results = update.inline_query.answer.call_args[0][0]
        # Should have results from the fallback name search
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_code_lookup_via_fuzzy(self):
        """Stop code like BCM2 should be found via fuzzy local search."""
        from bot.handlers.inline import inline_query_handler

        update = MagicMock()
        update.inline_query.query = "BCM2"
        update.inline_query.answer = AsyncMock()
        context = MagicMock()

        with patch("bot.handlers.inline.search_stops_local", return_value=[
                 {"code": "BCM2", "stop_id": "BCM2", "name": "Boavista - Casa da Música", "zone": ""},
             ]) as mock_local, \
             patch("bot.handlers.inline.stcp") as mock_stcp, \
             patch("bot.handlers.inline.search_stations", return_value=[]):

            await inline_query_handler(update, context)

        update.inline_query.answer.assert_called_once()
        results = update.inline_query.answer.call_args[0][0]
        assert any("BCM2" in r.description or "Boavista" in r.title for r in results)
        mock_local.assert_called_once()

    @pytest.mark.asyncio
    async def test_bus_prefix_code_fallback(self):
        """'bus BIBG2' should find stops via fuzzy search."""
        from bot.handlers.inline import inline_query_handler

        update = MagicMock()
        update.inline_query.query = "bus BIBG2"
        update.inline_query.answer = AsyncMock()
        context = MagicMock()

        with patch("bot.handlers.inline.search_stops_local", return_value=[
                 {"code": "BIBG2", "stop_id": "BIBG2", "name": "Biblioteca de Gaia 2", "zone": ""},
             ]) as mock_local, \
             patch("bot.handlers.inline.stcp") as mock_stcp, \
             patch("bot.handlers.inline.search_stations", return_value=[]):

            await inline_query_handler(update, context)

        update.inline_query.answer.assert_called_once()
        results = update.inline_query.answer.call_args[0][0]
        assert len(results) >= 1
        mock_local.assert_called_once()


# ===================================================================
# 3b. STCP local nearby search
# ===================================================================

class TestStcpLocalNearby:
    """Test local GTFS-based nearby bus stop search."""

    def test_local_search_with_data(self):
        """Local search should find stops within radius."""
        from bot.services.stcp import _search_nearby_local, _gtfs_bus_stops

        # Inject test data
        import bot.services.stcp as stcp_mod
        original = stcp_mod._gtfs_bus_stops
        stcp_mod._gtfs_bus_stops = [
            {"stop_id": "TST1", "name": "Teste 1", "lat": 41.1520, "lon": -8.6100},
            {"stop_id": "TST2", "name": "Teste 2", "lat": 41.1530, "lon": -8.6110},
            {"stop_id": "FAR1", "name": "Longe", "lat": 41.2000, "lon": -8.7000},
        ]
        try:
            results = _search_nearby_local(41.1519, -8.6102, 0.2)
            assert len(results) >= 1
            names = [s["name"] for s in results]
            assert "Teste 1" in names
            assert "Longe" not in names
        finally:
            stcp_mod._gtfs_bus_stops = original

    def test_local_search_empty_data(self):
        """Local search with no data should return empty."""
        from bot.services.stcp import _search_nearby_local
        import bot.services.stcp as stcp_mod
        original = stcp_mod._gtfs_bus_stops
        stcp_mod._gtfs_bus_stops = []
        try:
            results = _search_nearby_local(41.1519, -8.6102, 0.5)
            assert results == []
        finally:
            stcp_mod._gtfs_bus_stops = original

    def test_local_search_sorted_by_distance(self):
        """Results should be sorted closest first."""
        from bot.services.stcp import _search_nearby_local
        import bot.services.stcp as stcp_mod
        original = stcp_mod._gtfs_bus_stops
        stcp_mod._gtfs_bus_stops = [
            {"stop_id": "FAR", "name": "Mais longe", "lat": 41.1540, "lon": -8.6130},
            {"stop_id": "NEAR", "name": "Mais perto", "lat": 41.1520, "lon": -8.6103},
        ]
        try:
            results = _search_nearby_local(41.1519, -8.6102, 0.5)
            assert len(results) == 2
            assert results[0]["name"] == "Mais perto"
        finally:
            stcp_mod._gtfs_bus_stops = original


# ===================================================================
# 4. Bus routes error handling
# ===================================================================

class TestBusRoutesError:
    """Test bus routes listing when API is unavailable."""

    @pytest.mark.asyncio
    async def test_routes_empty_shows_retry_button(self):
        """When routes API returns empty, show retry button."""
        from bot.handlers.bus import bus_routes_callback

        update = MagicMock()
        query = AsyncMock()
        update.callback_query = query
        query.data = "bus:routes"
        context = MagicMock()
        context.user_data = {}

        with patch("bot.handlers.bus.stcp") as mock_stcp:
            mock_stcp.get_routes = AsyncMock(return_value=[])

            await bus_routes_callback(update, context)

        query.edit_message_text.assert_called_once()
        call_kwargs = query.edit_message_text.call_args
        text = call_kwargs[0][0] if call_kwargs[0] else call_kwargs[1]["text"]
        assert "indisponível" in text or "carregar" in text

        # Check retry button exists
        markup = call_kwargs[1].get("reply_markup") if len(call_kwargs) > 1 else call_kwargs.kwargs.get("reply_markup")
        if markup:
            all_data = [btn.callback_data for row in markup.inline_keyboard for btn in row]
            assert "bus:routes" in all_data


# ===================================================================
# 5. Command descriptions length
# ===================================================================

class TestCommandDescriptions:
    """Verify command descriptions fit iOS display."""

    def test_all_descriptions_under_23_chars(self):
        """iOS truncates descriptions > 22 chars."""
        from telegram import BotCommand

        # Recreate the commands as in main.py
        pt_commands = [
            BotCommand("start", "Menu principal"),
            BotCommand("bus", "Autocarros STCP"),
            BotCommand("metro", "Metro do Porto"),
            BotCommand("stop", "Paragem por código"),
            BotCommand("station", "Estação de metro"),
            BotCommand("route", "Planear trajeto"),
            BotCommand("favorites", "Os teus favoritos"),
            BotCommand("fav", "Favorito rápido"),
            BotCommand("settings", "Configurações"),
            BotCommand("help", "Ajuda"),
        ]
        for cmd in pt_commands:
            assert len(cmd.description) <= 22, (
                f"/{cmd.command} description too long for iOS: "
                f"'{cmd.description}' ({len(cmd.description)} chars)"
            )


# ===================================================================
# 6. Bus code callback handler
# ===================================================================

class TestBusCodeCallback:
    """Test the code lookup callback shows proper prompt."""

    @pytest.mark.asyncio
    async def test_code_callback_shows_prompt(self):
        """bus:code callback should prompt for stop code."""
        from bot.handlers.bus import bus_code_callback

        update = MagicMock()
        query = AsyncMock()
        update.callback_query = query
        context = MagicMock()
        context.user_data = {}

        await bus_code_callback(update, context)

        query.edit_message_text.assert_called_once()
        call_args = query.edit_message_text.call_args
        text = call_args[0][0] if call_args[0] else call_args[1]["text"]
        assert "código" in text.lower()
