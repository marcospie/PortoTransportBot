"""Tests for UI improvements: cancel buttons, AWAITING flags, onboarding, deep links."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from bot.keyboards.inline import (
    cancel_keyboard,
    onboarding_keyboard,
    bus_menu_keyboard,
    favorites_keyboard,
)
from bot.handlers.start import _clear_awaiting


# ===================================================================
# Cancel keyboard tests
# ===================================================================


class TestCancelKeyboard:
    def test_default_back_to_bus(self):
        kb = cancel_keyboard()
        btn = kb.inline_keyboard[0][0]
        assert btn.callback_data == "menu:bus"
        assert "Cancelar" in btn.text

    def test_custom_back_to(self):
        kb = cancel_keyboard("menu:metro")
        btn = kb.inline_keyboard[0][0]
        assert btn.callback_data == "menu:metro"


# ===================================================================
# Onboarding keyboard tests
# ===================================================================


class TestOnboardingKeyboard:
    def test_has_location_button(self):
        kb = onboarding_keyboard()
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "onboard:location" in all_data

    def test_has_search_buttons(self):
        kb = onboarding_keyboard()
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "bus:find" in all_data
        assert "metro:search" in all_data


# ===================================================================
# Clear awaiting tests
# ===================================================================


class TestClearAwaiting:
    def test_clears_all_flags(self):
        context = MagicMock()
        context.user_data = {
            "awaiting_bus_find": datetime.now(),
            "awaiting_bus_search": True,
            "awaiting_bus_code": True,
            "awaiting_metro_search": datetime.now(),
            "other_data": "keep_me",
        }

        _clear_awaiting(context)

        assert "awaiting_bus_find" not in context.user_data
        assert "awaiting_bus_search" not in context.user_data
        assert "awaiting_bus_code" not in context.user_data
        assert "awaiting_metro_search" not in context.user_data
        assert context.user_data["other_data"] == "keep_me"

    def test_safe_when_no_flags(self):
        context = MagicMock()
        context.user_data = {}

        _clear_awaiting(context)
        # Should not raise


# ===================================================================
# Bus find callback tests (merged search/code)
# ===================================================================


class TestBusFindCallback:
    @pytest.mark.asyncio
    async def test_sets_awaiting_flag_as_datetime(self):
        from bot.handlers.bus import bus_find_callback

        query = AsyncMock()
        query.data = "bus:find"
        update = MagicMock()
        update.callback_query = query
        context = MagicMock()
        context.user_data = {}

        await bus_find_callback(update, context)

        assert "awaiting_bus_find" in context.user_data
        assert isinstance(context.user_data["awaiting_bus_find"], datetime)


class TestBusTextInputAutoDetect:
    """Test that the unified text handler auto-detects codes vs names."""

    @pytest.mark.asyncio
    async def test_code_detected_as_stop_code(self):
        from bot.handlers.bus import handle_bus_text_input

        update = MagicMock()
        update.message.text = "BCM2"
        context = MagicMock()
        context.user_data = {"awaiting_bus_find": datetime.now()}

        with patch("bot.handlers.bus._send_stop_realtime", new_callable=AsyncMock) as mock_send:
            result = await handle_bus_text_input(update, context)

        assert result is True
        mock_send.assert_called_once()
        # Should pass uppercase code
        assert mock_send.call_args[0][1] == "BCM2"

    @pytest.mark.asyncio
    async def test_name_detected_as_search(self):
        from bot.handlers.bus import handle_bus_text_input

        update = MagicMock()
        update.message.text = "Boavista"
        context = MagicMock()
        context.user_data = {"awaiting_bus_find": datetime.now()}

        with patch("bot.handlers.bus._search_and_show_stops", new_callable=AsyncMock) as mock_search:
            result = await handle_bus_text_input(update, context)

        assert result is True
        mock_search.assert_called_once()

    @pytest.mark.asyncio
    async def test_expired_flag_not_handled(self):
        from bot.handlers.bus import handle_bus_text_input

        update = MagicMock()
        update.message.text = "BCM2"
        context = MagicMock()
        # Set flag 10 minutes ago (expired)
        context.user_data = {
            "awaiting_bus_find": datetime.now() - timedelta(minutes=10)
        }

        result = await handle_bus_text_input(update, context)
        assert result is False
        # Flag should be cleared
        assert "awaiting_bus_find" not in context.user_data


class TestMetroTextInputExpiration:
    @pytest.mark.asyncio
    async def test_expired_metro_flag_not_handled(self):
        from bot.handlers.metro import handle_metro_text_input

        update = MagicMock()
        update.message.text = "Trindade"
        context = MagicMock()
        context.user_data = {
            "awaiting_metro_search": datetime.now() - timedelta(minutes=10)
        }

        result = await handle_metro_text_input(update, context)
        assert result is False
        assert "awaiting_metro_search" not in context.user_data

    @pytest.mark.asyncio
    async def test_active_metro_flag_handled(self):
        from bot.handlers.metro import handle_metro_text_input

        update = MagicMock()
        update.message.text = "Trindade"
        context = MagicMock()
        context.user_data = {
            "awaiting_metro_search": datetime.now()
        }

        with patch("bot.handlers.metro._search_and_show_stations", new_callable=AsyncMock):
            result = await handle_metro_text_input(update, context)

        assert result is True


# ===================================================================
# Favorites keyboard improvement
# ===================================================================


class TestEmptyFavoritesKeyboard:
    def test_shows_find_buttons_instead_of_separate_menus(self):
        kb = favorites_keyboard([])
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        # Should have find buttons, not just "go to bus/metro"
        assert any("find" in d or "search" in d for d in all_data)


# ===================================================================
# Bus menu with merged find
# ===================================================================


class TestBusMenuMerged:
    def test_has_find_not_separate_search_code(self):
        kb = bus_menu_keyboard()
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "bus:find" in all_data
        assert "bus:search" not in all_data
        assert "bus:code" not in all_data

    def test_has_three_buttons(self):
        kb = bus_menu_keyboard()
        # Should have: find, routes, back = 3 rows
        assert len(kb.inline_keyboard) == 3


# ===================================================================
# Metro search cancel button
# ===================================================================


class TestMetroSearchCallback:
    @pytest.mark.asyncio
    async def test_sets_timestamp_and_shows_cancel(self):
        from bot.handlers.metro import metro_search_callback

        query = AsyncMock()
        query.data = "metro:search"
        update = MagicMock()
        update.callback_query = query
        context = MagicMock()
        context.user_data = {}

        await metro_search_callback(update, context)

        assert isinstance(context.user_data["awaiting_metro_search"], datetime)
        # Check that edit_message_text was called with a reply_markup
        call_kwargs = query.edit_message_text.call_args[1]
        assert call_kwargs.get("reply_markup") is not None
