"""Tests for new features: i18n, smart favorites, metro line viz, route autocomplete, nearby refresh."""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime


# ===================================================================
# i18n Tests
# ===================================================================

class TestI18nTranslations:
    """Test that all translation keys exist in both PT and EN."""

    def test_all_pt_keys_exist_in_en(self):
        from bot.utils.i18n import TRANSLATIONS
        pt_keys = set(TRANSLATIONS["pt"].keys())
        en_keys = set(TRANSLATIONS["en"].keys())
        missing = pt_keys - en_keys
        assert not missing, f"Missing EN translations: {missing}"

    def test_all_en_keys_exist_in_pt(self):
        from bot.utils.i18n import TRANSLATIONS
        pt_keys = set(TRANSLATIONS["pt"].keys())
        en_keys = set(TRANSLATIONS["en"].keys())
        missing = en_keys - pt_keys
        assert not missing, f"Missing PT translations: {missing}"

    def test_key_translation_keys_exist(self):
        """Check that critical keys exist."""
        from bot.utils.i18n import t
        critical_keys = [
            "bus_title", "metro_title", "loading", "retry",
            "kb_buses", "kb_metro", "kb_back", "kb_cancel",
            "kb_favorite", "kb_unfavorite", "kb_refresh",
            "fav_added", "fav_removed", "fav_already",
            "route_title", "route_ask_origin", "route_ask_dest",
            "no_results", "tip_direct_search",
        ]
        for key in critical_keys:
            pt = t(key, "pt")
            en = t(key, "en")
            assert pt != key, f"Missing PT translation for '{key}'"
            assert en != key, f"Missing EN translation for '{key}'"

    def test_t_returns_pt_for_unknown_lang(self):
        from bot.utils.i18n import t
        assert t("kb_buses", "fr") == t("kb_buses", "pt")

    def test_t_returns_key_for_unknown_key(self):
        from bot.utils.i18n import t
        assert t("nonexistent_key_xyz", "pt") == "nonexistent_key_xyz"

    def test_get_lang_defaults_to_pt(self):
        from bot.utils.i18n import get_lang
        update = MagicMock()
        update.effective_user = None
        assert get_lang(update) == "pt"

    def test_get_lang_detects_en(self):
        from bot.utils.i18n import get_lang
        update = MagicMock()
        update.effective_user.language_code = "en-US"
        assert get_lang(update) == "en"


# ===================================================================
# Smart Favorites Toggle Tests
# ===================================================================

class TestSmartFavoritesToggle:
    def test_bus_stop_keyboard_not_favorited(self):
        from bot.keyboards.inline import bus_stop_actions_keyboard
        kb = bus_stop_actions_keyboard("BCM2", is_fav=False)
        buttons = [btn for row in kb.inline_keyboard for btn in row]
        fav_btn = [b for b in buttons if "fav" in (b.callback_data or "")]
        assert len(fav_btn) == 1
        assert "fav:add" in fav_btn[0].callback_data

    def test_bus_stop_keyboard_favorited(self):
        from bot.keyboards.inline import bus_stop_actions_keyboard
        kb = bus_stop_actions_keyboard("BCM2", is_fav=True)
        buttons = [btn for row in kb.inline_keyboard for btn in row]
        fav_btn = [b for b in buttons if "fav" in (b.callback_data or "")]
        assert len(fav_btn) == 1
        assert "fav:remove" in fav_btn[0].callback_data

    def test_metro_station_keyboard_not_favorited(self):
        from bot.keyboards.inline import metro_station_actions_keyboard
        kb = metro_station_actions_keyboard("Trindade", is_fav=False)
        buttons = [btn for row in kb.inline_keyboard for btn in row]
        fav_btn = [b for b in buttons if "fav" in (b.callback_data or "")]
        assert len(fav_btn) == 1
        assert "fav:add" in fav_btn[0].callback_data

    def test_metro_station_keyboard_favorited(self):
        from bot.keyboards.inline import metro_station_actions_keyboard
        kb = metro_station_actions_keyboard("Trindade", is_fav=True)
        buttons = [btn for row in kb.inline_keyboard for btn in row]
        fav_btn = [b for b in buttons if "fav" in (b.callback_data or "")]
        assert len(fav_btn) == 1
        assert "fav:remove" in fav_btn[0].callback_data

    def test_default_is_not_favorited(self):
        """Default (no is_fav) should show add button."""
        from bot.keyboards.inline import bus_stop_actions_keyboard
        kb = bus_stop_actions_keyboard("BCM2")
        buttons = [btn for row in kb.inline_keyboard for btn in row]
        fav_btn = [b for b in buttons if "fav" in (b.callback_data or "")]
        assert "fav:add" in fav_btn[0].callback_data


# ===================================================================
# Metro Line Visualization Tests
# ===================================================================

class TestMetroLineVisualization:
    def test_format_metro_line_info_basic(self):
        from bot.utils.formatting import format_metro_line_info
        line_data = {"emoji": "🔵", "name": "Linha Azul", "route": "A → B"}
        stations = ["Station A", "Station B", "Station C"]
        text = format_metro_line_info("A", line_data, stations)
        assert "Linha Azul" in text
        assert "Station A" in text
        assert "Station B" in text
        assert "Station C" in text
        assert "│" in text  # Visual connector

    def test_format_metro_line_info_with_transfers(self):
        from bot.utils.formatting import format_metro_line_info
        line_data = {"emoji": "🔵", "name": "Linha Azul", "route": ""}
        stations = ["X", "Trindade", "Y"]
        stations_data = {
            "X": {"lines": ["A"]},
            "Trindade": {"lines": ["A", "B", "C", "D"]},
            "Y": {"lines": ["A"]},
        }
        text = format_metro_line_info("A", line_data, stations,
                                      stations_data=stations_data)
        assert "🔄" in text  # Transfer indicator for Trindade

    def test_format_metro_line_first_last_bold(self):
        from bot.utils.formatting import format_metro_line_info
        line_data = {"emoji": "🔵", "name": "Test", "route": ""}
        stations = ["First", "Middle", "Last"]
        text = format_metro_line_info("A", line_data, stations)
        # First and last should be bold (wrapped in *)
        assert "*First*" in text
        assert "*Last*" in text

    def test_metro_line_detail_keyboard_has_key_stations(self):
        from bot.keyboards.inline import metro_line_detail_keyboard
        stations = ["S1", "S2", "S3", "S4", "S5"]
        stations_data = {
            "S1": {"lines": ["A"]},
            "S2": {"lines": ["A"]},
            "S3": {"lines": ["A", "B"]},  # Transfer
            "S4": {"lines": ["A"]},
            "S5": {"lines": ["A"]},
        }
        kb = metro_line_detail_keyboard("A", stations,
                                         stations_data=stations_data)
        button_texts = [btn.text for row in kb.inline_keyboard for btn in row]
        # Should have first station, transfer station, last station
        assert any("S1" in t for t in button_texts)
        assert any("S3" in t for t in button_texts)  # Transfer station
        assert any("S5" in t for t in button_texts)

    def test_metro_line_detail_keyboard_real_data(self):
        """Test with real metro data."""
        from bot.keyboards.inline import metro_line_detail_keyboard
        from bot.services.metro import get_line_stations, STATIONS
        stations = get_line_stations("A")
        assert len(stations) > 5
        kb = metro_line_detail_keyboard("A", stations,
                                         stations_data=STATIONS)
        # Should have at least first + last + frequencies + back
        assert len(kb.inline_keyboard) >= 3

    def test_format_truncation(self):
        """Very long line info should be truncated."""
        from bot.utils.formatting import format_metro_line_info
        line_data = {"emoji": "🔵", "name": "Test", "route": ""}
        # Create 200 stations with long names
        stations = [f"Very Long Station Name Number {i}" for i in range(200)]
        text = format_metro_line_info("A", line_data, stations)
        assert len(text) <= 4100


# ===================================================================
# Route Planner Inline Autocomplete Tests
# ===================================================================

class TestRouteInlineAutocomplete:
    @pytest.mark.asyncio
    async def test_route_command_shows_inline_button(self):
        from bot.handlers.routes import route_command
        update = MagicMock()
        update.message.reply_text = AsyncMock()
        update.effective_user.language_code = "pt"
        context = MagicMock()
        context.user_data = {}

        await route_command(update, context)

        update.message.reply_text.assert_called_once()
        call_kwargs = update.message.reply_text.call_args[1]
        kb = call_kwargs["reply_markup"]
        # Check that keyboard has buttons (location or cancel)
        assert len(kb.inline_keyboard) >= 1

    @pytest.mark.asyncio
    async def test_route_plan_callback_shows_keyboard(self):
        from bot.handlers.routes import route_plan_callback
        query = AsyncMock()
        query.data = "route:plan"
        update = MagicMock()
        update.callback_query = query
        update.effective_user.language_code = "pt"
        context = MagicMock()
        context.user_data = {}

        await route_plan_callback(update, context)

        query.edit_message_text.assert_called_once()
        call_kwargs = query.edit_message_text.call_args[1]
        kb = call_kwargs["reply_markup"]
        assert len(kb.inline_keyboard) >= 1

    @pytest.mark.asyncio
    async def test_text_input_still_works_as_fallback(self):
        """Text input should still work even with inline autocomplete."""
        from bot.handlers.routes import handle_route_text_input
        update = MagicMock()
        update.message.text = "Trindade"
        update.message.reply_text = AsyncMock()
        update.effective_user.language_code = "pt"
        context = MagicMock()
        context.user_data = {
            "awaiting_route_origin": datetime.now(),
        }

        with patch("bot.handlers.routes.resolve_location") as mock_resolve:
            mock_resolve.return_value = {
                "type": "metro", "name": "Trindade",
                "lat": 41.1519, "lon": -8.6099,
                "lines": ["A", "B"],
            }
            result = await handle_route_text_input(update, context)

        assert result is True
        update.message.reply_text.assert_called_once()


# ===================================================================
# Nearby Refresh Tests
# ===================================================================

class TestNearbyRefresh:
    @pytest.mark.asyncio
    async def test_location_handler_stores_location(self):
        """Location handler should store coordinates for refresh."""
        from bot.handlers.location import location_handler
        update = MagicMock()
        update.message.location.latitude = 41.1496
        update.message.location.longitude = -8.6109
        update.message.reply_text = AsyncMock()
        update.effective_user.id = 12345
        update.effective_user.language_code = "pt"
        context = MagicMock()
        context.user_data = {}
        context.bot.send_message = AsyncMock()

        with patch("bot.handlers.location.get_user_settings", new_callable=AsyncMock) as mock_settings, \
             patch("bot.handlers.location.metro") as mock_metro, \
             patch("bot.handlers.location._get_nearby_bus_stops", new_callable=AsyncMock) as mock_bus:
            mock_settings.return_value = {
                "metro_radius_m": 500, "bus_radius_m": 200, "max_results": 5,
                "language": "auto",
            }
            mock_metro.get_nearby_stations.return_value = [{
                "name": "Trindade", "distance_m": 100,
                "lines": [{"emoji": "🔵", "code": "A", "name": "Azul"}],
            }]
            mock_bus.return_value = []

            await location_handler(update, context)

        assert "last_location" in context.user_data
        assert context.user_data["last_location"]["lat"] == 41.1496

    @pytest.mark.asyncio
    async def test_nearby_refresh_without_location(self):
        """Refresh without stored location should ask to send location again."""
        from bot.handlers.location import nearby_refresh_callback
        query = AsyncMock()
        query.data = "nearby:refresh"
        update = MagicMock()
        update.callback_query = query
        update.effective_user.language_code = "pt"
        context = MagicMock()
        context.user_data = {}

        await nearby_refresh_callback(update, context)

        query.edit_message_text.assert_called_once()


# ===================================================================
# Keyboard i18n Tests
# ===================================================================

class TestKeyboardI18n:
    def test_main_menu_keyboard_pt(self):
        from bot.keyboards.inline import main_menu_keyboard
        kb = main_menu_keyboard(lang="pt")
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert "🚌 Autocarros" in texts
        assert "🚇 Metro" in texts

    def test_main_menu_keyboard_en(self):
        from bot.keyboards.inline import main_menu_keyboard
        kb = main_menu_keyboard(lang="en")
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert "🚌 Buses" in texts
        assert "🚇 Metro" in texts

    def test_bus_menu_keyboard_en(self):
        from bot.keyboards.inline import bus_menu_keyboard
        kb = bus_menu_keyboard(lang="en")
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        # Should have English labels
        assert any("Main menu" in t or "Back" in t for t in texts)

    def test_metro_menu_keyboard_en(self):
        from bot.keyboards.inline import metro_menu_keyboard
        kb = metro_menu_keyboard(lang="en")
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert any("Main menu" in t or "Back" in t for t in texts)

    def test_keyboard_default_lang_is_pt(self):
        """Calling without lang should default to Portuguese."""
        from bot.keyboards.inline import main_menu_keyboard
        kb = main_menu_keyboard()
        texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert "🚌 Autocarros" in texts


# ===================================================================
# Favorites i18n Tests
# ===================================================================

class TestFavoritesI18n:
    @pytest.mark.asyncio
    async def test_favorites_add_en(self):
        """Add favorite callback should use English."""
        from bot.handlers.favorites import add_favorite_callback
        query = AsyncMock()
        query.data = "fav:add:bus:BCM2"
        update = MagicMock()
        update.callback_query = query
        update.effective_user.id = 123
        update.effective_user.language_code = "en"
        context = MagicMock()

        with patch("bot.handlers.favorites.is_favorite", new_callable=AsyncMock, return_value=False), \
             patch("bot.handlers.favorites.add_favorite", new_callable=AsyncMock), \
             patch("bot.services.stcp.get_stop_info", new_callable=AsyncMock, return_value={"name": "Boavista"}):
            await add_favorite_callback(update, context)

        query.answer.assert_called_once()
        answer_text = query.answer.call_args[0][0]
        # Should be in English
        assert "Added" in answer_text or "favorites" in answer_text.lower() or "⭐" in answer_text


# ===================================================================
# Local GTFS Fuzzy Search Tests
# ===================================================================

class TestLocalGtfsFuzzySearch:
    def test_search_stops_local_empty_query(self):
        from bot.services.stcp import search_stops_local
        assert search_stops_local("") == []
        assert search_stops_local("  ") == []

    def test_search_stops_local_no_data(self):
        from bot.services.stcp import search_stops_local
        import bot.services.stcp as stcp_mod
        original = stcp_mod._gtfs_bus_stops
        stcp_mod._gtfs_bus_stops = []
        try:
            assert search_stops_local("test") == []
        finally:
            stcp_mod._gtfs_bus_stops = original

    def test_search_stops_local_with_data(self):
        from bot.services.stcp import search_stops_local
        import bot.services.stcp as stcp_mod
        original = stcp_mod._gtfs_bus_stops
        stcp_mod._gtfs_bus_stops = [
            {"stop_id": "BCM2", "name": "Boavista - Casa da Música", "lat": 41.1, "lon": -8.6},
            {"stop_id": "BCM1", "name": "Boavista - Casa da Música", "lat": 41.1, "lon": -8.6},
            {"stop_id": "TRD1", "name": "Trindade", "lat": 41.2, "lon": -8.5},
        ]
        try:
            # Search by code prefix
            results = search_stops_local("BCM")
            assert len(results) == 2
            assert all("BCM" in r["stop_id"] for r in results)

            # Search by name
            results = search_stops_local("Trindade")
            assert len(results) >= 1
            assert results[0]["name"] == "Trindade"
        finally:
            stcp_mod._gtfs_bus_stops = original
