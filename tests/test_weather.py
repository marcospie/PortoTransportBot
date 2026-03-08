"""Tests for the Weather (Meteorologia) feature."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from telegram import InlineKeyboardMarkup


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_context(user_data=None):
    ctx = MagicMock()
    ctx.user_data = user_data if user_data is not None else {}
    ctx.args = []
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()
    return ctx


def _make_update(user_id=123, text="", lang="pt", chat_id=456):
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
    query.data = ""
    update.callback_query = query

    return update


# ===================================================================
# Weather service tests
# ===================================================================

class TestWeatherService:
    def test_get_weather_info_returns_dict_with_expected_keys(self):
        from bot.services.weather import get_weather_info
        info = get_weather_info()
        assert isinstance(info, dict)
        expected_keys = {
            "month", "temp_min", "temp_max", "rain_prob",
            "description_pt", "description_en",
            "sunrise", "sunset", "emoji",
        }
        assert expected_keys.issubset(info.keys())

    def test_get_transport_tip_returns_string_pt(self):
        from bot.services.weather import get_transport_tip
        tip = get_transport_tip("pt")
        assert isinstance(tip, str)
        assert len(tip) > 0

    def test_get_transport_tip_returns_string_en(self):
        from bot.services.weather import get_transport_tip
        tip = get_transport_tip("en")
        assert isinstance(tip, str)
        assert len(tip) > 0

    def test_get_weather_emoji_returns_emoji(self):
        from bot.services.weather import get_weather_emoji
        for month in range(1, 13):
            emoji = get_weather_emoji(month)
            assert isinstance(emoji, str)
            assert len(emoji) > 0

    def test_climate_data_all_months(self):
        from bot.services.weather import PORTO_CLIMATE
        for month in range(1, 13):
            assert month in PORTO_CLIMATE, f"Missing month {month}"
            data = PORTO_CLIMATE[month]
            assert "temp_min" in data
            assert "temp_max" in data
            assert "rain_prob" in data
            assert "description_pt" in data
            assert "description_en" in data
            assert "sunrise" in data
            assert "sunset" in data

    def test_winter_rain_probability_high(self):
        from bot.services.weather import PORTO_CLIMATE
        winter_months = [12, 1, 2]
        for month in winter_months:
            assert PORTO_CLIMATE[month]["rain_prob"] >= 60, (
                f"Month {month} should have high rain probability"
            )

    def test_summer_rain_probability_low(self):
        from bot.services.weather import PORTO_CLIMATE
        summer_months = [6, 7, 8]
        for month in summer_months:
            assert PORTO_CLIMATE[month]["rain_prob"] <= 20, (
                f"Month {month} should have low rain probability"
            )


# ===================================================================
# Weather keyboard tests
# ===================================================================

class TestWeatherKeyboards:
    def test_weather_keyboard_has_refresh_and_back(self):
        from bot.keyboards.inline import weather_keyboard
        kb = weather_keyboard("pt")
        assert isinstance(kb, InlineKeyboardMarkup)
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "menu:weather" in all_data
        assert "menu:main" in all_data

    def test_weather_keyboard_en(self):
        from bot.keyboards.inline import weather_keyboard
        kb = weather_keyboard("en")
        assert isinstance(kb, InlineKeyboardMarkup)
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "menu:weather" in all_data
        assert "menu:main" in all_data

    def test_main_menu_has_weather_button(self):
        from bot.keyboards.inline import main_menu_keyboard
        kb = main_menu_keyboard("pt")
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "menu:weather" in all_data


# ===================================================================
# Weather handler tests
# ===================================================================

class TestWeatherHandlers:
    @pytest.mark.asyncio
    async def test_weather_command(self):
        """Test /meteo command shows the weather overview."""
        from bot.handlers.weather import weather_command
        update = _make_update(lang="pt")
        context = _make_context()

        await weather_command(update, context)

        update.message.reply_text.assert_called_once()
        call_kwargs = update.message.reply_text.call_args
        assert "Meteorologia" in call_kwargs[0][0]
        assert call_kwargs[1]["parse_mode"] == "MarkdownV2"

    @pytest.mark.asyncio
    async def test_weather_command_en(self):
        """Test /meteo command in English."""
        from bot.handlers.weather import weather_command
        update = _make_update(lang="en")
        context = _make_context()

        await weather_command(update, context)

        update.message.reply_text.assert_called_once()
        call_kwargs = update.message.reply_text.call_args
        assert "Porto Weather" in call_kwargs[0][0]

    @pytest.mark.asyncio
    async def test_weather_menu_callback(self):
        """Test weather menu callback shows weather."""
        from bot.handlers.weather import weather_menu_callback
        update = _make_update(lang="pt")
        context = _make_context()

        await weather_menu_callback(update, context)

        update.callback_query.answer.assert_called_once()
        update.callback_query.edit_message_text.assert_called_once()


# ===================================================================
# i18n tests
# ===================================================================

class TestWeatherI18n:
    def test_i18n_weather_keys_exist(self):
        """Verify all weather i18n keys exist in both languages."""
        from bot.utils.i18n import TRANSLATIONS
        weather_keys = [
            "weather_title", "weather_temp", "weather_rain",
            "weather_sunrise", "weather_sunset", "weather_tip",
            "weather_tip_rain", "weather_tip_nice",
            "weather_tip_hot", "weather_tip_cold",
            "weather_disclaimer", "kb_weather",
        ]
        for key in weather_keys:
            assert key in TRANSLATIONS["pt"], f"Missing PT key: {key}"
            assert key in TRANSLATIONS["en"], f"Missing EN key: {key}"
