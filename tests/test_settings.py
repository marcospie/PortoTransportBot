"""Tests for user settings feature."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.database import DEFAULT_SETTINGS


class TestDefaultSettings:
    """Verify default settings values are sensible."""

    def test_default_metro_radius(self):
        assert DEFAULT_SETTINGS["metro_radius_m"] == 500

    def test_default_bus_radius(self):
        assert DEFAULT_SETTINGS["bus_radius_m"] == 200

    def test_default_max_results(self):
        assert DEFAULT_SETTINGS["max_results"] == 5

    def test_default_language(self):
        assert DEFAULT_SETTINGS["language"] == "auto"


class TestSettingsJsonFallback:
    """Test JSON fallback for settings storage."""

    def test_load_returns_defaults_when_no_file(self):
        from bot.database import _json_load_settings
        # Use a user_id that won't have a file
        settings = _json_load_settings(999999999)
        assert settings == DEFAULT_SETTINGS

    @pytest.mark.asyncio
    async def test_get_user_settings_returns_defaults(self):
        from bot.database import get_user_settings
        settings = await get_user_settings(999999999)
        assert settings["metro_radius_m"] == 500
        assert settings["bus_radius_m"] == 200
        assert settings["max_results"] == 5

    @pytest.mark.asyncio
    async def test_update_and_get_setting(self):
        from bot.database import get_user_settings, update_user_setting
        import bot.database as db_mod

        # Ensure we're using JSON fallback
        original = db_mod._use_db
        db_mod._use_db = False
        test_user = 888888888
        try:
            await update_user_setting(test_user, "metro_radius_m", 1000)
            settings = await get_user_settings(test_user)
            assert settings["metro_radius_m"] == 1000

            # Clean up
            import os
            path = db_mod._json_settings_path(test_user)
            if path.exists():
                os.remove(path)
        finally:
            db_mod._use_db = original

    @pytest.mark.asyncio
    async def test_update_invalid_key_raises(self):
        from bot.database import update_user_setting
        with pytest.raises(ValueError, match="Unknown setting"):
            await update_user_setting(999, "invalid_key", "value")


class TestSettingsHandler:
    """Test settings command and callbacks."""

    @pytest.mark.asyncio
    async def test_settings_command_shows_menu(self):
        from bot.handlers.settings import settings_command

        update = MagicMock()
        update.effective_user.id = 123
        update.effective_user.language_code = "pt"
        update.message.reply_text = AsyncMock()
        context = MagicMock()

        with patch("bot.handlers.settings.get_user_settings",
                   return_value=dict(DEFAULT_SETTINGS)):
            await settings_command(update, context)

        update.message.reply_text.assert_called_once()
        call_args = update.message.reply_text.call_args
        text = call_args[0][0] if call_args[0] else call_args[1]["text"]
        assert "Configurações" in text or "Settings" in text

    @pytest.mark.asyncio
    async def test_settings_menu_callback(self):
        from bot.handlers.settings import settings_menu_callback

        update = MagicMock()
        query = AsyncMock()
        update.callback_query = query
        update.effective_user.id = 123
        update.effective_user.language_code = "pt"
        context = MagicMock()

        with patch("bot.handlers.settings.get_user_settings",
                   return_value=dict(DEFAULT_SETTINGS)):
            await settings_menu_callback(update, context)

        query.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_settings_set_callback_saves(self):
        from bot.handlers.settings import settings_set_callback

        update = MagicMock()
        query = AsyncMock()
        query.data = "settings:set:metro_radius_m:1000"
        update.callback_query = query
        update.effective_user.id = 123
        update.effective_user.language_code = "pt"
        context = MagicMock()

        with patch("bot.handlers.settings.update_user_setting") as mock_update, \
             patch("bot.handlers.settings.get_user_settings",
                   return_value={**DEFAULT_SETTINGS, "metro_radius_m": 1000}):
            await settings_set_callback(update, context)
            mock_update.assert_called_once_with(123, "metro_radius_m", 1000)

        query.answer.assert_called_once()

    @pytest.mark.asyncio
    async def test_settings_reset_callback(self):
        from bot.handlers.settings import settings_reset_callback

        update = MagicMock()
        query = AsyncMock()
        update.callback_query = query
        update.effective_user.id = 123
        update.effective_user.language_code = "pt"
        context = MagicMock()

        with patch("bot.handlers.settings.update_user_setting") as mock_update, \
             patch("bot.handlers.settings.get_user_settings",
                   return_value=dict(DEFAULT_SETTINGS)):
            await settings_reset_callback(update, context)
            # Should have called update for each default setting
            assert mock_update.call_count == len(DEFAULT_SETTINGS)


class TestSettingsKeyboards:
    """Test the settings keyboard builders."""

    def test_radius_options_keyboard(self):
        from bot.handlers.settings import _radius_options_keyboard
        kb = _radius_options_keyboard("metro_radius_m", [200, 500, 1000], 500, "pt")
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "settings:set:metro_radius_m:200" in all_data
        assert "settings:set:metro_radius_m:500" in all_data
        assert "settings:set:metro_radius_m:1000" in all_data
        # Current value should be marked
        all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert any("• 500m •" in t for t in all_texts)

    def test_language_keyboard(self):
        from bot.handlers.settings import _language_keyboard
        kb = _language_keyboard("auto", "pt")
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row
                    if btn.callback_data]
        assert "settings:set:language:auto" in all_data
        assert "settings:set:language:pt" in all_data
        assert "settings:set:language:en" in all_data

    def test_settings_menu_has_all_options(self):
        from bot.handlers.settings import _settings_menu_keyboard
        kb = _settings_menu_keyboard(DEFAULT_SETTINGS, "pt")
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "settings:metro_radius" in all_data
        assert "settings:bus_radius" in all_data
        assert "settings:max_results" in all_data
        assert "settings:language" in all_data
        assert "settings:reset" in all_data
        assert "menu:main" in all_data


class TestMainMenuHasSettings:
    """Verify settings button is in main menu."""

    def test_main_menu_has_settings_button(self):
        from bot.keyboards.inline import main_menu_keyboard
        kb = main_menu_keyboard()
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row
                    if btn.callback_data]
        assert "menu:settings" in all_data
