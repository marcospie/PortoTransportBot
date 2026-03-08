"""Tests for the inline query handler."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.handlers.inline import (
    inline_query_handler,
    _add_metro_stations_quick,
    _add_bus_stop_by_code,
    _add_bus_stops_quick,
)


class TestInlineQueryHandler:
    """Test inline query handler routing."""

    @pytest.mark.asyncio
    async def test_empty_query_returns_hints(self):
        update = MagicMock()
        update.inline_query.query = ""
        update.inline_query.answer = AsyncMock()
        context = MagicMock()

        await inline_query_handler(update, context)

        update.inline_query.answer.assert_called_once()
        results = update.inline_query.answer.call_args[0][0]
        assert len(results) == 3  # 3 hints: quick search, bus, metro
        assert "Pesquisa" in results[0].title

    @pytest.mark.asyncio
    async def test_code_query_searches_bus(self):
        update = MagicMock()
        update.inline_query.query = "BCM2"
        update.inline_query.answer = AsyncMock()
        context = MagicMock()

        with patch("bot.handlers.inline.search_stops_local", return_value=[
                 {"code": "BCM2", "stop_id": "BCM2", "name": "Boavista - Casa da Música", "zone": ""},
             ]), \
             patch("bot.handlers.inline.stcp") as mock_stcp, \
             patch("bot.handlers.inline.search_stations", return_value=[]):

            await inline_query_handler(update, context)

        update.inline_query.answer.assert_called_once()
        results = update.inline_query.answer.call_args[0][0]
        assert any("Boavista" in r.title for r in results)

    @pytest.mark.asyncio
    async def test_name_query_searches_metro_and_bus(self):
        update = MagicMock()
        update.inline_query.query = "Trindade"
        update.inline_query.answer = AsyncMock()
        context = MagicMock()

        with patch("bot.handlers.inline.search_stations") as mock_search, \
             patch("bot.handlers.inline.search_stops_local", return_value=[]), \
             patch("bot.handlers.inline.stcp") as mock_stcp:
            mock_search.return_value = [{
                "name": "Trindade",
                "zone": "PRT",
                "lines": [{"emoji": "🔵", "name": "Linha Azul", "code": "A"}],
            }]
            mock_stcp.search_stops = AsyncMock(return_value=[])

            await inline_query_handler(update, context)

        update.inline_query.answer.assert_called_once()
        results = update.inline_query.answer.call_args[0][0]
        assert any("Trindade" in r.title for r in results)

    @pytest.mark.asyncio
    async def test_bus_prefix_searches_only_bus(self):
        update = MagicMock()
        update.inline_query.query = "bus Bolhão"
        update.inline_query.answer = AsyncMock()
        context = MagicMock()

        with patch("bot.handlers.inline.search_stops_local", return_value=[
                 {"code": "BLH1", "stop_id": "BLH1", "name": "Bolhão", "zone": "PRT"},
             ]), \
             patch("bot.handlers.inline.stcp") as mock_stcp, \
             patch("bot.handlers.inline.search_stations") as mock_metro:

            await inline_query_handler(update, context)

        # Metro search should NOT be called
        mock_metro.assert_not_called()

    @pytest.mark.asyncio
    async def test_metro_prefix_searches_only_metro(self):
        update = MagicMock()
        update.inline_query.query = "metro Trindade"
        update.inline_query.answer = AsyncMock()
        context = MagicMock()

        with patch("bot.handlers.inline.search_stations") as mock_search, \
             patch("bot.handlers.inline.stcp") as mock_stcp:
            mock_search.return_value = [{
                "name": "Trindade",
                "zone": "PRT",
                "lines": [{"emoji": "🔵", "name": "Linha Azul", "code": "A"}],
            }]

            await inline_query_handler(update, context)

        # Bus search should NOT be called
        mock_stcp.search_stops.assert_not_called()


class TestAddMetroStationsQuick:
    """Test metro station quick search for inline results."""

    def test_adds_results_for_matching_stations(self):
        results = []
        with patch("bot.handlers.inline.search_stations") as mock_search:
            mock_search.return_value = [{
                "name": "Bolhão",
                "zone": "PRT",
                "lines": [{"emoji": "🔵", "name": "Azul", "code": "A"}],
            }]

            _add_metro_stations_quick("Bolhão", results)

        assert len(results) == 1
        assert "Bolhão" in results[0].title

    def test_no_results_for_no_match(self):
        results = []
        with patch("bot.handlers.inline.search_stations", return_value=[]):
            _add_metro_stations_quick("nonexistent", results)

        assert len(results) == 0


class TestAddBusStopByCode:
    """Test bus stop code lookup for inline results."""

    @pytest.mark.asyncio
    async def test_adds_result_for_valid_code(self):
        results = []
        with patch("bot.handlers.inline.stcp") as mock_stcp:
            mock_stcp.get_stop_real_time = AsyncMock(return_value={
                "stop_name": "Boavista",
                "arrivals": [
                    {"line": "204", "destination": "Marquês", "time": "3 min"},
                ],
            })

            await _add_bus_stop_by_code("BCM2", results)

        assert len(results) == 1
        assert "BCM2" in results[0].title

    @pytest.mark.asyncio
    async def test_no_result_on_api_error(self):
        results = []
        with patch("bot.handlers.inline.stcp") as mock_stcp:
            mock_stcp.get_stop_real_time = AsyncMock(side_effect=Exception("API error"))

            await _add_bus_stop_by_code("NOPE", results)

        assert len(results) == 0


class TestAddBusStopsQuick:
    """Test bus stop name quick search for inline results."""

    @pytest.mark.asyncio
    async def test_adds_results_for_matching_stops(self):
        results = []
        with patch("bot.handlers.inline.stcp") as mock_stcp:
            mock_stcp.search_stops = AsyncMock(return_value=[
                {"code": "BCM2", "stop_id": "BCM2", "name": "Boavista - Casa da Música", "zone": "PRT"},
            ])

            await _add_bus_stops_quick("Boavista", results)

        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_no_results_on_empty_search(self):
        results = []
        with patch("bot.handlers.inline.stcp") as mock_stcp:
            mock_stcp.search_stops = AsyncMock(return_value=[])

            await _add_bus_stops_quick("nonexistent", results)

        assert len(results) == 0
