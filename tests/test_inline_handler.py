"""Tests for the inline query handler."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.handlers.inline import (
    inline_query_handler,
    _add_metro_stations_quick,
    _add_metrobus_stops_quick,
    _add_train_stations_quick,
    _add_bus_stop_by_code,
    _add_bus_stops_quick,
    _inline_lang,
    _t,
)


def _inline_update(query: str, lang="pt"):
    """Build an inline-query update whose from_user has a real language code."""
    update = MagicMock()
    update.inline_query.query = query
    update.inline_query.from_user.language_code = lang
    update.inline_query.answer = AsyncMock()
    return update


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
        # 4 hints: quick search, bus, metro, train
        assert len(results) == 4
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


# ===================================================================
# Train inline mode (the "train " prefix used to fall through to a
# literal text search and always answered "no results")
# ===================================================================

class TestTrainInlineMode:
    """'train <name>' must reach the CP station search."""

    @pytest.mark.asyncio
    async def test_train_prefix_returns_cp_stations(self):
        update = _inline_update("train Campanha")
        context = MagicMock()

        await inline_query_handler(update, context)

        results = update.inline_query.answer.call_args[0][0]
        assert results, "train prefix must return CP station results"
        assert any("Campanh" in r.title for r in results)

    @pytest.mark.asyncio
    async def test_train_prefix_does_not_search_bus_or_metro(self):
        update = _inline_update("train Ermesinde")
        context = MagicMock()

        with patch("bot.handlers.inline.search_stations") as mock_metro, \
             patch("bot.handlers.inline.stcp") as mock_stcp:
            await inline_query_handler(update, context)

        mock_metro.assert_not_called()
        mock_stcp.search_stops.assert_not_called()

    @pytest.mark.asyncio
    async def test_train_results_have_station_callback_button(self):
        update = _inline_update("train Campanha")
        context = MagicMock()

        await inline_query_handler(update, context)

        results = update.inline_query.answer.call_args[0][0]
        buttons = [b for r in results if r.reply_markup
                   for row in r.reply_markup.inline_keyboard for b in row]
        assert buttons, "train results must carry a 'see times' button"
        assert all(b.callback_data.startswith("train:station:") for b in buttons)

    @pytest.mark.asyncio
    async def test_train_prefix_without_query_shows_hint(self):
        update = _inline_update("train ")
        context = MagicMock()

        await inline_query_handler(update, context)

        results = update.inline_query.answer.call_args[0][0]
        assert len(results) == 1
        assert "CP" in results[0].title or "station" in results[0].title.lower()

    def test_all_mode_includes_trains(self):
        results = []
        _add_train_stations_quick("Ermesinde", results)
        assert len(results) == 1
        assert "Ermesinde" in results[0].title

    @pytest.mark.asyncio
    async def test_bare_query_searches_trains_too(self):
        """No prefix should search every mode, trains included."""
        update = _inline_update("Ermesinde")
        context = MagicMock()

        with patch("bot.handlers.inline.search_stops_local", return_value=[]), \
             patch("bot.handlers.inline.stcp") as mock_stcp, \
             patch("bot.handlers.inline.search_stations", return_value=[]):
            mock_stcp.search_stops = AsyncMock(return_value=[])
            await inline_query_handler(update, context)

        results = update.inline_query.answer.call_args[0][0]
        assert any("Ermesinde" in r.title for r in results)


# ===================================================================
# Localization + per-user caching
# ===================================================================

class TestInlineLocalization:
    def test_inline_lang_reads_from_user(self):
        q = MagicMock()
        q.from_user.language_code = "en-GB"
        assert _inline_lang(q) == "en"

    def test_inline_lang_defaults_to_pt(self):
        q = MagicMock()
        q.from_user.language_code = "de"  # unsupported
        assert _inline_lang(q) == "pt"

    def test_inline_lang_survives_missing_from_user(self):
        q = MagicMock()
        q.from_user.language_code = None
        assert _inline_lang(q) == "pt"

    def test_translations_differ_between_languages(self):
        for key in ("inline_hint_quick_title", "inline_no_results_title",
                    "inline_view_times", "inline_zone", "inline_bus_stop"):
            assert _t(key, "en") != _t(key, "pt"), key

    def test_no_raw_keys_leak(self):
        """_t must never return the key itself."""
        for key in ("inline_hint_train_title", "inline_typing_train_desc",
                    "inline_lines", "inline_metrobus_label"):
            for lang in ("pt", "en"):
                assert _t(key, lang) != key

    @pytest.mark.asyncio
    async def test_hints_localized_in_english(self):
        update = _inline_update("", lang="en")
        context = MagicMock()

        await inline_query_handler(update, context)

        results = update.inline_query.answer.call_args[0][0]
        titles = " ".join(r.title for r in results)
        assert "Search" in titles
        assert "Pesquisar" not in titles

    @pytest.mark.asyncio
    async def test_no_results_localized(self):
        update = _inline_update("zzzznotarealplace", lang="en")
        context = MagicMock()

        with patch("bot.handlers.inline.search_stops_local", return_value=[]), \
             patch("bot.handlers.inline.stcp") as mock_stcp, \
             patch("bot.handlers.inline.search_stations", return_value=[]):
            mock_stcp.search_stops = AsyncMock(return_value=[])
            await inline_query_handler(update, context)

        results = update.inline_query.answer.call_args[0][0]
        assert len(results) == 1
        assert "No results" in results[0].title

    @pytest.mark.asyncio
    async def test_metro_results_localized(self):
        update = _inline_update("metro Trindade", lang="en")
        context = MagicMock()

        await inline_query_handler(update, context)

        results = update.inline_query.answer.call_args[0][0]
        buttons = [b for r in results if r.reply_markup
                   for row in r.reply_markup.inline_keyboard for b in row]
        assert buttons
        assert all("See times" in b.text for b in buttons)

    @pytest.mark.asyncio
    async def test_results_are_personal(self):
        """Language-dependent results must not be cached across users."""
        update = _inline_update("metro Trindade")
        context = MagicMock()

        await inline_query_handler(update, context)

        assert update.inline_query.answer.call_args.kwargs["is_personal"] is True

    @pytest.mark.asyncio
    async def test_hint_answers_are_personal(self):
        update = _inline_update("")
        context = MagicMock()

        await inline_query_handler(update, context)

        assert update.inline_query.answer.call_args.kwargs["is_personal"] is True

    @pytest.mark.asyncio
    async def test_typing_hint_answers_are_personal(self):
        update = _inline_update("metro ")
        context = MagicMock()

        await inline_query_handler(update, context)

        assert update.inline_query.answer.call_args.kwargs["is_personal"] is True


# ===================================================================
# Bus inline results must offer a button, not a command to type
# ===================================================================

class TestBusInlineButton:
    @pytest.mark.asyncio
    async def test_bus_result_has_stop_callback_button(self):
        results = []
        with patch("bot.handlers.inline.search_stops_local", return_value=[
                {"code": "BCM2", "stop_id": "BCM2", "name": "Boavista", "zone": "PRT"},
        ]):
            await _add_bus_stops_quick("Boavista", results)

        assert len(results) == 1
        markup = results[0].reply_markup
        assert markup is not None, "bus results must carry a button"
        button = markup.inline_keyboard[0][0]
        assert button.callback_data == "bus:stop:BCM2"

    @pytest.mark.asyncio
    async def test_bus_result_does_not_tell_user_to_type_a_command(self):
        results = []
        with patch("bot.handlers.inline.search_stops_local", return_value=[
                {"code": "BCM2", "stop_id": "BCM2", "name": "Boavista", "zone": ""},
        ]):
            await _add_bus_stops_quick("Boavista", results)

        text = results[0].input_message_content.message_text
        assert "/stop" not in text

    @pytest.mark.asyncio
    async def test_bus_code_lookup_has_button(self):
        results = []
        with patch("bot.handlers.inline.stcp") as mock_stcp:
            mock_stcp.get_stop_real_time = AsyncMock(return_value={
                "stop_name": "Boavista",
                "arrivals": [{"line": "204", "destination": "X", "time": "3 min"}],
            })
            await _add_bus_stop_by_code("BCM2", results)

        assert results[0].reply_markup.inline_keyboard[0][0].callback_data == "bus:stop:BCM2"


# ===================================================================
# callback_data byte limits (Telegram hard-rejects over 64 bytes)
# ===================================================================

class TestInlineCallbackDataLimits:
    def _all_callback_data(self, results):
        return [b.callback_data for r in results if r.reply_markup
                for row in r.reply_markup.inline_keyboard for b in row]

    def test_metro_station_callbacks_within_limit(self):
        from bot.services.metro import STATIONS
        results = []
        for name in STATIONS:
            _add_metro_stations_quick(name, results)
        data = self._all_callback_data(results)
        assert data
        for d in data:
            assert len(d.encode("utf-8")) <= 64, d

    def test_train_station_callbacks_within_limit(self):
        from bot.services.cp import STATIONS
        results = []
        for name in STATIONS:
            _add_train_stations_quick(name, results)
        data = self._all_callback_data(results)
        assert data
        for d in data:
            assert len(d.encode("utf-8")) <= 64, d

    def test_metrobus_stop_callbacks_within_limit(self):
        from bot.services.metrobus import STOPS
        results = []
        for name in STOPS:
            _add_metrobus_stops_quick(name, results)
        data = self._all_callback_data(results)
        assert data
        for d in data:
            assert len(d.encode("utf-8")) <= 64, d

    def test_overlong_callback_data_is_dropped_not_raised(self):
        """A pathologically long name must not produce an invalid button."""
        long_name = "Ã" * 60
        results = []
        with patch("bot.handlers.inline.search_train_stations", return_value=[
                {"name": long_name, "lines": [], "lat": 0, "lon": 0},
        ]):
            _add_train_stations_quick("x", results)

        assert len(results) == 1
        assert results[0].reply_markup is None


# ===================================================================
# Mode prefixes must survive the exact text the keyboards pre-fill
# ===================================================================

class TestModePrefixParsing:
    """switch_inline_query_current_chat pre-fills "<mode> " with a trailing
    space; the handler used to strip it and then search for the literal word."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("mode", ["bus", "metro", "metrobus", "train"])
    async def test_prefilled_prefix_shows_its_own_hint(self, mode):
        update = _inline_update(f"{mode} ")
        context = MagicMock()

        await inline_query_handler(update, context)

        results = update.inline_query.answer.call_args[0][0]
        assert len(results) == 1, f"'{mode} ' should show exactly one hint"
        assert results[0].title == _t(f"inline_typing_{mode}_title", "pt")
        assert results[0].description == _t(f"inline_typing_{mode}_desc", "pt")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bare", ["bus", "metro", "metrobus", "train"])
    async def test_bare_mode_word_is_a_mode_not_a_search(self, bare):
        update = _inline_update(bare)
        context = MagicMock()

        await inline_query_handler(update, context)

        results = update.inline_query.answer.call_args[0][0]
        assert len(results) == 1
        assert "Sem resultados" not in results[0].title

    @pytest.mark.asyncio
    async def test_metrobus_prefix_wins_over_metro(self):
        update = _inline_update("metrobus Boavista")
        context = MagicMock()

        with patch("bot.handlers.inline.search_stations") as mock_metro:
            await inline_query_handler(update, context)

        mock_metro.assert_not_called()
        results = update.inline_query.answer.call_args[0][0]
        assert results
        assert all(b.callback_data.startswith("metrobus:stop:")
                   for r in results if r.reply_markup
                   for row in r.reply_markup.inline_keyboard for b in row)
