"""Tests for user settings feature."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.database import DEFAULT_SETTINGS
from bot.utils.i18n import TRANSLATIONS, clear_lang_cache, get_lang


@pytest.fixture(autouse=True)
def _clean_lang_cache():
    clear_lang_cache()
    yield
    clear_lang_cache()


def _settings_with_notifications(**overrides):
    base = dict(DEFAULT_SETTINGS)
    base.setdefault("notifications", "off")
    base.update(overrides)
    return base


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


class TestSettingsHonoursStoredLanguage:
    """The /settings screen itself must render in the chosen language."""

    @pytest.mark.asyncio
    async def test_settings_command_uses_stored_english(self):
        from bot.handlers.settings import settings_command

        update = MagicMock()
        update.effective_user.id = 5551
        update.effective_user.language_code = "pt"
        update.message.reply_text = AsyncMock()

        with patch("bot.handlers.settings.get_user_settings",
                   return_value={**DEFAULT_SETTINGS, "language": "en"}), \
             patch("bot.database.get_user_settings",
                   new=AsyncMock(return_value={**DEFAULT_SETTINGS, "language": "en"})):
            await settings_command(update, MagicMock())

        text = update.message.reply_text.call_args[0][0]
        assert text == TRANSLATIONS["en"]["settings_title"]

    @pytest.mark.asyncio
    async def test_changing_language_writes_through_to_i18n_cache(self):
        """Selecting English must make every later get_lang() return 'en'."""
        from bot.handlers.settings import settings_set_callback

        update = MagicMock()
        query = AsyncMock()
        query.data = "settings:set:language:en"
        update.callback_query = query
        update.effective_user.id = 5552
        update.effective_user.language_code = "pt"

        assert get_lang(update) == "pt"

        with patch("bot.handlers.settings.update_user_setting") as mock_update, \
             patch("bot.handlers.settings.get_user_settings",
                   return_value={**DEFAULT_SETTINGS, "language": "en"}):
            await settings_set_callback(update, MagicMock())
            mock_update.assert_awaited_once_with(5552, "language", "en")

        assert get_lang(update) == "en"
        # ...and the redraw is already in English
        assert query.edit_message_text.call_args[0][0] == \
            TRANSLATIONS["en"]["settings_title"]

    @pytest.mark.asyncio
    async def test_reset_restores_auto_language(self):
        from bot.handlers.settings import settings_reset_callback
        from bot.utils.i18n import set_lang_preference

        update = MagicMock()
        update.callback_query = AsyncMock()
        update.effective_user.id = 5553
        update.effective_user.language_code = "pt"

        set_lang_preference(5553, "en")
        assert get_lang(update) == "en"

        with patch("bot.handlers.settings.update_user_setting"), \
             patch("bot.handlers.settings.get_user_settings",
                   return_value=dict(DEFAULT_SETTINGS)):
            await settings_reset_callback(update, MagicMock())

        assert get_lang(update) == "pt"


class TestNotificationsToggle:
    """Opt-in proactive notifications toggle."""

    def test_menu_shows_notifications_row_when_supported(self):
        from bot.handlers.settings import _settings_menu_keyboard
        kb = _settings_menu_keyboard(_settings_with_notifications(), "pt")
        all_data = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert "settings:set:notifications:toggle" in all_data

    def test_notifications_row_uses_registered_callback_pattern(self):
        """It must match main.py's ^settings:set:.+$ handler."""
        import re
        from bot.handlers.settings import _settings_menu_keyboard
        kb = _settings_menu_keyboard(_settings_with_notifications(), "pt")
        data = [b.callback_data for row in kb.inline_keyboard for b in row
                if b.callback_data and "notifications" in b.callback_data]
        assert data
        for item in data:
            assert re.match(r"^settings:set:.+$", item)

    def test_menu_hides_notifications_when_unsupported(self):
        from bot.handlers.settings import _settings_menu_keyboard
        bare = {k: v for k, v in DEFAULT_SETTINGS.items() if k != "notifications"}
        with patch.dict("bot.handlers.settings.DEFAULT_SETTINGS", bare, clear=True):
            kb = _settings_menu_keyboard(bare, "pt")
        all_data = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert not any("notifications" in (d or "") for d in all_data)

    def test_default_is_off(self):
        from bot.handlers.settings import _notifications_value
        assert _notifications_value({}) == "off"
        assert _notifications_value(_settings_with_notifications()) == "off"

    @pytest.mark.parametrize("raw,expected", [
        ("on", "on"), ("off", "off"), ("ON", "on"), (True, "on"), (False, "off"),
        ("true", "on"), ("nonsense", "off"), (1, "on"), (0, "off"),
    ])
    def test_notifications_value_normalisation(self, raw, expected):
        from bot.handlers.settings import _notifications_value
        assert _notifications_value({"notifications": raw}) == expected

    def test_label_is_localised(self):
        from bot.handlers.settings import _notifications_label
        assert _notifications_label("on", "pt") == TRANSLATIONS["pt"]["settings_notifications_on"]
        assert _notifications_label("off", "en") == TRANSLATIONS["en"]["settings_notifications_off"]
        assert _notifications_label("on", "pt") != _notifications_label("on", "en")

    @pytest.mark.asyncio
    async def test_toggle_turns_notifications_on(self):
        from bot.handlers.settings import settings_set_callback

        update = MagicMock()
        query = AsyncMock()
        query.data = "settings:set:notifications:toggle"
        update.callback_query = query
        update.effective_user.id = 5554
        update.effective_user.language_code = "pt"

        with patch("bot.handlers.settings.update_user_setting") as mock_update, \
             patch("bot.handlers.settings.get_user_settings",
                   return_value=_settings_with_notifications(notifications="off")):
            await settings_set_callback(update, MagicMock())
            mock_update.assert_awaited_once_with(5554, "notifications", "on")

    @pytest.mark.asyncio
    async def test_toggle_turns_notifications_off_again(self):
        from bot.handlers.settings import settings_set_callback

        update = MagicMock()
        query = AsyncMock()
        query.data = "settings:set:notifications:toggle"
        update.callback_query = query
        update.effective_user.id = 5555
        update.effective_user.language_code = "pt"

        with patch("bot.handlers.settings.update_user_setting") as mock_update, \
             patch("bot.handlers.settings.get_user_settings",
                   return_value=_settings_with_notifications(notifications="on")):
            await settings_set_callback(update, MagicMock())
            mock_update.assert_awaited_once_with(5555, "notifications", "off")

    @pytest.mark.asyncio
    async def test_unsupported_key_does_not_raise(self):
        """If the storage layer rejects the key, the user still sees the menu."""
        from bot.handlers.settings import settings_set_callback

        update = MagicMock()
        query = AsyncMock()
        query.data = "settings:set:notifications:on"
        update.callback_query = query
        update.effective_user.id = 5556
        update.effective_user.language_code = "pt"

        with patch("bot.handlers.settings.update_user_setting",
                   new=AsyncMock(side_effect=ValueError("Unknown setting"))), \
             patch("bot.handlers.settings.get_user_settings",
                   return_value=dict(DEFAULT_SETTINGS)):
            await settings_set_callback(update, MagicMock())

        query.edit_message_text.assert_called_once()

    def test_notifications_options_keyboard(self):
        from bot.handlers.settings import _notifications_keyboard
        kb = _notifications_keyboard("off", "pt")
        all_data = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert "settings:set:notifications:on" in all_data
        assert "settings:set:notifications:off" in all_data


class TestSettingsUsesSafeEdit:
    """Tapping a toggle twice must not surface 'Message is not modified'."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("handler_name,data", [
        ("settings_menu_callback", "menu:settings"),
        ("settings_option_callback", "settings:language"),
        ("settings_set_callback", "settings:set:max_results:5"),
        ("settings_reset_callback", "settings:reset"),
    ])
    async def test_not_modified_is_swallowed(self, handler_name, data):
        import bot.handlers.settings as mod

        handler = getattr(mod, handler_name)
        update = MagicMock()
        query = AsyncMock()
        query.data = data
        query.edit_message_text = AsyncMock(
            side_effect=Exception("Message is not modified: ...")
        )
        update.callback_query = query
        update.effective_user.id = 5557
        update.effective_user.language_code = "pt"

        with patch("bot.handlers.settings.update_user_setting"), \
             patch("bot.handlers.settings.get_user_settings",
                   return_value=dict(DEFAULT_SETTINGS)):
            await handler(update, MagicMock())  # must not raise

    @pytest.mark.asyncio
    async def test_real_edit_error_still_propagates(self):
        from bot.handlers.settings import settings_menu_callback

        update = MagicMock()
        query = AsyncMock()
        query.edit_message_text = AsyncMock(side_effect=Exception("Chat not found"))
        update.callback_query = query
        update.effective_user.id = 5558
        update.effective_user.language_code = "pt"

        with patch("bot.handlers.settings.get_user_settings",
                   return_value=dict(DEFAULT_SETTINGS)):
            with pytest.raises(Exception, match="Chat not found"):
                await settings_menu_callback(update, MagicMock())


class TestMainMenuHasSettings:
    """Verify settings button is in main menu."""

    def test_main_menu_has_settings_button(self):
        from bot.keyboards.inline import main_menu_keyboard
        kb = main_menu_keyboard()
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row
                    if btn.callback_data]
        assert "menu:settings" in all_data
