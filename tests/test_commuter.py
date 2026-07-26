"""Tests for the Commuter Profile feature."""

import json
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import bot.database as db_mod
from bot.database import (
    DEFAULT_COMMUTER_PROFILE,
    save_commuter_profile,
    get_commuter_profile,
    delete_commuter_profile,
    _json_commuter_path,
)


# ===================================================================
# Profile storage (JSON fallback)
# ===================================================================

class TestCommuterProfileStorage:
    """Test commuter profile save/load/delete with JSON fallback."""

    TEST_USER = 770000001

    def _cleanup(self):
        path = _json_commuter_path(self.TEST_USER)
        if path.exists():
            os.remove(path)

    @pytest.mark.asyncio
    async def test_save_and_load_profile(self):
        original = db_mod._use_db
        db_mod._use_db = False
        try:
            profile = {
                "home_name": "Trindade",
                "home_lat": 41.1519,
                "home_lon": -8.6099,
                "work_name": "Casa da Música",
                "work_lat": 41.1586,
                "work_lon": -8.6306,
                "preferred_mode": "metro",
                "usual_departure_time": "08:30",
                "usual_return_time": "17:30",
            }
            await save_commuter_profile(self.TEST_USER, profile)
            loaded = await get_commuter_profile(self.TEST_USER)

            assert loaded is not None
            assert loaded["home_name"] == "Trindade"
            assert loaded["work_name"] == "Casa da Música"
            assert loaded["preferred_mode"] == "metro"
            assert loaded["usual_departure_time"] == "08:30"
            assert loaded["usual_return_time"] == "17:30"
        finally:
            self._cleanup()
            db_mod._use_db = original

    @pytest.mark.asyncio
    async def test_load_nonexistent_profile_returns_none(self):
        original = db_mod._use_db
        db_mod._use_db = False
        try:
            result = await get_commuter_profile(770099999)
            assert result is None
        finally:
            db_mod._use_db = original

    @pytest.mark.asyncio
    async def test_delete_profile(self):
        original = db_mod._use_db
        db_mod._use_db = False
        try:
            await save_commuter_profile(self.TEST_USER, {"home_name": "Test"})
            result = await delete_commuter_profile(self.TEST_USER)
            assert result is True

            loaded = await get_commuter_profile(self.TEST_USER)
            assert loaded is None
        finally:
            self._cleanup()
            db_mod._use_db = original

    @pytest.mark.asyncio
    async def test_delete_nonexistent_profile(self):
        original = db_mod._use_db
        db_mod._use_db = False
        try:
            result = await delete_commuter_profile(770099999)
            assert result is False
        finally:
            db_mod._use_db = original

    @pytest.mark.asyncio
    async def test_save_merges_with_defaults(self):
        original = db_mod._use_db
        db_mod._use_db = False
        try:
            await save_commuter_profile(self.TEST_USER, {"home_name": "Bolhão"})
            loaded = await get_commuter_profile(self.TEST_USER)

            assert loaded is not None
            assert loaded["home_name"] == "Bolhão"
            # Should have defaults for missing keys
            assert loaded["preferred_mode"] == "any"
            assert loaded["usual_departure_time"] == "08:00"
            assert loaded["usual_return_time"] == "18:00"
        finally:
            self._cleanup()
            db_mod._use_db = original

    def test_default_commuter_profile_has_all_keys(self):
        expected_keys = {
            "home_name", "home_lat", "home_lon",
            "work_name", "work_lat", "work_lon",
            "preferred_mode", "usual_departure_time", "usual_return_time",
        }
        assert set(DEFAULT_COMMUTER_PROFILE.keys()) == expected_keys


# ===================================================================
# Setup flow
# ===================================================================

class TestCommuterSetupFlow:
    """Test the commuter setup flow handlers."""

    @pytest.mark.asyncio
    async def test_setup_callback_sets_step(self):
        from bot.handlers.commuter import commuter_setup_callback

        update = MagicMock()
        query = AsyncMock()
        update.callback_query = query
        update.effective_user.id = 123
        update.effective_user.language_code = "pt"
        context = MagicMock()
        context.user_data = {}

        await commuter_setup_callback(update, context)

        assert context.user_data["commuter_step"] == "home"
        assert context.user_data["commuter_setup"] == {}
        query.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_mode_callback_advances_to_departure(self):
        from bot.handlers.commuter import commuter_mode_callback

        update = MagicMock()
        query = AsyncMock()
        query.data = "commuter:mode:metro"
        update.callback_query = query
        update.effective_user.id = 123
        update.effective_user.language_code = "pt"
        context = MagicMock()
        context.user_data = {"commuter_setup": {}, "commuter_step": "mode"}

        await commuter_mode_callback(update, context)

        assert context.user_data["commuter_setup"]["preferred_mode"] == "metro"
        assert context.user_data["commuter_step"] == "departure"

    @pytest.mark.asyncio
    async def test_text_input_home_step_advances(self):
        from bot.handlers.commuter import handle_commuter_text_input

        update = MagicMock()
        update.message.text = "Trindade"
        update.effective_user.id = 123
        update.effective_user.language_code = "pt"
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.user_data = {"commuter_setup": {}, "commuter_step": "home"}

        mock_loc = {"name": "Trindade", "lat": 41.15, "lon": -8.61}
        with patch("bot.handlers.commuter._resolve_location_async",
                   return_value=mock_loc):
            result = await handle_commuter_text_input(update, context)

        assert result is True
        assert context.user_data["commuter_step"] == "work"
        assert context.user_data["commuter_setup"]["home_name"] == "Trindade"

    @pytest.mark.asyncio
    async def test_text_input_invalid_time_rejected(self):
        from bot.handlers.commuter import handle_commuter_text_input

        update = MagicMock()
        update.message.text = "invalid"
        update.effective_user.id = 123
        update.effective_user.language_code = "pt"
        update.message.reply_text = AsyncMock()
        context = MagicMock()
        context.user_data = {"commuter_setup": {}, "commuter_step": "departure"}

        result = await handle_commuter_text_input(update, context)

        assert result is True
        # Step should NOT advance
        assert context.user_data["commuter_step"] == "departure"

    @pytest.mark.asyncio
    async def test_text_input_not_in_setup_returns_false(self):
        from bot.handlers.commuter import handle_commuter_text_input

        update = MagicMock()
        update.message.text = "hello"
        context = MagicMock()
        context.user_data = {}

        result = await handle_commuter_text_input(update, context)
        assert result is False


# ===================================================================
# Quick action handlers
# ===================================================================

class TestCommuterQuickActions:
    """Test commuter quick action handlers."""

    @pytest.mark.asyncio
    async def test_go_work_shows_route(self):
        from bot.handlers.commuter import commuter_go_work_callback

        profile = {
            "home_name": "Bolhão",
            "work_name": "Casa da Música",
            "preferred_mode": "metro",
            "usual_departure_time": "08:30",
            "usual_return_time": "17:30",
        }

        update = MagicMock()
        query = AsyncMock()
        update.callback_query = query
        update.effective_user.id = 123
        update.effective_user.language_code = "pt"
        context = MagicMock()

        with patch("bot.handlers.commuter.get_commuter_profile",
                   return_value=profile):
            await commuter_go_work_callback(update, context)

        query.edit_message_text.assert_called_once()
        text = query.edit_message_text.call_args[0][0]
        assert "Bolhão" in text
        assert "Casa da Música" in text

    @pytest.mark.asyncio
    async def test_go_home_shows_route(self):
        from bot.handlers.commuter import commuter_go_home_callback

        profile = {
            "home_name": "Bolhão",
            "work_name": "Casa da Música",
            "preferred_mode": "bus",
            "usual_departure_time": "08:30",
            "usual_return_time": "17:30",
        }

        update = MagicMock()
        query = AsyncMock()
        update.callback_query = query
        update.effective_user.id = 123
        update.effective_user.language_code = "pt"
        context = MagicMock()

        with patch("bot.handlers.commuter.get_commuter_profile",
                   return_value=profile):
            await commuter_go_home_callback(update, context)

        query.edit_message_text.assert_called_once()
        text = query.edit_message_text.call_args[0][0]
        assert "Bolhão" in text
        assert "Casa da Música" in text

    @pytest.mark.asyncio
    async def test_my_times_shows_schedule(self):
        from bot.handlers.commuter import commuter_my_times_callback

        profile = {
            "home_name": "Trindade",
            "work_name": "Aeroporto",
            "preferred_mode": "metro",
            "usual_departure_time": "07:45",
            "usual_return_time": "18:15",
        }

        update = MagicMock()
        query = AsyncMock()
        update.callback_query = query
        update.effective_user.id = 123
        update.effective_user.language_code = "pt"
        context = MagicMock()

        with patch("bot.handlers.commuter.get_commuter_profile",
                   return_value=profile):
            await commuter_my_times_callback(update, context)

        query.edit_message_text.assert_called_once()
        text = query.edit_message_text.call_args[0][0]
        assert "07:45" in text
        assert "18:15" in text


# ===================================================================
# Keyboard builders
# ===================================================================

class TestCommuterKeyboards:
    """Test commuter keyboard builders."""

    def test_menu_keyboard_no_profile(self):
        from bot.keyboards.inline import commuter_menu_keyboard
        kb = commuter_menu_keyboard(False, "pt")
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "commuter:setup" in all_data
        assert "menu:main" in all_data

    def test_menu_keyboard_with_profile(self):
        from bot.keyboards.inline import commuter_menu_keyboard
        kb = commuter_menu_keyboard(True, "pt")
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "commuter:go_work" in all_data
        assert "commuter:go_home" in all_data
        assert "commuter:my_times" in all_data
        assert "commuter:delete" in all_data

    def test_mode_keyboard(self):
        from bot.keyboards.inline import commuter_mode_keyboard
        kb = commuter_mode_keyboard("pt")
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "commuter:mode:metro" in all_data
        assert "commuter:mode:bus" in all_data
        assert "commuter:mode:any" in all_data
        assert "commuter:cancel" in all_data

    def test_quick_actions_keyboard(self):
        from bot.keyboards.inline import commuter_quick_actions_keyboard
        kb = commuter_quick_actions_keyboard("en")
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "commuter:go_work" in all_data
        assert "commuter:go_home" in all_data
        assert "commuter:my_times" in all_data
        assert "commuter:setup" in all_data  # edit = setup again
        assert "menu:main" in all_data

    def test_setup_keyboard_cancel(self):
        from bot.keyboards.inline import commuter_setup_keyboard
        kb = commuter_setup_keyboard("home", "pt")
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "commuter:cancel" in all_data


# ===================================================================
# i18n
# ===================================================================

class TestCommuterI18n:
    """Test that commuter translations exist in both languages."""

    def test_pt_translations_exist(self):
        from bot.utils.i18n import t
        keys = [
            "commuter_title", "commuter_no_profile", "commuter_ask_home",
            "commuter_ask_work", "commuter_ask_mode", "commuter_ask_departure",
            "commuter_ask_return", "commuter_confirm", "commuter_deleted",
            "commuter_go_work", "commuter_go_home", "commuter_my_times",
            "commuter_edit", "commuter_delete", "commuter_setup",
            "commuter_mode_metro", "commuter_mode_bus", "commuter_mode_any",
        ]
        for key in keys:
            val = t(key, "pt")
            assert val != key, f"Missing PT translation for {key}"

    def test_en_translations_exist(self):
        from bot.utils.i18n import t
        keys = [
            "commuter_title", "commuter_no_profile", "commuter_ask_home",
            "commuter_ask_work", "commuter_ask_mode", "commuter_ask_departure",
            "commuter_ask_return", "commuter_confirm", "commuter_deleted",
            "commuter_go_work", "commuter_go_home", "commuter_my_times",
            "commuter_edit", "commuter_delete", "commuter_setup",
            "commuter_mode_metro", "commuter_mode_bus", "commuter_mode_any",
        ]
        for key in keys:
            val = t(key, "en")
            assert val != key, f"Missing EN translation for {key}"


# ===================================================================
# Coordinate validation during setup (no more corrupted profiles)
# ===================================================================

class TestCommuterCoordinateValidation:
    """The old ``_resolve_location`` could return lat/lon 0.0 and store it."""

    def test_resolve_rejects_unknown_name(self):
        from bot.handlers.commuter import _resolve_location
        assert _resolve_location("xyznonexistent12345") is None

    def test_resolve_rejects_empty(self):
        from bot.handlers.commuter import _resolve_location
        assert _resolve_location("") is None
        assert _resolve_location("   ") is None

    def test_resolve_metro_station(self):
        from bot.handlers.commuter import _resolve_location
        result = _resolve_location("Trindade")
        assert result is not None
        assert result["name"] == "Trindade"
        assert result["lat"] != 0.0 and result["lon"] != 0.0

    def test_resolve_is_not_metro_only(self):
        """CP and MetroBus locations resolve too (metro-only before)."""
        from bot.handlers.commuter import _resolve_location
        assert _resolve_location("Rotunda da Boavista") is not None
        assert _resolve_location("Ermesinde") is not None

    def test_resolve_rejects_zero_coordinates(self):
        from bot.handlers.commuter import _resolve_location
        with patch("bot.handlers.commuter.resolve_transport_location") as resolver:
            resolver.return_value = {"name": "Broken", "lat": 0.0, "lon": 0.0,
                                     "type": "bus"}
            assert _resolve_location("Broken") is None

    def test_resolve_rejects_out_of_region_coordinates(self):
        from bot.handlers.commuter import _resolve_location
        with patch("bot.handlers.commuter.resolve_transport_location") as resolver:
            resolver.return_value = {"name": "Paris", "lat": 48.85, "lon": 2.35,
                                     "type": "bus"}
            assert _resolve_location("Paris") is None

    @pytest.mark.asyncio
    async def test_async_resolver_rejects_zero_coordinates(self):
        from bot.handlers.commuter import _resolve_location_async
        with patch("bot.handlers.commuter.resolve_transport_location",
                   return_value=None), \
             patch("bot.handlers.commuter.resolve_location_any",
                   new_callable=AsyncMock) as any_resolver:
            any_resolver.return_value = {"name": "Zero", "lat": 0.0, "lon": 0.0}
            assert await _resolve_location_async("Zero") is None

    @pytest.mark.asyncio
    async def test_setup_rejects_invalid_coordinates_without_advancing(self):
        from bot.handlers.commuter import handle_commuter_text_input

        update = MagicMock()
        update.message.text = "Somewhere"
        update.message.reply_text = AsyncMock()
        update.effective_user.id = 123
        update.effective_user.language_code = "pt"
        context = MagicMock()
        context.user_data = {"commuter_setup": {}, "commuter_step": "home"}

        with patch("bot.handlers.commuter._resolve_location_async",
                   return_value={"name": "Broken", "lat": 0.0, "lon": 0.0}):
            handled = await handle_commuter_text_input(update, context)

        assert handled is True
        assert context.user_data["commuter_step"] == "home"
        assert "home_lat" not in context.user_data["commuter_setup"]

    @pytest.mark.asyncio
    async def test_profile_is_not_saved_with_invalid_coordinates(self):
        from bot.handlers.commuter import handle_commuter_text_input

        update = MagicMock()
        update.message.text = "18:30"
        update.message.reply_text = AsyncMock()
        update.effective_user.id = 123
        update.effective_user.language_code = "pt"
        context = MagicMock()
        context.user_data = {
            "commuter_setup": {
                "home_name": "Broken", "home_lat": 0.0, "home_lon": 0.0,
                "work_name": "Broken", "work_lat": 0.0, "work_lon": 0.0,
                "preferred_mode": "any", "usual_departure_time": "08:00",
            },
            "commuter_step": "return",
        }

        with patch("bot.handlers.commuter.save_commuter_profile",
                   new_callable=AsyncMock) as save:
            handled = await handle_commuter_text_input(update, context)

        assert handled is True
        save.assert_not_called()

    @pytest.mark.asyncio
    async def test_profile_is_saved_with_valid_coordinates(self):
        from bot.handlers.commuter import handle_commuter_text_input

        update = MagicMock()
        update.message.text = "18:30"
        update.message.reply_text = AsyncMock()
        update.effective_user.id = 123
        update.effective_user.language_code = "pt"
        context = MagicMock()
        context.user_data = {
            "commuter_setup": {
                "home_name": "Trindade", "home_lat": 41.1519, "home_lon": -8.6102,
                "work_name": "Aeroporto", "work_lat": 41.2370, "work_lon": -8.6694,
                "preferred_mode": "metro", "usual_departure_time": "08:00",
            },
            "commuter_step": "return",
        }

        with patch("bot.handlers.commuter.save_commuter_profile",
                   new_callable=AsyncMock) as save:
            handled = await handle_commuter_text_input(update, context)

        assert handled is True
        save.assert_awaited_once()
        saved = save.call_args[0][1]
        assert saved["home_lat"] == 41.1519
        assert saved["usual_return_time"] == "18:30"

    def test_profile_coords_helper(self):
        from bot.handlers.commuter import profile_coords
        assert profile_coords({"home_lat": 0.0, "home_lon": 0.0,
                               "work_lat": 41.15, "work_lon": -8.61}) is None
        assert profile_coords({"home_lat": 41.15, "home_lon": -8.61,
                               "work_lat": 41.23, "work_lon": -8.66}) is not None
        assert profile_coords({}) is None


# ===================================================================
# Sharing a location during setup
# ===================================================================

class TestCommuterLocationSetup:

    def _update(self, lat, lon, lang="pt"):
        update = MagicMock()
        update.message.location = MagicMock(latitude=lat, longitude=lon)
        update.message.reply_text = AsyncMock()
        update.effective_user.id = 123
        update.effective_user.language_code = lang
        return update

    @pytest.mark.asyncio
    async def test_location_sets_home_and_advances(self):
        from bot.handlers.commuter import handle_commuter_location

        update = self._update(41.1519, -8.6102)
        context = MagicMock()
        context.user_data = {"commuter_setup": {}, "commuter_step": "home"}

        handled = await handle_commuter_location(update, context)

        assert handled is True
        assert context.user_data["commuter_step"] == "work"
        assert context.user_data["commuter_setup"]["home_lat"] == 41.1519

    @pytest.mark.asyncio
    async def test_location_sets_work_and_advances_to_mode(self):
        from bot.handlers.commuter import handle_commuter_location

        update = self._update(41.2370, -8.6694)
        context = MagicMock()
        context.user_data = {
            "commuter_setup": {"home_name": "X", "home_lat": 41.15,
                               "home_lon": -8.61},
            "commuter_step": "work",
        }

        handled = await handle_commuter_location(update, context)

        assert handled is True
        assert context.user_data["commuter_step"] == "mode"
        assert context.user_data["commuter_setup"]["work_lon"] == -8.6694

    @pytest.mark.asyncio
    async def test_out_of_region_location_rejected(self):
        from bot.handlers.commuter import handle_commuter_location

        update = self._update(48.8566, 2.3522)  # Paris
        context = MagicMock()
        context.user_data = {"commuter_setup": {}, "commuter_step": "home"}

        handled = await handle_commuter_location(update, context)

        assert handled is True
        assert context.user_data["commuter_step"] == "home"
        assert context.user_data["commuter_setup"] == {}

    @pytest.mark.asyncio
    async def test_location_ignored_outside_setup(self):
        from bot.handlers.commuter import handle_commuter_location

        update = self._update(41.1519, -8.6102)
        context = MagicMock()
        context.user_data = {}

        assert await handle_commuter_location(update, context) is False

    @pytest.mark.asyncio
    async def test_setup_offers_a_location_button(self):
        from bot.handlers.commuter import commuter_setup_callback
        from telegram import ReplyKeyboardMarkup

        update = MagicMock()
        query = AsyncMock()
        query.message = MagicMock()
        query.message.reply_text = AsyncMock()
        update.callback_query = query
        update.effective_user.id = 123
        update.effective_user.language_code = "pt"
        context = MagicMock()
        context.user_data = {}

        await commuter_setup_callback(update, context)

        query.message.reply_text.assert_awaited()
        markup = query.message.reply_text.call_args.kwargs["reply_markup"]
        assert isinstance(markup, ReplyKeyboardMarkup)
        assert markup.keyboard[0][0].request_location is True


# ===================================================================
# "Go to work" / "Go home" show a real route
# ===================================================================

def _valid_profile(mode="metro"):
    return {
        "home_name": "Trindade",
        "home_lat": 41.1519,
        "home_lon": -8.6102,
        "work_name": "Aeroporto",
        "work_lat": 41.2370,
        "work_lon": -8.6694,
        "preferred_mode": mode,
        "usual_departure_time": "08:30",
        "usual_return_time": "17:30",
    }


def _fake_options():
    from bot.services.trip_planner import TripOption, TripStep
    return [
        TripOption(
            steps=[
                TripStep(mode="walk", from_name="", to_name="Trindade",
                         duration_min=4),
                TripStep(mode="metro", from_name="Trindade",
                         to_name="Aeroporto", line="Linha Violeta",
                         duration_min=32, direction="Aeroporto",
                         departure_time="08:34"),
            ],
            total_time_min=36,
            transfers=0,
            estimated=False,
            source="motis",
            departure_time="08:30",
            arrival_time="09:06",
        ),
    ]


class TestCommuterRealRoute:

    def _update(self, lang="pt"):
        update = MagicMock()
        query = AsyncMock()
        query.message = MagicMock()
        query.message.reply_text = AsyncMock()
        update.callback_query = query
        update.effective_user.id = 123
        update.effective_user.language_code = lang
        return update, query

    @pytest.mark.asyncio
    async def test_go_work_plans_a_real_route(self):
        from bot.handlers.commuter import commuter_go_work_callback

        update, query = self._update()
        context = MagicMock()
        context.user_data = {}

        with patch("bot.handlers.commuter.get_commuter_profile",
                   return_value=_valid_profile()), \
             patch("bot.handlers.commuter.plan_trip_from_coords_async",
                   new_callable=AsyncMock) as planner:
            planner.return_value = _fake_options()
            await commuter_go_work_callback(update, context)

        planner.assert_awaited_once_with(41.1519, -8.6102, 41.2370, -8.6694)
        text = query.edit_message_text.call_args[0][0]
        assert "Linha Violeta" in text
        assert "08:34" in text
        assert "36 min" in text

    @pytest.mark.asyncio
    async def test_go_home_reverses_the_direction(self):
        from bot.handlers.commuter import commuter_go_home_callback

        update, _query = self._update()
        context = MagicMock()
        context.user_data = {}

        with patch("bot.handlers.commuter.get_commuter_profile",
                   return_value=_valid_profile()), \
             patch("bot.handlers.commuter.plan_trip_from_coords_async",
                   new_callable=AsyncMock) as planner:
            planner.return_value = _fake_options()
            await commuter_go_home_callback(update, context)

        planner.assert_awaited_once_with(41.2370, -8.6694, 41.1519, -8.6102)

    @pytest.mark.asyncio
    async def test_options_are_stored_for_the_detail_view(self):
        from bot.handlers.commuter import commuter_go_work_callback

        update, _query = self._update()
        context = MagicMock()
        context.user_data = {}

        with patch("bot.handlers.commuter.get_commuter_profile",
                   return_value=_valid_profile()), \
             patch("bot.handlers.commuter.plan_trip_from_coords_async",
                   new_callable=AsyncMock) as planner:
            planner.return_value = _fake_options()
            await commuter_go_work_callback(update, context)

        assert context.user_data["trip_options"]

    @pytest.mark.asyncio
    async def test_detail_buttons_are_within_callback_limit(self):
        from bot.handlers.commuter import commuter_go_work_callback

        update, query = self._update()
        context = MagicMock()
        context.user_data = {}

        with patch("bot.handlers.commuter.get_commuter_profile",
                   return_value=_valid_profile()), \
             patch("bot.handlers.commuter.plan_trip_from_coords_async",
                   new_callable=AsyncMock) as planner:
            planner.return_value = _fake_options()
            await commuter_go_work_callback(update, context)

        markup = query.edit_message_text.call_args.kwargs["reply_markup"]
        callbacks = [b.callback_data for row in markup.inline_keyboard for b in row]
        assert "trip:detail:0" in callbacks
        for data in callbacks:
            assert len(data.encode("utf-8")) <= 64

    @pytest.mark.asyncio
    async def test_no_route_found_is_reported(self):
        from bot.handlers.commuter import commuter_go_work_callback
        from bot.utils.i18n import t

        update, query = self._update()
        context = MagicMock()
        context.user_data = {}

        with patch("bot.handlers.commuter.get_commuter_profile",
                   return_value=_valid_profile()), \
             patch("bot.handlers.commuter.plan_trip_from_coords_async",
                   new_callable=AsyncMock) as planner:
            planner.return_value = []
            await commuter_go_work_callback(update, context)

        text = query.edit_message_text.call_args[0][0]
        assert t("trip_no_routes", "pt") in text

    @pytest.mark.asyncio
    async def test_profile_with_invalid_coords_is_not_planned(self):
        from bot.handlers.commuter import commuter_go_work_callback

        update, query = self._update()
        context = MagicMock()
        context.user_data = {}
        broken = _valid_profile()
        broken["work_lat"] = 0.0
        broken["work_lon"] = 0.0

        with patch("bot.handlers.commuter.get_commuter_profile",
                   return_value=broken), \
             patch("bot.handlers.commuter.plan_trip_from_coords_async",
                   new_callable=AsyncMock) as planner:
            await commuter_go_work_callback(update, context)

        planner.assert_not_called()
        text = query.edit_message_text.call_args[0][0]
        # Names are still shown so the user knows which profile is broken.
        assert "Trindade" in text

    @pytest.mark.asyncio
    async def test_planner_failure_degrades_gracefully(self):
        from bot.handlers.commuter import commuter_go_work_callback

        update, query = self._update()
        context = MagicMock()
        context.user_data = {}

        with patch("bot.handlers.commuter.get_commuter_profile",
                   return_value=_valid_profile()), \
             patch("bot.handlers.commuter.plan_trip_from_coords_async",
                   new_callable=AsyncMock) as planner:
            planner.side_effect = RuntimeError("network down")
            await commuter_go_work_callback(update, context)

        query.edit_message_text.assert_awaited()

    @pytest.mark.asyncio
    async def test_estimated_route_is_labelled(self):
        from bot.handlers.commuter import commuter_go_work_callback
        from bot.services.trip_planner import TripOption, TripStep
        from bot.utils.i18n import t

        update, query = self._update()
        context = MagicMock()
        context.user_data = {}
        estimate = [TripOption(
            steps=[TripStep(mode="metro", from_name="Trindade",
                            to_name="Aeroporto", line="Linha Violeta",
                            duration_min=30)],
            total_time_min=30, transfers=0, estimated=True, source="estimate",
        )]

        with patch("bot.handlers.commuter.get_commuter_profile",
                   return_value=_valid_profile()), \
             patch("bot.handlers.commuter.plan_trip_from_coords_async",
                   new_callable=AsyncMock) as planner:
            planner.return_value = estimate
            await commuter_go_work_callback(update, context)

        text = query.edit_message_text.call_args[0][0]
        assert t("data_estimated", "pt") in text
