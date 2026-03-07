"""Tests for the inline query handler."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.handlers.inline import (
    inline_query_handler,
    _add_metro_stations,
    _add_bus_stop_by_code,
    _add_bus_stops_by_name,
)


class TestInlineQueryHandler:
    """Test inline query handler routing."""

    @pytest.mark.asyncio
    async def test_empty_query_returns_hint(self):
        update = MagicMock()
        update.inline_query.query = ""
        update.inline_query.answer = AsyncMock()
        context = MagicMock()

        await inline_query_handler(update, context)

        update.inline_query.answer.assert_called_once()
        results = update.inline_query.answer.call_args[0][0]
        assert len(results) == 1
        assert "Escreve" in results[0].title

    @pytest.mark.asyncio
    async def test_code_query_searches_bus(self):
        update = MagicMock()
        update.inline_query.query = "BCM2"
        update.inline_query.answer = AsyncMock()
        context = MagicMock()

        with patch("bot.handlers.inline.stcp") as mock_stcp, \
             patch("bot.handlers.inline.search_stations", return_value=[]):
            mock_stcp.get_stop_real_time = AsyncMock(return_value={
                "stop_name": "Boavista",
                "arrivals": [
                    {"line": "204", "destination": "Marquês", "time": "3 min"},
                ],
            })

            await inline_query_handler(update, context)

        update.inline_query.answer.assert_called_once()
        results = update.inline_query.answer.call_args[0][0]
        # Should have at least the bus stop result
        assert any("BCM2" in r.title for r in results)

    @pytest.mark.asyncio
    async def test_name_query_searches_metro_and_bus(self):
        update = MagicMock()
        update.inline_query.query = "Trindade"
        update.inline_query.answer = AsyncMock()
        context = MagicMock()

        with patch("bot.handlers.inline.search_stations") as mock_search, \
             patch("bot.handlers.inline.get_next_departures") as mock_deps, \
             patch("bot.handlers.inline.stcp") as mock_stcp:
            mock_search.return_value = [{
                "name": "Trindade",
                "lines": [{"emoji": "🔵", "name": "Linha Azul", "code": "A"}],
            }]
            mock_deps.return_value = [
                {"direction": "Matosinhos", "time": "3 min", "line": "A"},
            ]
            mock_stcp.search_stops = AsyncMock(return_value=[])

            await inline_query_handler(update, context)

        update.inline_query.answer.assert_called_once()
        results = update.inline_query.answer.call_args[0][0]
        assert any("Trindade" in r.title for r in results)


class TestAddMetroStations:
    """Test metro station search for inline results."""

    def test_adds_results_for_matching_stations(self):
        results = []
        with patch("bot.handlers.inline.search_stations") as mock_search, \
             patch("bot.handlers.inline.get_next_departures") as mock_deps:
            mock_search.return_value = [{
                "name": "Bolhão",
                "lines": [{"emoji": "🔵", "name": "Azul", "code": "A"}],
            }]
            mock_deps.return_value = [
                {"direction": "Matosinhos", "time": "5 min", "line": "A"},
            ]

            _add_metro_stations("Bolhão", results)

        assert len(results) == 1
        assert "Bolhão" in results[0].title

    def test_no_results_for_no_match(self):
        results = []
        with patch("bot.handlers.inline.search_stations", return_value=[]):
            _add_metro_stations("nonexistent", results)

        assert len(results) == 0

    def test_handles_service_closed(self):
        results = []
        with patch("bot.handlers.inline.search_stations") as mock_search, \
             patch("bot.handlers.inline.get_next_departures") as mock_deps:
            mock_search.return_value = [{
                "name": "Trindade",
                "lines": [],
            }]
            mock_deps.return_value = [
                {"direction": "Serviço encerrado", "time": "", "line": ""},
            ]

            _add_metro_stations("Trindade", results)

        assert len(results) == 1
        # Should show "Sem partidas" since direction starts with "Serviço"
        assert "Sem partidas" in results[0].input_message_content.message_text


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


class TestAddBusStopsByName:
    """Test bus stop name search for inline results."""

    @pytest.mark.asyncio
    async def test_adds_results_for_matching_stops(self):
        results = []
        with patch("bot.handlers.inline.stcp") as mock_stcp:
            mock_stcp.search_stops = AsyncMock(return_value=[
                {"code": "BCM2", "name": "Boavista - Casa da Música"},
            ])
            mock_stcp.get_stop_real_time = AsyncMock(return_value={
                "stop_name": "Boavista",
                "arrivals": [
                    {"line": "204", "destination": "Marquês", "time": "5 min"},
                ],
            })

            await _add_bus_stops_by_name("Boavista", results)

        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_no_results_on_empty_search(self):
        results = []
        with patch("bot.handlers.inline.stcp") as mock_stcp:
            mock_stcp.search_stops = AsyncMock(return_value=[])

            await _add_bus_stops_by_name("nonexistent", results)

        assert len(results) == 0
