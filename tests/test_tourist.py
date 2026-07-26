"""Comprehensive tests for the Tourist Mode feature."""

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
# Tourist service tests
# ===================================================================

class TestTouristService:
    def test_get_categories_returns_all(self):
        from bot.services.tourist import get_categories
        cats = get_categories()
        assert len(cats) == 8
        assert "beaches" in cats
        assert "wine_cellars" in cats
        assert "historic_center" in cats
        assert "airport" in cats
        assert "stadium" in cats
        assert "universities" in cats
        assert "hospitals" in cats
        assert "tickets" in cats

    def test_get_category_valid(self):
        from bot.services.tourist import get_category
        cat = get_category("beaches")
        assert cat is not None
        assert cat["emoji"] == "🏖"
        assert len(cat["destinations"]) >= 2

    def test_get_category_invalid(self):
        from bot.services.tourist import get_category
        cat = get_category("nonexistent")
        assert cat is None

    def test_get_destination_valid(self):
        from bot.services.tourist import get_destination
        dest = get_destination("beaches", 0)
        assert dest is not None
        assert "name_pt" in dest
        assert "name_en" in dest
        assert "station" in dest
        assert "zone" in dest
        assert "tip_pt" in dest
        assert "tip_en" in dest

    def test_get_destination_invalid_index(self):
        from bot.services.tourist import get_destination
        dest = get_destination("beaches", 999)
        assert dest is None

    def test_get_destination_invalid_category(self):
        from bot.services.tourist import get_destination
        dest = get_destination("nonexistent", 0)
        assert dest is None

    def test_get_ticket_info_pt(self):
        from bot.services.tourist import get_ticket_info
        info = get_ticket_info("pt")
        assert "title" in info
        assert "sections" in info
        assert len(info["sections"]) >= 5
        assert "Andante" in info["title"]

    def test_get_ticket_info_en(self):
        from bot.services.tourist import get_ticket_info
        info = get_ticket_info("en")
        assert "Tickets" in info["title"] or "Andante" in info["title"]
        assert len(info["sections"]) >= 5

    def test_all_destinations_have_required_fields(self):
        """Verify every destination has all required fields."""
        from bot.services.tourist import TOURIST_POIS
        required_fields = {"name_pt", "name_en", "best_transport", "station",
                           "line", "zone", "tip_pt", "tip_en"}
        for cat_key, cat in TOURIST_POIS.items():
            for i, dest in enumerate(cat.get("destinations", [])):
                for field in required_fields:
                    assert field in dest, (
                        f"Missing '{field}' in {cat_key}[{i}]"
                    )


    def test_ticket_info_prices_come_from_fares(self):
        """No hardcoded prices: the guide renders bot.services.fares."""
        from bot.services import fares
        from bot.services.tourist import get_ticket_info
        for lang in ("pt", "en"):
            text = " ".join(s["text"] for s in get_ticket_info(lang)["sections"])
            assert "1\\.40" in text                      # current Z2 fare
            assert "1\\.25" not in text                  # old, wrong Z2 fare
            assert "1\\.65" not in text                  # old, wrong Z3 fare
            assert f"{fares.TOUR_PRICES[3]:.2f}".replace(".", "\\.") in text
            assert "15\\.00" not in text                 # old Tour 3 price

    def test_ticket_info_shows_real_zone_names(self):
        """Users must be able to cross-check against station signage."""
        from bot.services.tourist import get_ticket_info
        for lang in ("pt", "en"):
            text = " ".join(s["text"] for s in get_ticket_info(lang)["sections"])
            assert "PRT1" in text
            assert "VCD8" in text

    def test_ticket_info_shows_verification_date(self):
        from bot.services import fares
        from bot.services.tourist import get_ticket_info
        for lang in ("pt", "en"):
            text = " ".join(s["text"] for s in get_ticket_info(lang)["sections"])
            assert fares.LAST_VERIFIED.replace("-", "\\-") in text

    def test_destination_zones_are_computed_not_typed(self):
        from bot.services.tourist import TOURIST_POIS
        from bot.services.zones import calculate_zones
        beach = TOURIST_POIS["beaches"]["destinations"][0]
        # Matosinhos (MTS1) is 3 zones from central Porto, not 4.
        assert beach["zone"] == "Z3"
        assert calculate_zones("Trindade", "Matosinhos Sul")["title"] == "Z3"

    def test_gaia_cellars_are_z2(self):
        """Porto -> Gaia riverside is officially a Z2 trip."""
        from bot.services.tourist import TOURIST_POIS
        for dest in TOURIST_POIS["wine_cellars"]["destinations"]:
            assert dest["zone"] == "Z2"


# ===================================================================
# Tourist keyboard tests
# ===================================================================

class TestTouristKeyboards:
    def test_tourist_menu_keyboard_pt(self):
        from bot.keyboards.inline import tourist_menu_keyboard
        kb = tourist_menu_keyboard("pt")
        assert isinstance(kb, InlineKeyboardMarkup)
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        # Should have a button for each category + back
        assert "tourist:cat:beaches" in all_data
        assert "tourist:cat:airport" in all_data
        assert "tourist:cat:tickets" in all_data
        assert "menu:main" in all_data

    def test_tourist_menu_keyboard_en(self):
        from bot.keyboards.inline import tourist_menu_keyboard
        kb = tourist_menu_keyboard("en")
        all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
        # English titles
        assert any("Beaches" in t for t in all_texts)
        assert any("Airport" in t for t in all_texts)

    def test_tourist_category_keyboard(self):
        from bot.keyboards.inline import tourist_category_keyboard
        kb = tourist_category_keyboard("beaches", "pt")
        assert isinstance(kb, InlineKeyboardMarkup)
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "tourist:dest:beaches:0" in all_data
        assert "tourist:dest:beaches:1" in all_data
        assert "tourist:tickets" in all_data
        assert "tourist:menu" in all_data

    def test_tourist_destination_keyboard_with_station(self):
        from bot.keyboards.inline import tourist_destination_keyboard
        kb = tourist_destination_keyboard("beaches", 0, station="Matosinhos Sul", lang="pt")
        assert isinstance(kb, InlineKeyboardMarkup)
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "metro:station:Matosinhos Sul" in all_data
        assert "tourist:cat:beaches" in all_data

    def test_tourist_destination_keyboard_without_station(self):
        from bot.keyboards.inline import tourist_destination_keyboard
        kb = tourist_destination_keyboard("beaches", 0, station=None, lang="pt")
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        # No metro:station button when station is None
        assert not any(d and d.startswith("metro:station:") for d in all_data)

    def test_tourist_tickets_keyboard(self):
        from bot.keyboards.inline import tourist_tickets_keyboard
        kb = tourist_tickets_keyboard("en")
        assert isinstance(kb, InlineKeyboardMarkup)
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "tourist:menu" in all_data
        assert "menu:main" in all_data

    def test_main_menu_has_tourist_button(self):
        from bot.keyboards.inline import main_menu_keyboard
        kb = main_menu_keyboard("pt")
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "tourist:menu" in all_data


# ===================================================================
# Tourist handler tests
# ===================================================================

class TestTouristHandlers:
    @pytest.mark.asyncio
    async def test_tourist_command(self):
        """Test /tourist command shows the tourist menu."""
        from bot.handlers.tourist import tourist_command
        update = _make_update(lang="pt")
        context = _make_context()

        await tourist_command(update, context)

        update.message.reply_text.assert_called_once()
        call_kwargs = update.message.reply_text.call_args
        assert "Guia Turístico" in call_kwargs[0][0] or "tourist" in call_kwargs[0][0].lower()
        assert call_kwargs[1]["parse_mode"] == "MarkdownV2"

    @pytest.mark.asyncio
    async def test_tourist_command_en(self):
        """Test /tourist command in English."""
        from bot.handlers.tourist import tourist_command
        update = _make_update(lang="en")
        context = _make_context()

        await tourist_command(update, context)

        update.message.reply_text.assert_called_once()
        call_kwargs = update.message.reply_text.call_args
        assert "Tourist Guide" in call_kwargs[0][0]

    @pytest.mark.asyncio
    async def test_tourist_menu_callback(self):
        """Test tourist menu callback shows menu."""
        from bot.handlers.tourist import tourist_menu_callback
        update = _make_update(lang="pt")
        context = _make_context()

        await tourist_menu_callback(update, context)

        update.callback_query.answer.assert_called_once()
        update.callback_query.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_tourist_category_callback_beaches(self):
        """Test category callback shows beach destinations."""
        from bot.handlers.tourist import tourist_category_callback
        update = _make_update(lang="pt")
        update.callback_query.data = "tourist:cat:beaches"
        context = _make_context()

        await tourist_category_callback(update, context)

        update.callback_query.answer.assert_called_once()
        call_args = update.callback_query.edit_message_text.call_args
        text = call_args[0][0]
        assert "Praias" in text

    @pytest.mark.asyncio
    async def test_tourist_category_callback_en(self):
        """Test category callback in English."""
        from bot.handlers.tourist import tourist_category_callback
        update = _make_update(lang="en")
        update.callback_query.data = "tourist:cat:historic_center"
        context = _make_context()

        await tourist_category_callback(update, context)

        call_args = update.callback_query.edit_message_text.call_args
        text = call_args[0][0]
        assert "Historic Center" in text

    @pytest.mark.asyncio
    async def test_tourist_destination_callback(self):
        """Test destination callback shows detailed info."""
        from bot.handlers.tourist import tourist_destination_callback
        update = _make_update(lang="pt")
        update.callback_query.data = "tourist:dest:airport:0"
        context = _make_context()

        await tourist_destination_callback(update, context)

        call_args = update.callback_query.edit_message_text.call_args
        text = call_args[0][0]
        # Should contain airport info
        assert "Aeroporto" in text
        assert "Z4" in text

    @pytest.mark.asyncio
    async def test_tourist_destination_callback_en(self):
        """Test destination callback in English."""
        from bot.handlers.tourist import tourist_destination_callback
        update = _make_update(lang="en")
        update.callback_query.data = "tourist:dest:airport:0"
        context = _make_context()

        await tourist_destination_callback(update, context)

        call_args = update.callback_query.edit_message_text.call_args
        text = call_args[0][0]
        assert "Airport" in text

    @pytest.mark.asyncio
    async def test_tourist_tickets_callback(self):
        """Test tickets callback shows ticket info."""
        from bot.handlers.tourist import tourist_tickets_callback
        update = _make_update(lang="pt")
        context = _make_context()

        await tourist_tickets_callback(update, context)

        call_args = update.callback_query.edit_message_text.call_args
        text = call_args[0][0]
        assert "Andante" in text
        assert "Z2" in text

    @pytest.mark.asyncio
    async def test_tourist_tickets_callback_en(self):
        """Test tickets callback in English."""
        from bot.handlers.tourist import tourist_tickets_callback
        update = _make_update(lang="en")
        context = _make_context()

        await tourist_tickets_callback(update, context)

        call_args = update.callback_query.edit_message_text.call_args
        text = call_args[0][0]
        assert "Andante" in text
        assert "Zone" in text or "zone" in text

    @pytest.mark.asyncio
    async def test_tourist_destination_shows_walk_time(self):
        """Test that destination info includes walk time."""
        from bot.handlers.tourist import tourist_destination_callback
        update = _make_update(lang="pt")
        update.callback_query.data = "tourist:dest:beaches:0"
        context = _make_context()

        await tourist_destination_callback(update, context)

        call_args = update.callback_query.edit_message_text.call_args
        text = call_args[0][0]
        # Matosinhos beach has 5 min walk
        assert "5 min" in text

    @pytest.mark.asyncio
    async def test_tourist_destination_shows_bus_alt(self):
        """Test that destination info includes bus alternatives."""
        from bot.handlers.tourist import tourist_destination_callback
        update = _make_update(lang="en")
        update.callback_query.data = "tourist:dest:beaches:0"
        context = _make_context()

        await tourist_destination_callback(update, context)

        call_args = update.callback_query.edit_message_text.call_args
        text = call_args[0][0]
        assert "500" in text  # Bus 500 is an alternative


# ===================================================================
# Formatting / integration tests
# ===================================================================

class TestTouristFormatting:
    def test_format_destination_pt(self):
        """Test destination formatting in Portuguese."""
        from bot.handlers.tourist import _format_destination
        dest = {
            "name_pt": "Test Dest",
            "name_en": "Test Dest EN",
            "best_transport": "metro",
            "station": "Trindade",
            "line": "D",
            "line_name": "Linha Amarela",
            "bus_alt": "200, 201",
            "zone": "Z2",
            "walk_min": 5,
            "tip_pt": "Dica de teste",
            "tip_en": "Test tip",
        }
        text = _format_destination(dest, "⛪", "pt")
        assert "Test Dest" in text
        assert "Trindade" in text
        assert "Z2" in text
        assert "5 min" in text
        assert "Dica de teste" in text

    def test_format_destination_en(self):
        """Test destination formatting in English."""
        from bot.handlers.tourist import _format_destination
        dest = {
            "name_pt": "Test Dest",
            "name_en": "Test Dest EN",
            "best_transport": "bus",
            "station": "Foz",
            "line": "500",
            "line_name": "Bus 500",
            "bus_alt": "500, 203",
            "zone": "Z2",
            "walk_min": 0,
            "tip_pt": "Dica",
            "tip_en": "English tip here",
        }
        text = _format_destination(dest, "🏖", "en")
        assert "Test Dest EN" in text
        assert "English tip here" in text
        # walk_min=0 should show direct exit
        assert "Direct exit" in text

    def test_format_destination_metro_transport(self):
        """Test that metro transport label is shown correctly."""
        from bot.handlers.tourist import _format_destination
        dest = {
            "name_pt": "X", "name_en": "X",
            "best_transport": "metro",
            "station": "S", "line": "A", "line_name": "Azul",
            "bus_alt": "", "zone": "Z2",
            "walk_min": 1,
            "tip_pt": "", "tip_en": "",
        }
        text = _format_destination(dest, "📍", "en")
        assert "Metro" in text

    def test_i18n_tourist_keys_exist(self):
        """Verify all tourist i18n keys exist in both languages."""
        from bot.utils.i18n import TRANSLATIONS
        tourist_keys = [
            "tourist_title", "tourist_category_title", "tourist_dest_title",
            "tourist_best_transport", "tourist_best_transport_bus",
            "tourist_station", "tourist_line", "tourist_bus_alt",
            "tourist_zone", "tourist_walk", "tourist_walk_zero",
            "tourist_tip", "tourist_no_destinations",
            "kb_tourist", "kb_tourist_back_menu",
            "kb_tourist_show_map", "kb_tourist_tickets",
        ]
        for key in tourist_keys:
            assert key in TRANSLATIONS["pt"], f"Missing PT key: {key}"
            assert key in TRANSLATIONS["en"], f"Missing EN key: {key}"
