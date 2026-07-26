"""Regression tests for favorite transport types, the star toggle, /fav and /start.

Covers four user-facing bugs:

* a saved CP train / MetroBus favorite opened the *metro* handler;
* favoriting from a detail view left the button saying "add" and unfavoriting
  replaced the arrivals the user was reading with the favorites list;
* ``/fav`` could only ever open the first favorite;
* ``/start`` never sent the persistent "Near me" reply keyboard.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from telegram import ReplyKeyboardMarkup

from bot.handlers import favorites as fav_mod
from bot.keyboards.inline import (
    bus_stop_actions_keyboard,
    favorites_keyboard,
    metro_station_actions_keyboard,
    metrobus_stop_actions_keyboard,
    train_station_actions_keyboard,
)

ACTIONS_BUILDERS = {
    "bus": bus_stop_actions_keyboard,
    "metro": metro_station_actions_keyboard,
    "metrobus": metrobus_stop_actions_keyboard,
    "train": train_station_actions_keyboard,
}

IDS = {
    "bus": "BCM2",
    "metro": "Trindade",
    "metrobus": "Boavista",
    "train": "Porto-Campanha",
}

DETAIL_TEXT = "🚇 *Trindade*\n━━━━━\n\n*Senhor de Matosinhos* — `3 min`"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _callbacks(markup):
    return [btn.callback_data for row in markup.inline_keyboard for btn in row
            if btn.callback_data]


def _update_for(action: str, fav_type: str, *, markup, lang="pt",
                text=DETAIL_TEXT, user_id=123):
    """Build a callback update whose message carries a real keyboard."""
    fav_id = IDS[fav_type]
    query = MagicMock()
    query.data = f"fav:{action}:{fav_type}:{fav_id}"
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.edit_message_reply_markup = AsyncMock()
    query.from_user.id = user_id
    query.message = MagicMock()
    query.message.reply_markup = markup
    query.message.text_markdown_v2 = text

    update = MagicMock()
    update.callback_query = query
    update.effective_user.id = user_id
    update.effective_user.language_code = lang
    return update, query


def _detail_update(action: str, fav_type: str, *, is_fav, lang="pt",
                   back_callback=None, text=DETAIL_TEXT):
    builder = ACTIONS_BUILDERS[fav_type]
    kwargs = {"is_fav": is_fav, "lang": lang}
    if back_callback is not None:
        kwargs["back_callback"] = back_callback
    markup = builder(IDS[fav_type], **kwargs)
    return _update_for(action, fav_type, markup=markup, lang=lang, text=text)


def _context(args=None):
    ctx = MagicMock()
    ctx.user_data = {}
    ctx.args = args if args is not None else []
    ctx.bot = MagicMock()
    ctx.bot.set_chat_menu_button = AsyncMock()
    return ctx


def _message_update(lang="pt", user_id=123):
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_user.language_code = lang
    update.effective_chat.id = 456
    update.message.reply_text = AsyncMock()
    return update


# ===================================================================
# 1. All four favorite types route to their own handler
# ===================================================================

class TestFavoriteTypeRouting:

    @pytest.mark.parametrize("fav_type,expected_prefix", [
        ("bus", "bus:stop:"),
        ("metro", "metro:station:"),
        ("metrobus", "metrobus:stop:"),
        ("train", "train:station:"),
    ])
    def test_keyboard_prefix(self, fav_type, expected_prefix):
        from bot.keyboards.inline import favorite_callback_data
        assert favorite_callback_data(fav_type, IDS[fav_type]) == \
            expected_prefix + IDS[fav_type]

    def test_prefixes_match_registered_handlers(self):
        """The prefixes must be the ones bot/main.py actually registers."""
        import inspect
        import bot.main as main_mod

        source = inspect.getsource(main_mod)
        for pattern in (r"^bus:stop:.+$", r"^metro:station:.+$",
                        r"^metrobus:stop:.+$", r"^train:station:.+$"):
            assert pattern in source, pattern

    @pytest.mark.asyncio
    @pytest.mark.parametrize("fav_type,target_module,target_func", [
        ("bus", "bot.handlers.bus", "_send_stop_realtime"),
        ("metro", "bot.handlers.metro", "_search_and_show_stations"),
        ("train", "bot.handlers.trains", "_search_and_show_stations"),
    ])
    async def test_fav_command_opens_correct_handler(self, fav_type,
                                                     target_module, target_func):
        update = _message_update()
        ctx = _context()
        favs = [{"type": fav_type, "id": IDS[fav_type], "name": IDS[fav_type]}]

        with patch.object(fav_mod, "get_favorites", new=AsyncMock(return_value=favs)), \
             patch(f"{target_module}.{target_func}", new_callable=AsyncMock) as mock_open:
            await fav_mod.fav_quick_command(update, ctx)

        mock_open.assert_awaited_once()
        assert mock_open.await_args[0][1] == IDS[fav_type]

    @pytest.mark.asyncio
    async def test_metrobus_favorite_does_not_use_metro_handler(self):
        update = _message_update()
        ctx = _context()
        favs = [{"type": "metrobus", "id": "Boavista", "name": "Boavista"}]

        with patch.object(fav_mod, "get_favorites", new=AsyncMock(return_value=favs)), \
             patch("bot.handlers.metro._search_and_show_stations",
                   new_callable=AsyncMock) as mock_metro, \
             patch.object(fav_mod, "_send_metrobus_stop",
                          new_callable=AsyncMock) as mock_mb:
            await fav_mod.fav_quick_command(update, ctx)

        mock_metro.assert_not_awaited()
        mock_mb.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_train_favorite_does_not_use_metro_handler(self):
        update = _message_update()
        ctx = _context()
        favs = [{"type": "train", "id": "Porto-Campanha", "name": "Porto-Campanha"}]

        with patch.object(fav_mod, "get_favorites", new=AsyncMock(return_value=favs)), \
             patch("bot.handlers.metro._search_and_show_stations",
                   new_callable=AsyncMock) as mock_metro, \
             patch("bot.handlers.trains._search_and_show_stations",
                   new_callable=AsyncMock) as mock_train:
            await fav_mod.fav_quick_command(update, ctx)

        mock_metro.assert_not_awaited()
        mock_train.assert_awaited_once()

    def test_all_four_types_declared(self):
        assert set(fav_mod.FAV_TYPES) == {"bus", "metro", "metrobus", "train"}

    def test_every_actions_keyboard_stores_its_own_type(self):
        """fav:add:<type> in the detail keyboards must match FAV_TYPES."""
        for fav_type, builder in ACTIONS_BUILDERS.items():
            data = _callbacks(builder(IDS[fav_type], is_fav=False))
            assert f"fav:add:{fav_type}:{IDS[fav_type]}" in data


# ===================================================================
# 2. Star toggles in place without destroying the view
# ===================================================================

class TestStarTogglesInPlace:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("fav_type", list(ACTIONS_BUILDERS))
    async def test_add_flips_button_to_remove(self, fav_type):
        update, query = _detail_update("add", fav_type, is_fav=False)
        ctx = _context()

        with patch.object(fav_mod, "is_favorite", new=AsyncMock(return_value=False)), \
             patch.object(fav_mod, "add_favorite", new=AsyncMock()), \
             patch("bot.services.stcp.get_stop_info",
                   new=AsyncMock(return_value={"name": "Boavista"})):
            await fav_mod.add_favorite_callback(update, ctx)

        query.edit_message_text.assert_awaited_once()
        markup = query.edit_message_text.await_args.kwargs["reply_markup"]
        data = _callbacks(markup)
        assert f"fav:remove:{fav_type}:{IDS[fav_type]}" in data
        assert not any(d.startswith("fav:add:") for d in data)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("fav_type", list(ACTIONS_BUILDERS))
    async def test_remove_flips_button_back_to_add(self, fav_type):
        update, query = _detail_update("remove", fav_type, is_fav=True)
        ctx = _context()

        with patch.object(fav_mod, "remove_favorite", new=AsyncMock()), \
             patch.object(fav_mod, "get_favorites",
                          new=AsyncMock(return_value=[])) as mock_get:
            await fav_mod.remove_favorite_callback(update, ctx)

        query.edit_message_text.assert_awaited_once()
        data = _callbacks(query.edit_message_text.await_args.kwargs["reply_markup"])
        assert f"fav:add:{fav_type}:{IDS[fav_type]}" in data
        # Did NOT navigate away to the favorites list.
        mock_get.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_remove_from_detail_keeps_the_message_text(self):
        update, query = _detail_update("remove", "metro", is_fav=True)
        ctx = _context()

        with patch.object(fav_mod, "remove_favorite", new=AsyncMock()), \
             patch.object(fav_mod, "get_favorites", new=AsyncMock(return_value=[])):
            await fav_mod.remove_favorite_callback(update, ctx)

        assert query.edit_message_text.await_args[0][0] == DETAIL_TEXT

    @pytest.mark.asyncio
    async def test_add_from_detail_keeps_the_message_text(self):
        update, query = _detail_update("add", "metro", is_fav=False)
        ctx = _context()

        with patch.object(fav_mod, "is_favorite", new=AsyncMock(return_value=False)), \
             patch.object(fav_mod, "add_favorite", new=AsyncMock()):
            await fav_mod.add_favorite_callback(update, ctx)

        assert query.edit_message_text.await_args[0][0] == DETAIL_TEXT

    @pytest.mark.asyncio
    async def test_back_callback_survives_the_toggle(self):
        update, query = _detail_update("add", "metro", is_fav=False,
                                       back_callback="metro:line:A")
        ctx = _context()

        with patch.object(fav_mod, "is_favorite", new=AsyncMock(return_value=False)), \
             patch.object(fav_mod, "add_favorite", new=AsyncMock()):
            await fav_mod.add_favorite_callback(update, ctx)

        data = _callbacks(query.edit_message_text.await_args.kwargs["reply_markup"])
        assert "metro:line:A" in data

    @pytest.mark.asyncio
    async def test_already_favorited_repairs_a_stale_button(self):
        """Tapping a stale "add" star must fix the keyboard, not just complain."""
        update, query = _detail_update("add", "metro", is_fav=False)
        ctx = _context()

        with patch.object(fav_mod, "is_favorite", new=AsyncMock(return_value=True)), \
             patch.object(fav_mod, "add_favorite", new=AsyncMock()) as mock_add:
            await fav_mod.add_favorite_callback(update, ctx)

        mock_add.assert_not_awaited()
        query.answer.assert_awaited_once()
        data = _callbacks(query.edit_message_text.await_args.kwargs["reply_markup"])
        assert "fav:remove:metro:Trindade" in data

    @pytest.mark.asyncio
    async def test_remove_from_favorites_list_refreshes_the_list(self):
        favs = [{"type": "metro", "id": "Trindade", "name": "Trindade"},
                {"type": "bus", "id": "BCM2", "name": "Boavista"}]
        update, query = _update_for("remove", "metro",
                                     markup=favorites_keyboard(favs),
                                     text="⭐ *Os teus favoritos*")
        ctx = _context()

        remaining = [favs[1]]
        with patch.object(fav_mod, "remove_favorite", new=AsyncMock()), \
             patch.object(fav_mod, "get_favorites",
                          new=AsyncMock(return_value=remaining)) as mock_get:
            await fav_mod.remove_favorite_callback(update, ctx)

        mock_get.assert_awaited_once()
        data = _callbacks(query.edit_message_text.await_args.kwargs["reply_markup"])
        assert "bus:stop:BCM2" in data
        assert "metro:station:Trindade" not in data

    @pytest.mark.asyncio
    async def test_unknown_view_falls_back_to_the_list(self):
        """No recoverable keyboard: refresh the list rather than crash."""
        update, query = _update_for("remove", "metro", markup=MagicMock())
        ctx = _context()

        with patch.object(fav_mod, "remove_favorite", new=AsyncMock()), \
             patch.object(fav_mod, "get_favorites", new=AsyncMock(return_value=[])):
            await fav_mod.remove_favorite_callback(update, ctx)

        query.edit_message_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_malformed_callback_data_is_rejected(self):
        update, query = _detail_update("add", "metro", is_fav=False)
        query.data = "fav:add"
        ctx = _context()

        await fav_mod.add_favorite_callback(update, ctx)

        query.answer.assert_awaited_once()
        query.edit_message_text.assert_not_awaited()

    def test_detail_view_detection(self):
        rows = list(metro_station_actions_keyboard("Trindade").inline_keyboard)
        assert fav_mod._is_detail_view(rows, "metro") is True
        list_rows = list(favorites_keyboard(
            [{"type": "metro", "id": "Trindade", "name": "Trindade"}]).inline_keyboard)
        assert fav_mod._is_detail_view(list_rows, "metro") is False
        assert fav_mod._is_detail_view(None, "metro") is False


# ===================================================================
# 3. /fav reaches every favorite, not just the first
# ===================================================================

MANY_FAVS = [
    {"type": "bus", "id": "BCM2", "name": "Boavista"},
    {"type": "metro", "id": "Trindade", "name": "Trindade"},
    {"type": "train", "id": "Porto-Campanha", "name": "Porto-Campanha"},
]


class TestFavQuickCommand:

    @pytest.mark.asyncio
    async def test_no_argument_with_many_shows_dashboard(self):
        update = _message_update()
        ctx = _context()

        with patch.object(fav_mod, "get_favorites", new=AsyncMock(return_value=MANY_FAVS)), \
             patch("bot.handlers.bus._send_stop_realtime",
                   new_callable=AsyncMock) as mock_bus:
            await fav_mod.fav_quick_command(update, ctx)

        # Must not silently open only the first favorite.
        mock_bus.assert_not_awaited()
        update.message.reply_text.assert_awaited_once()
        text = update.message.reply_text.await_args[0][0]
        for n in ("1", "2", "3"):
            assert f"{n}\\." in text
        markup = update.message.reply_text.await_args.kwargs["reply_markup"]
        data = _callbacks(markup)
        assert "bus:stop:BCM2" in data
        assert "metro:station:Trindade" in data
        assert "train:station:Porto-Campanha" in data

    @pytest.mark.asyncio
    async def test_single_favorite_opens_directly(self):
        update = _message_update()
        ctx = _context()

        with patch.object(fav_mod, "get_favorites",
                          new=AsyncMock(return_value=[MANY_FAVS[0]])), \
             patch("bot.handlers.bus._send_stop_realtime",
                   new_callable=AsyncMock) as mock_bus:
            await fav_mod.fav_quick_command(update, ctx)

        mock_bus.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_index_argument_opens_that_favorite(self):
        update = _message_update()
        ctx = _context(args=["2"])

        with patch.object(fav_mod, "get_favorites", new=AsyncMock(return_value=MANY_FAVS)), \
             patch("bot.handlers.metro._search_and_show_stations",
                   new_callable=AsyncMock) as mock_metro:
            await fav_mod.fav_quick_command(update, ctx)

        mock_metro.assert_awaited_once()
        assert mock_metro.await_args[0][1] == "Trindade"

    @pytest.mark.asyncio
    async def test_third_index_reaches_the_train_favorite(self):
        update = _message_update()
        ctx = _context(args=["3"])

        with patch.object(fav_mod, "get_favorites", new=AsyncMock(return_value=MANY_FAVS)), \
             patch("bot.handlers.trains._search_and_show_stations",
                   new_callable=AsyncMock) as mock_train:
            await fav_mod.fav_quick_command(update, ctx)

        mock_train.assert_awaited_once()
        assert mock_train.await_args[0][1] == "Porto-Campanha"

    @pytest.mark.asyncio
    async def test_name_argument_opens_that_favorite(self):
        update = _message_update()
        ctx = _context(args=["trindade"])

        with patch.object(fav_mod, "get_favorites", new=AsyncMock(return_value=MANY_FAVS)), \
             patch("bot.handlers.metro._search_and_show_stations",
                   new_callable=AsyncMock) as mock_metro:
            await fav_mod.fav_quick_command(update, ctx)

        mock_metro.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_multi_word_name_argument(self):
        update = _message_update()
        ctx = _context(args=["Porto-Campanha"])

        with patch.object(fav_mod, "get_favorites", new=AsyncMock(return_value=MANY_FAVS)), \
             patch("bot.handlers.trains._search_and_show_stations",
                   new_callable=AsyncMock) as mock_train:
            await fav_mod.fav_quick_command(update, ctx)

        mock_train.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_code_argument(self):
        update = _message_update()
        ctx = _context(args=["bcm2"])

        with patch.object(fav_mod, "get_favorites", new=AsyncMock(return_value=MANY_FAVS)), \
             patch("bot.handlers.bus._send_stop_realtime",
                   new_callable=AsyncMock) as mock_bus:
            await fav_mod.fav_quick_command(update, ctx)

        mock_bus.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unresolved_argument_shows_usage_hint(self):
        update = _message_update()
        ctx = _context(args=["99"])

        with patch.object(fav_mod, "get_favorites", new=AsyncMock(return_value=MANY_FAVS)), \
             patch("bot.handlers.bus._send_stop_realtime",
                   new_callable=AsyncMock) as mock_bus:
            await fav_mod.fav_quick_command(update, ctx)

        mock_bus.assert_not_awaited()
        text = update.message.reply_text.await_args[0][0]
        assert "/fav" in text
        # Still gives a way out: the tappable list.
        assert update.message.reply_text.await_args.kwargs["reply_markup"] is not None

    @pytest.mark.asyncio
    async def test_unknown_name_shows_usage_hint(self):
        update = _message_update()
        ctx = _context(args=["definitelynotthere"])

        with patch.object(fav_mod, "get_favorites", new=AsyncMock(return_value=MANY_FAVS)):
            await fav_mod.fav_quick_command(update, ctx)

        assert "/fav" in update.message.reply_text.await_args[0][0]

    @pytest.mark.asyncio
    async def test_no_favorites_message(self):
        update = _message_update()
        ctx = _context()

        with patch.object(fav_mod, "get_favorites", new=AsyncMock(return_value=[])):
            await fav_mod.fav_quick_command(update, ctx)

        update.message.reply_text.assert_awaited_once()

    def test_resolve_by_index_bounds(self):
        assert fav_mod._resolve_favorite(MANY_FAVS, "1") is MANY_FAVS[0]
        assert fav_mod._resolve_favorite(MANY_FAVS, "3") is MANY_FAVS[2]
        assert fav_mod._resolve_favorite(MANY_FAVS, "0") is None
        assert fav_mod._resolve_favorite(MANY_FAVS, "4") is None
        assert fav_mod._resolve_favorite(MANY_FAVS, "") is None

    def test_resolve_prefers_exact_name(self):
        favs = [{"type": "metro", "id": "Trindade Norte", "name": "Trindade Norte"},
                {"type": "metro", "id": "Trindade", "name": "Trindade"}]
        assert fav_mod._resolve_favorite(favs, "Trindade")["id"] == "Trindade"

    def test_favorites_listing_is_escaped_and_numbered(self):
        text = fav_mod._favorites_listing(MANY_FAVS)
        assert "1\\." in text and "3\\." in text
        assert "Porto\\-Campanha" in text


# ===================================================================
# 4. /start actually sends the persistent reply keyboard
# ===================================================================

class TestStartReplyKeyboard:

    async def _run_start(self, ctx, favs=None, args=None):
        from bot.handlers.start import start_command
        update = _message_update()
        ctx.args = args or []
        with patch("bot.handlers.start.get_favorites",
                   new=AsyncMock(return_value=favs or [])), \
             patch("bot.database.is_user_onboarded", new=AsyncMock(return_value=False)):
            await start_command(update, ctx)
        return update

    @pytest.mark.asyncio
    async def test_reply_keyboard_is_sent(self):
        ctx = _context()
        update = await self._run_start(ctx)

        markups = [c.kwargs.get("reply_markup")
                   for c in update.message.reply_text.await_args_list]
        reply_kbs = [m for m in markups if isinstance(m, ReplyKeyboardMarkup)]
        assert reply_kbs, "/start must send the persistent reply keyboard"

    @pytest.mark.asyncio
    async def test_reply_keyboard_has_location_button(self):
        ctx = _context()
        update = await self._run_start(ctx)

        markups = [c.kwargs.get("reply_markup")
                   for c in update.message.reply_text.await_args_list]
        kb = next(m for m in markups if isinstance(m, ReplyKeyboardMarkup))
        buttons = [b for row in kb.keyboard for b in row]
        assert any(getattr(b, "request_location", False) for b in buttons)

    @pytest.mark.asyncio
    async def test_reply_keyboard_labels_match_main_text_router(self):
        """bot/main.py matches these exact strings to route the buttons."""
        import inspect
        import bot.main as main_mod
        from bot.handlers.start import _reply_keyboard

        source = inspect.getsource(main_mod)
        for lang in ("pt", "en"):
            for row in _reply_keyboard(lang).keyboard:
                for button in row:
                    assert f'"{button.text}"' in source, button.text

    @pytest.mark.asyncio
    async def test_inline_menu_still_sent(self):
        from telegram import InlineKeyboardMarkup
        ctx = _context()
        update = await self._run_start(ctx)

        markups = [c.kwargs.get("reply_markup")
                   for c in update.message.reply_text.await_args_list]
        assert any(isinstance(m, InlineKeyboardMarkup) for m in markups)

    @pytest.mark.asyncio
    async def test_reply_keyboard_sent_only_once_per_session(self):
        ctx = _context()
        await self._run_start(ctx)
        assert ctx.user_data.get("reply_keyboard_sent") is True

        update = await self._run_start(ctx)
        markups = [c.kwargs.get("reply_markup")
                   for c in update.message.reply_text.await_args_list]
        assert not [m for m in markups if isinstance(m, ReplyKeyboardMarkup)]

    @pytest.mark.asyncio
    async def test_reply_keyboard_sent_before_deep_link_handling(self):
        ctx = _context()
        with patch("bot.handlers.bus._send_stop_realtime", new_callable=AsyncMock):
            update = await self._run_start(ctx, args=["stop_BCM2"])

        markups = [c.kwargs.get("reply_markup")
                   for c in update.message.reply_text.await_args_list]
        assert [m for m in markups if isinstance(m, ReplyKeyboardMarkup)]

    @pytest.mark.asyncio
    async def test_welcome_list_uses_the_right_emoji_per_type(self):
        ctx = _context()
        favs = [
            {"type": "bus", "id": "BCM2", "name": "Boavista"},
            {"type": "metro", "id": "Trindade", "name": "Trindade"},
            {"type": "metrobus", "id": "Boavista", "name": "Boavista"},
            {"type": "train", "id": "Porto-Campanha", "name": "Porto-Campanha"},
        ]
        update = await self._run_start(ctx, favs=favs)

        texts = [c.args[0] for c in update.message.reply_text.await_args_list]
        body = "\n".join(texts)
        assert "🚌" in body
        assert "🚇" in body
        assert "\U0001f68d" in body   # MetroBus
        assert "\U0001f686" in body   # CP train
        # The train line must not be labelled with the metro emoji.
        train_line = next(l for l in body.splitlines() if "Campanha" in l)
        assert "🚇" not in train_line
