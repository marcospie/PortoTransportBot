"""Tests for the shared safe-edit helper and every refresh path that uses it.

Telegram answers ``BadRequest("Message is not modified")`` whenever an edit
would leave the message exactly as it is -- which is what happens every single
time a user taps a refresh button before the data changed. Before this helper
existed, that bubbled up to the global error handler and the user was told
"Erro interno" for doing nothing wrong.
"""

import inspect

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest

from bot.utils.telegram import (
    CALLBACK_DATA_MAX_BYTES,
    callback_data_ok,
    mark_active_button,
    pop_active_flag,
    rows_of,
    safe_callback_button,
    safe_edit_message,
    safe_edit_reply_markup,
    t_safe,
    truncate_label,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_context(user_data=None):
    ctx = MagicMock()
    ctx.user_data = user_data if user_data is not None else {}
    ctx.args = []
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()
    ctx.bot.send_location = AsyncMock()
    return ctx


def _make_update(callback_data="", lang="pt", user_id=123, chat_id=456):
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_user.language_code = lang
    update.effective_chat.id = chat_id

    msg = MagicMock()
    msg.text = ""
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
    query.data = callback_data
    update.callback_query = query
    return update


def _not_modified_query():
    query = MagicMock()
    query.edit_message_text = AsyncMock(
        side_effect=BadRequest("Message is not modified"))
    query.edit_message_reply_markup = AsyncMock(
        side_effect=BadRequest("Message is not modified"))
    return query


# ===================================================================
# safe_edit_message
# ===================================================================

class TestSafeEditMessage:

    @pytest.mark.asyncio
    async def test_returns_true_on_successful_edit(self):
        query = MagicMock()
        query.edit_message_text = AsyncMock()
        assert await safe_edit_message(query, "hello") is True

    @pytest.mark.asyncio
    async def test_passes_text_positionally_and_markup_as_kwarg(self):
        query = MagicMock()
        query.edit_message_text = AsyncMock()
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("x", callback_data="y")]])

        await safe_edit_message(query, "body", reply_markup=kb)

        args, kwargs = query.edit_message_text.call_args
        assert args[0] == "body"
        assert kwargs["reply_markup"] is kb
        assert kwargs["parse_mode"] == "MarkdownV2"

    @pytest.mark.asyncio
    async def test_tolerates_message_not_modified(self):
        query = _not_modified_query()
        assert await safe_edit_message(query, "same text") is False

    @pytest.mark.asyncio
    async def test_tolerates_message_not_modified_any_case(self):
        """Telegram's wording has varied; match case-insensitively."""
        query = MagicMock()
        query.edit_message_text = AsyncMock(side_effect=BadRequest(
            "Bad Request: message is not modified: specified new message "
            "content and reply markup are exactly the same"))
        assert await safe_edit_message(query, "same") is False

    @pytest.mark.asyncio
    async def test_reraises_other_bad_requests(self):
        query = MagicMock()
        query.edit_message_text = AsyncMock(
            side_effect=BadRequest("Can't parse entities"))
        with pytest.raises(BadRequest):
            await safe_edit_message(query, "boom")

    @pytest.mark.asyncio
    async def test_reraises_unrelated_exceptions(self):
        query = MagicMock()
        query.edit_message_text = AsyncMock(side_effect=RuntimeError("network"))
        with pytest.raises(RuntimeError):
            await safe_edit_message(query, "boom")

    @pytest.mark.asyncio
    async def test_custom_parse_mode_is_forwarded(self):
        query = MagicMock()
        query.edit_message_text = AsyncMock()
        await safe_edit_message(query, "body", parse_mode="HTML")
        assert query.edit_message_text.call_args.kwargs["parse_mode"] == "HTML"


class TestSafeEditReplyMarkup:

    @pytest.mark.asyncio
    async def test_tolerates_not_modified(self):
        query = _not_modified_query()
        assert await safe_edit_reply_markup(query, None) is False

    @pytest.mark.asyncio
    async def test_returns_true_on_success(self):
        query = MagicMock()
        query.edit_message_reply_markup = AsyncMock()
        assert await safe_edit_reply_markup(query, None) is True

    @pytest.mark.asyncio
    async def test_reraises_other_errors(self):
        query = MagicMock()
        query.edit_message_reply_markup = AsyncMock(
            side_effect=BadRequest("Message to edit not found"))
        with pytest.raises(BadRequest):
            await safe_edit_reply_markup(query, None)


# ===================================================================
# Every refresh path in the handlers we own
# ===================================================================

class TestHandlersUseSafeEdit:
    """No handler we own may call edit_message_text directly any more."""

    OWNED = [
        "bot/handlers/weather.py",
        "bot/handlers/alerts.py",
        "bot/handlers/events.py",
        "bot/handlers/accessibility.py",
        "bot/handlers/metro.py",
        "bot/handlers/bus.py",
        "bot/handlers/metrobus.py",
    ]

    @pytest.mark.parametrize("path", OWNED)
    def test_no_direct_edit_message_text(self, path):
        source = open(path, encoding="utf-8").read()
        assert "query.edit_message_text(" not in source, (
            f"{path} still edits messages directly; use safe_edit_message()"
        )

    @pytest.mark.parametrize("path", OWNED)
    def test_no_ad_hoc_not_modified_handling(self, path):
        """The inline try/except copies are gone — one helper owns this rule."""
        source = open(path, encoding="utf-8").read()
        assert 'if "Message is not modified" in str' not in source, (
            f"{path} still has an ad-hoc not-modified check"
        )

    @pytest.mark.parametrize("path", OWNED)
    def test_imports_the_shared_helper(self, path):
        source = open(path, encoding="utf-8").read()
        assert "safe_edit_message" in source


class TestRefreshPathsSurviveNotModified:
    """End-to-end: a second tap on refresh must not raise for any feature."""

    @pytest.mark.asyncio
    async def test_weather(self):
        from bot.handlers.weather import weather_menu_callback
        update = _make_update()
        update.callback_query.edit_message_text = AsyncMock(
            side_effect=BadRequest("Message is not modified"))
        await weather_menu_callback(update, _make_context())

    @pytest.mark.asyncio
    async def test_alerts_menu(self):
        from bot.handlers.alerts import alerts_menu_callback
        update = _make_update()
        update.callback_query.edit_message_text = AsyncMock(
            side_effect=BadRequest("Message is not modified"))
        with patch("bot.handlers.alerts.get_active_alerts",
                   new_callable=AsyncMock, return_value=[]):
            await alerts_menu_callback(update, _make_context())

    @pytest.mark.asyncio
    async def test_alerts_filter(self):
        from bot.handlers.alerts import alerts_filter_callback
        update = _make_update(callback_data="alerts:filter:delay")
        update.callback_query.edit_message_text = AsyncMock(
            side_effect=BadRequest("Message is not modified"))
        with patch("bot.handlers.alerts.get_active_alerts",
                   new_callable=AsyncMock, return_value=[]):
            await alerts_filter_callback(update, _make_context())

    @pytest.mark.asyncio
    async def test_events_menu(self):
        from bot.handlers.events import events_menu_callback
        update = _make_update()
        update.callback_query.edit_message_text = AsyncMock(
            side_effect=BadRequest("Message is not modified"))
        await events_menu_callback(update, _make_context())

    @pytest.mark.asyncio
    async def test_events_categories(self):
        from bot.handlers.events import events_categories_callback
        update = _make_update(callback_data="events:categories")
        update.callback_query.edit_message_text = AsyncMock(
            side_effect=BadRequest("Message is not modified"))
        await events_categories_callback(update, _make_context())

    @pytest.mark.asyncio
    async def test_accessibility_menu(self):
        from bot.handlers.accessibility import accessibility_menu_callback
        update = _make_update()
        update.callback_query.edit_message_text = AsyncMock(
            side_effect=BadRequest("Message is not modified"))
        await accessibility_menu_callback(update, _make_context())

    @pytest.mark.asyncio
    async def test_accessibility_station(self):
        from bot.handlers.accessibility import accessibility_station_callback
        update = _make_update(callback_data="access:station:Trindade")
        update.callback_query.edit_message_text = AsyncMock(
            side_effect=BadRequest("Message is not modified"))
        await accessibility_station_callback(update, _make_context())

    @pytest.mark.asyncio
    async def test_accessibility_elevators(self):
        from bot.handlers.accessibility import accessibility_elevators_callback
        update = _make_update(callback_data="access:elevators")
        update.callback_query.edit_message_text = AsyncMock(
            side_effect=BadRequest("Message is not modified"))
        await accessibility_elevators_callback(update, _make_context())

    @pytest.mark.asyncio
    async def test_metrobus_line(self):
        from bot.handlers.metrobus import metrobus_line_callback
        update = _make_update(callback_data="metrobus:line:1")
        update.callback_query.edit_message_text = AsyncMock(
            side_effect=BadRequest("Message is not modified"))
        await metrobus_line_callback(update, _make_context())
        # The generic error path must NOT have been taken (it would be a
        # second call to edit_message_text with an error string).
        assert update.callback_query.edit_message_text.call_count == 1

    @pytest.mark.asyncio
    async def test_bus_route(self):
        from bot.handlers.bus import bus_route_callback
        update = _make_update(callback_data="bus:route:200")
        update.callback_query.edit_message_text = AsyncMock(
            side_effect=BadRequest("Message is not modified"))
        with patch("bot.handlers.bus.stcp.get_route_stops",
                   new_callable=AsyncMock, return_value=[
                       {"stop_id": "BCM1", "name": "Boavista", "code": "BCM1", "seq": 1},
                       {"stop_id": "BLH1", "name": "Bolhão", "code": "BLH1", "seq": 2},
                   ]):
            await bus_route_callback(update, _make_context())
        assert update.callback_query.edit_message_text.call_count == 1

    @pytest.mark.asyncio
    async def test_metro_line(self):
        from bot.handlers.metro import metro_line_callback
        update = _make_update(callback_data="metro:line:A")
        update.callback_query.edit_message_text = AsyncMock(
            side_effect=BadRequest("Message is not modified"))
        await metro_line_callback(update, _make_context())
        assert update.callback_query.edit_message_text.call_count == 1


# ===================================================================
# callback_data byte limit
# ===================================================================

class TestCallbackDataLimit:

    def test_limit_is_64_bytes(self):
        assert CALLBACK_DATA_MAX_BYTES == 64

    def test_ascii_within_limit(self):
        assert callback_data_ok("bus:stop:BCM2")

    def test_multibyte_accents_count_double(self):
        # 32 "ã" characters are 64 bytes on their own.
        assert callback_data_ok("ã" * 32)
        assert not callback_data_ok("ã" * 33)

    def test_over_limit_button_is_dropped(self):
        assert safe_callback_button("x", "a" * 65) is None

    def test_within_limit_button_is_built(self):
        button = safe_callback_button("x", "a" * 64)
        assert button is not None
        assert button.callback_data == "a" * 64

    def test_longest_accented_metro_station_fits(self):
        from bot.services.metro import STATIONS
        for name in STATIONS:
            data = f"metro:station:{name}"
            assert callback_data_ok(data), (
                f"{name!r} produces {len(data.encode('utf-8'))} bytes")

    def test_longest_accented_metrobus_stop_fits(self):
        from bot.services.metrobus import STOPS
        for name in STOPS:
            for prefix in ("metrobus:stop:", "metrobus:stop_lines:",
                           "metrobus:loc:"):
                data = f"{prefix}{name}"
                assert callback_data_ok(data), (
                    f"{name!r} produces {len(data.encode('utf-8'))} bytes "
                    f"with prefix {prefix!r}")

    def test_accessibility_station_callbacks_fit(self):
        from bot.services.accessibility import ACCESSIBILITY
        for name in ACCESSIBILITY:
            assert callback_data_ok(f"access:station:{name}")

    def test_metrobus_line_keyboard_respects_limit(self):
        from bot.handlers.metrobus import _line_stops_keyboard
        from bot.services import metrobus
        from bot.services.metrobus import METROBUS_LINES

        for code, data in METROBUS_LINES.items():
            kb = _line_stops_keyboard(metrobus.get_line_stops(code), data, "pt")
            for row in kb.inline_keyboard:
                for button in row:
                    assert callback_data_ok(button.callback_data)

    def test_bus_route_keyboard_respects_limit_with_long_names(self):
        from bot.handlers.bus import _bus_route_keyboard

        stops = [
            {"stop_id": f"S{i}", "name": "Praça de Mouzinho de Albuquerque "
                                         "(Rotunda da Boavista) — Sentido Oeste",
             "code": f"S{i}", "seq": i}
            for i in range(30)
        ]
        kb = _bus_route_keyboard("ZC", 1, 2, stops, "pt")
        for row in kb.inline_keyboard:
            for button in row:
                if button.callback_data:
                    assert callback_data_ok(button.callback_data)


# ===================================================================
# Small helpers
# ===================================================================

class TestSmallHelpers:

    def test_truncate_label_keeps_short_text(self):
        assert truncate_label("Bolhão", 30) == "Bolhão"

    def test_truncate_label_shortens_long_text(self):
        out = truncate_label("A" * 50, 10)
        assert len(out) <= 10
        assert out.endswith("…")

    def test_rows_of_chunks(self):
        assert rows_of([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]

    def test_rows_of_empty(self):
        assert rows_of([], 2) == []

    def test_t_safe_prefers_real_translation(self):
        assert t_safe("kb_back", "pt") != "kb_back"

    def test_t_safe_falls_back_to_pt(self):
        assert t_safe("definitely_missing_key_xyz", "pt",
                      pt="Portugues", en="English") == "Portugues"

    def test_t_safe_falls_back_to_en_for_other_langs(self):
        assert t_safe("definitely_missing_key_xyz", "en",
                      pt="Portugues", en="English") == "English"

    def test_t_safe_never_returns_a_raw_key(self):
        for lang in ("pt", "en"):
            assert t_safe("definitely_missing_key_xyz", lang,
                          pt="P", en="E") != "definitely_missing_key_xyz"

    def test_mark_active_button_marks_only_the_match(self):
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("All", callback_data="alerts:filter:all"),
            InlineKeyboardButton("Delays", callback_data="alerts:filter:delay"),
        ]])
        marked = mark_active_button(kb, "alerts:filter:delay")
        labels = [b.text for row in marked.inline_keyboard for b in row]
        assert labels == ["All", "• Delays •"]

    def test_mark_active_button_preserves_callback_data(self):
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("All", callback_data="alerts:filter:all")]])
        marked = mark_active_button(kb, "alerts:filter:all")
        assert marked.inline_keyboard[0][0].callback_data == "alerts:filter:all"

    def test_mark_active_button_ignores_non_callback_buttons(self):
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("Search", switch_inline_query_current_chat="x")]])
        marked = mark_active_button(kb, "alerts:filter:all")
        assert marked.inline_keyboard[0][0].text == "Search"

    def test_pop_active_flag_true_boolean(self):
        data = {"awaiting_x": True}
        assert pop_active_flag(data, "awaiting_x") is True
        assert "awaiting_x" not in data

    def test_pop_active_flag_recent_datetime(self):
        from datetime import datetime
        data = {"awaiting_x": datetime.now()}
        assert pop_active_flag(data, "awaiting_x") is True

    def test_pop_active_flag_expired_datetime(self):
        from datetime import datetime, timedelta
        data = {"awaiting_x": datetime.now() - timedelta(minutes=10)}
        assert pop_active_flag(data, "awaiting_x") is False
        assert "awaiting_x" not in data

    def test_pop_active_flag_missing(self):
        assert pop_active_flag({}, "awaiting_x") is False


# ===================================================================
# Signatures main.py depends on must stay intact
# ===================================================================

class TestPublicSignaturesUnchanged:

    def test_bus_text_input_signature(self):
        from bot.handlers.bus import handle_bus_text_input
        params = list(inspect.signature(handle_bus_text_input).parameters)
        assert params == ["update", "context"]

    def test_metro_text_input_signature(self):
        from bot.handlers.metro import handle_metro_text_input
        params = list(inspect.signature(handle_metro_text_input).parameters)
        assert params == ["update", "context"]

    def test_accessibility_text_input_signature(self):
        from bot.handlers.accessibility import handle_accessibility_text_input
        params = list(inspect.signature(handle_accessibility_text_input).parameters)
        assert params == ["update", "context"]

    def test_awaiting_flag_constants_still_exported(self):
        from bot.handlers.bus import AWAITING_BUS_FIND
        from bot.handlers.metro import AWAITING_METRO_SEARCH
        assert AWAITING_BUS_FIND == "awaiting_bus_find"
        assert AWAITING_METRO_SEARCH == "awaiting_metro_search"
