"""Tests for the Andante Zone Calculator feature."""

import pytest
from unittest.mock import AsyncMock, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_context(user_data=None, args=None):
    ctx = MagicMock()
    ctx.user_data = user_data if user_data is not None else {}
    ctx.args = args if args is not None else []
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
# Zone service tests
# ===================================================================

class TestZoneService:
    """Tests for bot.services.zones module."""

    def test_get_zone_for_known_station(self):
        """Test zone lookup for a known metro station."""
        from bot.services.zones import get_zone_for_station
        assert get_zone_for_station("Trindade") == "Z2"

    def test_get_zone_for_airport(self):
        """Test zone lookup for the airport station."""
        from bot.services.zones import get_zone_for_station
        assert get_zone_for_station("Aeroporto") == "Z4"

    def test_get_zone_for_gaia_station(self):
        """Test zone lookup for a Vila Nova de Gaia station."""
        from bot.services.zones import get_zone_for_station
        assert get_zone_for_station("Santo Ovídio") == "Z5"

    def test_get_zone_for_unknown_station(self):
        """Test zone lookup returns None for unknown station."""
        from bot.services.zones import get_zone_for_station
        result = get_zone_for_station("Estação Inexistente XYZ")
        assert result is None

    def test_get_zone_case_insensitive(self):
        """Test zone lookup is case-insensitive."""
        from bot.services.zones import get_zone_for_station
        assert get_zone_for_station("trindade") == "Z2"
        assert get_zone_for_station("AEROPORTO") == "Z4"

    def test_calculate_zones_same_zone(self):
        """Test calculation when both stations are in the same zone."""
        from bot.services.zones import calculate_zones
        result = calculate_zones("Trindade", "Bolhão")
        assert result is not None
        assert result["zones_needed"] == 1
        assert result["origin_zone"] == "Z2"
        assert result["dest_zone"] == "Z2"
        assert result["price"] == 1.40

    def test_calculate_zones_cross_city(self):
        """Test calculation across multiple zones (Porto to Gaia)."""
        from bot.services.zones import calculate_zones
        result = calculate_zones("Trindade", "Santo Ovídio")
        assert result is not None
        assert result["zones_needed"] == 4  # Z2 -> Z3 -> Z4 -> Z5
        assert result["origin_zone"] == "Z2"
        assert result["dest_zone"] == "Z5"
        assert result["price"] == 3.05

    def test_calculate_zones_airport(self):
        """Test calculation to the airport."""
        from bot.services.zones import calculate_zones
        result = calculate_zones("Trindade", "Aeroporto")
        assert result is not None
        assert result["zones_needed"] == 3  # Z2 -> Z3 -> Z4
        assert result["price"] == 2.50

    def test_calculate_zones_not_found(self):
        """Test calculation returns None for unknown station."""
        from bot.services.zones import calculate_zones
        result = calculate_zones("Trindade", "Nonexistent Station XYZ")
        assert result is None

    def test_calculate_zones_symmetric(self):
        """Test that zone calculation is symmetric (A->B == B->A)."""
        from bot.services.zones import calculate_zones
        result_ab = calculate_zones("Trindade", "Aeroporto")
        result_ba = calculate_zones("Aeroporto", "Trindade")
        assert result_ab is not None
        assert result_ba is not None
        assert result_ab["zones_needed"] == result_ba["zones_needed"]
        assert result_ab["price"] == result_ba["price"]

    def test_get_price_single_zone(self):
        """Test single zone price."""
        from bot.services.zones import get_price
        assert get_price(1) == 1.40

    def test_get_price_multi_zone(self):
        """Test multi-zone prices."""
        from bot.services.zones import get_price
        assert get_price(2) == 1.95
        assert get_price(3) == 2.50
        assert get_price(5) == 3.60

    def test_get_price_minimum(self):
        """Test that price never goes below 1 zone."""
        from bot.services.zones import get_price
        assert get_price(0) == 1.40
        assert get_price(-1) == 1.40

    def test_get_day_pass_price(self):
        """Test day pass pricing."""
        from bot.services.zones import get_day_pass_price
        assert get_day_pass_price(1) == 4.15
        assert get_day_pass_price(2) == 5.80
        assert get_day_pass_price(3) == 7.50

    def test_get_day_pass_price_all_zones(self):
        """Test that large zone counts cap at the all-zones price."""
        from bot.services.zones import get_day_pass_price
        assert get_day_pass_price(8) == 15.30
        assert get_day_pass_price(11) == 15.30

    def test_get_stations_in_zone(self):
        """Test getting all stations in a specific zone."""
        from bot.services.zones import get_stations_in_zone
        z2_stations = get_stations_in_zone("Z2")
        assert len(z2_stations) > 0
        assert "Trindade" in z2_stations
        assert "Bolhão" in z2_stations
        assert "Aliados" in z2_stations

    def test_get_stations_in_zone_empty(self):
        """Test that an unknown zone returns empty list."""
        from bot.services.zones import get_stations_in_zone
        assert get_stations_in_zone("Z99") == []

    def test_get_all_zones(self):
        """Test getting all zones with stations."""
        from bot.services.zones import get_all_zones
        zones = get_all_zones()
        assert "Z2" in zones
        assert "Z4" in zones
        assert "Z10" in zones
        # Zones should be in order
        assert zones.index("Z2") < zones.index("Z4")
        assert zones.index("Z4") < zones.index("Z10")

    def test_search_station(self):
        """Test station search across transport modes."""
        from bot.services.zones import search_station
        results = search_station("Trindade")
        assert len(results) > 0
        assert results[0][0] == "Trindade"
        assert results[0][1] == "Z2"

    def test_search_station_partial(self):
        """Test partial station name search."""
        from bot.services.zones import search_station
        results = search_station("Aero")
        assert len(results) > 0
        assert any("Aeroporto" in r[0] for r in results)

    def test_search_station_empty(self):
        """Test empty search returns empty."""
        from bot.services.zones import search_station
        assert search_station("") == []

    def test_zone_prices_dict_complete(self):
        """Test that ZONE_PRICES covers all expected zone counts."""
        from bot.services.zones import ZONE_PRICES
        for i in range(1, 12):
            assert i in ZONE_PRICES

    def test_calculate_zones_result_has_all_fields(self):
        """Test that calculation result has all expected fields."""
        from bot.services.zones import calculate_zones
        result = calculate_zones("Trindade", "Aeroporto")
        assert result is not None
        assert "origin_zone" in result
        assert "dest_zone" in result
        assert "zones_needed" in result
        assert "price" in result
        assert "day_pass_price" in result
        assert "origin_name" in result
        assert "dest_name" in result

    def test_calculate_zones_povoa(self):
        """Test long-distance calculation to Póvoa de Varzim."""
        from bot.services.zones import calculate_zones
        result = calculate_zones("Trindade", "Póvoa de Varzim")
        assert result is not None
        assert result["zones_needed"] == 9  # Z2 -> Z10
        assert result["dest_zone"] == "Z10"

    def test_cp_station_zones(self):
        """Test CP train station zone lookup."""
        from bot.services.zones import get_zone_for_station
        assert get_zone_for_station("Porto-São Bento") == "Z2"
        assert get_zone_for_station("Porto-Campanhã") == "Z3"

    def test_metrobus_station_zones(self):
        """Test MetroBus stop zone lookup."""
        from bot.services.zones import get_zone_for_station
        assert get_zone_for_station("Casa da Música (MetroBus)") == "Z2"
        assert get_zone_for_station("Matosinhos (MetroBus)") == "Z4"


# ===================================================================
# Zone keyboard tests
# ===================================================================

class TestZoneKeyboards:
    """Tests for zone-related keyboards."""

    def test_zones_menu_keyboard(self):
        from bot.keyboards.inline import zones_menu_keyboard
        kb = zones_menu_keyboard("pt")
        assert kb is not None
        all_buttons = [btn for row in kb.inline_keyboard for btn in row]
        callbacks = [btn.callback_data for btn in all_buttons]
        assert "zones:calculate" in callbacks
        assert "zones:map" in callbacks
        assert "menu:main" in callbacks

    def test_zones_result_keyboard(self):
        from bot.keyboards.inline import zones_result_keyboard
        kb = zones_result_keyboard("Trindade", "Aeroporto", "pt")
        assert kb is not None
        all_buttons = [btn for row in kb.inline_keyboard for btn in row]
        callbacks = [btn.callback_data for btn in all_buttons]
        assert "zones:calculate" in callbacks
        assert "zones:map" in callbacks

    def test_zones_map_keyboard(self):
        from bot.keyboards.inline import zones_map_keyboard
        kb = zones_map_keyboard("pt")
        assert kb is not None
        all_buttons = [btn for row in kb.inline_keyboard for btn in row]
        zone_buttons = [btn for btn in all_buttons if btn.callback_data and btn.callback_data.startswith("zones:zone:")]
        assert len(zone_buttons) > 0

    def test_zone_detail_keyboard(self):
        from bot.keyboards.inline import zone_detail_keyboard
        kb = zone_detail_keyboard("Z2", "pt")
        assert kb is not None


# ===================================================================
# Zone handler tests
# ===================================================================

class TestZoneHandlers:
    """Tests for zone handler functions."""

    @pytest.mark.asyncio
    async def test_zones_command_no_args(self):
        """Test /zonas command with no arguments shows menu."""
        from bot.handlers.zones import zones_command
        update = _make_update()
        context = _make_context(args=[])
        await zones_command(update, context)
        update.message.reply_text.assert_called_once()
        call_args = update.message.reply_text.call_args[0][0]
        assert "Andante" in call_args or "Zonas" in call_args

    @pytest.mark.asyncio
    async def test_zones_command_quick(self):
        """Test /zonas Trindade Aeroporto quick calculation."""
        from bot.handlers.zones import zones_command
        update = _make_update()
        context = _make_context(args=["Trindade", "Aeroporto"])
        await zones_command(update, context)
        update.message.reply_text.assert_called_once()
        call_args = update.message.reply_text.call_args[0][0]
        assert "Z" in call_args

    @pytest.mark.asyncio
    async def test_zones_menu_callback(self):
        """Test zone menu callback."""
        from bot.handlers.zones import zones_menu_callback
        update = _make_update()
        context = _make_context()
        await zones_menu_callback(update, context)
        update.callback_query.answer.assert_called_once()
        update.callback_query.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_zones_calculate_callback(self):
        """Test starting zone calculation sets step to origin."""
        from bot.handlers.zones import zones_calculate_callback
        update = _make_update()
        context = _make_context()
        await zones_calculate_callback(update, context)
        assert context.user_data.get("zones_step") == "origin"

    @pytest.mark.asyncio
    async def test_zones_map_callback(self):
        """Test zone map display."""
        from bot.handlers.zones import zones_map_callback
        update = _make_update()
        context = _make_context()
        await zones_map_callback(update, context)
        update.callback_query.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_zones_zone_callback(self):
        """Test zone detail display shows stations."""
        from bot.handlers.zones import zones_zone_callback
        update = _make_update()
        update.callback_query.data = "zones:zone:Z2"
        context = _make_context()
        await zones_zone_callback(update, context)
        update.callback_query.edit_message_text.assert_called_once()
        call_args = update.callback_query.edit_message_text.call_args[0][0]
        # Z2 has many stations; check for one that appears early alphabetically
        assert "Aliados" in call_args

    @pytest.mark.asyncio
    async def test_handle_zones_text_origin(self):
        """Test handling text input for origin station."""
        from bot.handlers.zones import handle_zones_text_input
        update = _make_update(text="Trindade")
        context = _make_context(user_data={"zones_step": "origin"})
        result = await handle_zones_text_input(update, context)
        assert result is True
        assert context.user_data.get("zones_origin") == "Trindade"
        assert context.user_data.get("zones_step") == "dest"

    @pytest.mark.asyncio
    async def test_handle_zones_text_dest(self):
        """Test handling text input for destination station."""
        from bot.handlers.zones import handle_zones_text_input
        update = _make_update(text="Aeroporto")
        context = _make_context(user_data={
            "zones_step": "dest",
            "zones_origin": "Trindade",
        })
        result = await handle_zones_text_input(update, context)
        assert result is True
        update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_zones_text_not_awaiting(self):
        """Test that text handler returns False when not in zone flow."""
        from bot.handlers.zones import handle_zones_text_input
        update = _make_update(text="Trindade")
        context = _make_context()
        result = await handle_zones_text_input(update, context)
        assert result is False

    @pytest.mark.asyncio
    async def test_handle_zones_text_unknown_station(self):
        """Test handling unknown station name during zone flow."""
        from bot.handlers.zones import handle_zones_text_input
        update = _make_update(text="NonExistentStationXYZ123")
        context = _make_context(user_data={"zones_step": "origin"})
        result = await handle_zones_text_input(update, context)
        assert result is True
        update.message.reply_text.assert_called_once()
        call_args = update.message.reply_text.call_args[0][0]
        assert "NonExistentStationXYZ123" in call_args


# ===================================================================
# i18n tests
# ===================================================================

class TestZoneI18n:
    """Tests for zone-related translations."""

    def test_zone_translations_exist_pt(self):
        from bot.utils.i18n import t
        assert "Andante" in t("zones_title", "pt") or "Zonas" in t("zones_title", "pt")
        assert t("zones_ask_origin", "pt") != "zones_ask_origin"
        assert t("zones_result", "pt") != "zones_result"

    def test_zone_translations_exist_en(self):
        from bot.utils.i18n import t
        assert "Andante" in t("zones_title", "en") or "Zone" in t("zones_title", "en")
        assert t("zones_ask_origin", "en") != "zones_ask_origin"
        assert t("zones_result", "en") != "zones_result"

    def test_zone_keyboard_labels_exist(self):
        from bot.utils.i18n import t
        for lang in ("pt", "en"):
            assert t("kb_zones", lang) != "kb_zones"
            assert t("kb_zones_calculate", lang) != "kb_zones_calculate"
            assert t("kb_zones_map", lang) != "kb_zones_map"
            assert t("kb_zones_new_calc", lang) != "kb_zones_new_calc"
