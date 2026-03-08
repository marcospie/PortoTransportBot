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
