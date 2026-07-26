"""Tests for the Accessibility (Acessibilidade) feature."""

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
# Accessibility service tests
# ===================================================================

class TestAccessibilityService:
    """Tests for bot.services.accessibility module."""

    def test_get_station_accessibility_known(self):
        """Test accessibility lookup for a known station."""
        from bot.services.accessibility import get_station_accessibility
        result = get_station_accessibility("Trindade")
        assert result is not None
        assert result["name"] == "Trindade"
        assert result["elevator"] is True
        assert result["elevator_status"] == "operational"
        assert result["ramp"] is True
        assert result["tactile"] is True
        assert result["audio"] is True
        assert result["accessible_machines"] is True
        assert result["wheelchair_spaces"] is True

    def test_get_station_accessibility_case_insensitive(self):
        """Test that lookup is case-insensitive."""
        from bot.services.accessibility import get_station_accessibility
        result = get_station_accessibility("trindade")
        assert result is not None
        assert result["name"] == "Trindade"

    def test_get_station_accessibility_unknown(self):
        """Test that unknown station returns None."""
        from bot.services.accessibility import get_station_accessibility
        result = get_station_accessibility("NonExistentStationXYZ123")
        assert result is None

    def test_no_invented_maintenance_status(self):
        """No station may claim an unsourced 'lift under maintenance' status."""
        from bot.services.accessibility import ACCESSIBILITY, get_station_accessibility
        # Bolhão used to be hardcoded as "under maintenance" with no source.
        result = get_station_accessibility("Bolhão")
        assert result is not None
        assert result["elevator_status"] != "maintenance"
        assert all(d["elevator_status"] != "maintenance"
                   for d in ACCESSIBILITY.values())

    def test_every_station_carries_provenance(self):
        """Accessibility data must state its source, date and live-ness."""
        from bot.services.accessibility import get_station_accessibility
        result = get_station_accessibility("Trindade")
        assert result["data_source"]
        assert result["data_date"]
        assert result["live_status_available"] is False
        assert result["verified_live"] is False
        # The note must point users at official live information.
        assert "metrodoporto" in result["notes_pt"].lower()
        assert "metrodoporto" in result["notes_en"].lower()
        assert result["notes_pt"] != ""
        assert result["notes_en"] != ""

    def test_has_live_elevator_status_is_false(self):
        """There is no public live lift feed, so this must not claim one."""
        from bot.services.accessibility import has_live_elevator_status
        assert has_live_elevator_status() is False

    def test_get_accessible_stations(self):
        """Test that get_accessible_stations returns all metro stations."""
        from bot.services.accessibility import get_accessible_stations
        from bot.services.metro import STATIONS
        stations = get_accessible_stations()
        assert len(stations) == len(STATIONS)
        # Every station should have all required keys
        for station in stations:
            assert "name" in station
            assert "elevator" in station
            assert "ramp" in station
            assert "tactile" in station
            assert "audio" in station

    def test_search_accessible_features_elevator_ok(self):
        """Test searching for stations with operational elevators."""
        from bot.services.accessibility import search_accessible_features
        from bot.services.metro import STATIONS
        results = search_accessible_features("elevator_ok")
        assert len(results) > 0
        # All results should have operational elevators
        for r in results:
            assert r["elevator_status"] == "operational"
        # No station is claimed to be in maintenance any more.
        assert len(results) == len(STATIONS)

    def test_search_accessible_features_elevator_maintenance(self):
        """Without a live source, no station may be reported as out of order."""
        from bot.services.accessibility import search_accessible_features
        results = search_accessible_features("elevator_maintenance")
        assert results == []

    def test_search_accessible_features_ramp(self):
        """Test searching by ramp feature."""
        from bot.services.accessibility import search_accessible_features
        from bot.services.metro import STATIONS
        results = search_accessible_features("ramp")
        assert len(results) == len(STATIONS)

    def test_no_hardcoded_maintenance_station_list(self):
        """The invented _MAINTENANCE_STATIONS set must be gone."""
        import bot.services.accessibility as mod
        assert not hasattr(mod, "_MAINTENANCE_STATIONS")

    def test_all_metro_stations_have_accessibility(self):
        """Test that every metro station has accessibility data."""
        from bot.services.accessibility import ACCESSIBILITY
        from bot.services.metro import STATIONS
        for station_name in STATIONS:
            assert station_name in ACCESSIBILITY, f"{station_name} missing accessibility data"


# ===================================================================
# Accessibility keyboard tests
# ===================================================================

class TestAccessibilityKeyboards:
    """Tests for accessibility-related keyboards."""

    def test_accessibility_menu_keyboard(self):
        from bot.keyboards.inline import accessibility_menu_keyboard
        kb = accessibility_menu_keyboard("pt")
        assert kb is not None
        all_buttons = [btn for row in kb.inline_keyboard for btn in row]
        callbacks = [btn.callback_data for btn in all_buttons]
        assert "access:search" in callbacks
        assert "access:elevators" in callbacks
        assert "menu:main" in callbacks

    def test_accessibility_station_keyboard(self):
        from bot.keyboards.inline import accessibility_station_keyboard
        kb = accessibility_station_keyboard("Trindade", "pt")
        assert kb is not None
        all_buttons = [btn for row in kb.inline_keyboard for btn in row]
        callbacks = [btn.callback_data for btn in all_buttons]
        assert "access:search" in callbacks
        assert "menu:accessibility" in callbacks

    def test_accessibility_in_main_menu(self):
        from bot.keyboards.inline import main_menu_keyboard
        kb = main_menu_keyboard("pt")
        all_buttons = [btn for row in kb.inline_keyboard for btn in row]
        callbacks = [btn.callback_data for btn in all_buttons]
        assert "menu:accessibility" in callbacks


# ===================================================================
# Accessibility handler tests
# ===================================================================

class TestAccessibilityHandlers:
    """Tests for accessibility handler functions."""

    @pytest.mark.asyncio
    async def test_accessibility_command(self):
        """Test /acessibilidade command shows menu."""
        from bot.handlers.accessibility import accessibility_command
        update = _make_update()
        context = _make_context()
        await accessibility_command(update, context)
        update.message.reply_text.assert_called_once()
        call_args = update.message.reply_text.call_args[0][0]
        assert "Acessibilidade" in call_args or "Accessibility" in call_args

    @pytest.mark.asyncio
    async def test_accessibility_menu_callback(self):
        """Test accessibility menu callback."""
        from bot.handlers.accessibility import accessibility_menu_callback
        update = _make_update()
        context = _make_context()
        await accessibility_menu_callback(update, context)
        update.callback_query.answer.assert_called_once()
        update.callback_query.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_accessibility_station_callback(self):
        """Test station accessibility callback."""
        from bot.handlers.accessibility import accessibility_station_callback
        update = _make_update()
        update.callback_query.data = "access:station:Trindade"
        context = _make_context()
        await accessibility_station_callback(update, context)
        update.callback_query.edit_message_text.assert_called_once()
        call_args = update.callback_query.edit_message_text.call_args[0][0]
        assert "Trindade" in call_args

    @pytest.mark.asyncio
    async def test_accessibility_station_callback_not_found(self):
        """Test station callback with unknown station."""
        from bot.handlers.accessibility import accessibility_station_callback
        update = _make_update()
        update.callback_query.data = "access:station:NonExistentXYZ"
        context = _make_context()
        await accessibility_station_callback(update, context)
        update.callback_query.edit_message_text.assert_called_once()
        call_args = update.callback_query.edit_message_text.call_args[0][0]
        assert "NonExistentXYZ" in call_args

    @pytest.mark.asyncio
    async def test_accessibility_search_callback(self):
        """Test search callback sets step."""
        from bot.handlers.accessibility import accessibility_search_callback
        update = _make_update()
        context = _make_context()
        await accessibility_search_callback(update, context)
        assert context.user_data.get("accessibility_step") == "search"

    @pytest.mark.asyncio
    async def test_accessibility_elevators_callback(self):
        """Test elevators overview callback."""
        from bot.handlers.accessibility import accessibility_elevators_callback
        update = _make_update()
        context = _make_context()
        await accessibility_elevators_callback(update, context)
        update.callback_query.edit_message_text.assert_called_once()
        call_args = update.callback_query.edit_message_text.call_args[0][0]
        # Zero stations are claimed to be under maintenance now, because no
        # live lift-status source exists.
        assert "0" in call_args

    @pytest.mark.asyncio
    async def test_handle_accessibility_text_search(self):
        """Test text input for station search."""
        from bot.handlers.accessibility import handle_accessibility_text_input
        update = _make_update(text="Trindade")
        context = _make_context(user_data={"accessibility_step": "search"})
        result = await handle_accessibility_text_input(update, context)
        assert result is True
        update.message.reply_text.assert_called_once()
        call_args = update.message.reply_text.call_args[0][0]
        assert "Trindade" in call_args

    @pytest.mark.asyncio
    async def test_handle_accessibility_text_not_awaiting(self):
        """Test that text handler returns False when not in accessibility flow."""
        from bot.handlers.accessibility import handle_accessibility_text_input
        update = _make_update(text="Trindade")
        context = _make_context()
        result = await handle_accessibility_text_input(update, context)
        assert result is False

    @pytest.mark.asyncio
    async def test_handle_accessibility_text_unknown(self):
        """Test text input with unknown station."""
        from bot.handlers.accessibility import handle_accessibility_text_input
        update = _make_update(text="NonExistentStationXYZ123")
        context = _make_context(user_data={"accessibility_step": "search"})
        result = await handle_accessibility_text_input(update, context)
        assert result is True
        update.message.reply_text.assert_called_once()
        call_args = update.message.reply_text.call_args[0][0]
        assert "NonExistentStationXYZ123" in call_args


# ===================================================================
# i18n tests
# ===================================================================

class TestAccessibilityI18n:
    """Tests for accessibility-related translations."""

    def test_accessibility_translations_exist_pt(self):
        from bot.utils.i18n import t
        assert t("accessibility_title", "pt") != "accessibility_title"
        assert t("accessibility_overview", "pt") != "accessibility_overview"
        assert t("accessibility_station_info", "pt") != "accessibility_station_info"

    def test_accessibility_translations_exist_en(self):
        from bot.utils.i18n import t
        assert t("accessibility_title", "en") != "accessibility_title"
        assert t("accessibility_overview", "en") != "accessibility_overview"
        assert t("accessibility_station_info", "en") != "accessibility_station_info"

    def test_accessibility_keyboard_labels_exist(self):
        from bot.utils.i18n import t
        for lang in ("pt", "en"):
            assert t("kb_accessibility", lang) != "kb_accessibility"
            assert t("kb_accessibility_search", lang) != "kb_accessibility_search"
            assert t("kb_accessibility_elevators", lang) != "kb_accessibility_elevators"

    def test_accessibility_status_labels_exist(self):
        from bot.utils.i18n import t
        for lang in ("pt", "en"):
            assert t("accessibility_status_ok", lang) != "accessibility_status_ok"
            assert t("accessibility_status_maintenance", lang) != "accessibility_status_maintenance"
            assert t("accessibility_status_out", lang) != "accessibility_status_out"
