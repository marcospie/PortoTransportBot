"""Tests for the shared Telegram helpers and the handlers built on them.

Covers:

* ``safe_edit_message`` -- Telegram answers
  ``BadRequest("Message is not modified")`` whenever an edit would leave the
  message exactly as it is, which is what happens every single time a user taps
  refresh before the data changed. That used to reach the global error handler
  and tell the user "Erro interno" for doing nothing wrong.
* the 64-byte ``callback_data`` limit (accents cost two bytes each),
* the alerts filter telling the truth about *which* alerts are missing,
* the bus route direction toggle and tappable stops,
* the accessibility search prompt being escapable and its "not found" offering
  suggestions.
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


# ===================================================================
# Alert filters must not lie about what is missing
# ===================================================================

class TestAlertFilterHonesty:

    ALERTS = [
        {"id": "d1", "type": "disruption", "title": "Linha A interrompida",
         "description": "d", "affected_lines": ["A"], "severity": "high"},
        {"id": "i1", "type": "info", "title": "Aviso", "description": "d",
         "affected_lines": [], "severity": "low"},
    ]

    def test_no_filter_and_no_alerts_says_all_normal(self):
        from bot.handlers.alerts import format_alerts_message
        from bot.utils.i18n import t
        assert format_alerts_message([], "pt") == t("no_alerts", "pt")

    def test_backward_compatible_two_argument_call(self):
        from bot.handlers.alerts import format_alerts_message
        assert "Sem alertas" in format_alerts_message([], "pt")
        assert "No alerts" in format_alerts_message([], "en")

    def test_empty_filtered_result_does_not_claim_all_normal(self):
        """The bug: filtering to "atrasos" said "tudo a funcionar normalmente"."""
        from bot.handlers.alerts import format_alerts_message
        from bot.utils.i18n import t

        msg = format_alerts_message([], "pt", filter_type="delay")
        assert msg != t("no_alerts", "pt")
        assert "normalmente" not in msg
        assert msg == t("no_alerts_of_type", "pt")

    def test_empty_filtered_result_en(self):
        from bot.handlers.alerts import format_alerts_message
        from bot.utils.i18n import t
        msg = format_alerts_message([], "en", filter_type="disruption")
        assert msg != t("no_alerts", "en")

    def test_all_filter_still_uses_the_plain_no_alerts_message(self):
        from bot.handlers.alerts import format_alerts_message
        from bot.utils.i18n import t
        assert format_alerts_message([], "pt", filter_type="all") == \
               t("no_alerts", "pt")

    def test_unavailable_source_is_not_reported_as_normal(self):
        from bot.handlers.alerts import format_alerts_message
        from bot.utils.i18n import t
        msg = format_alerts_message([], "pt", source_available=False)
        assert msg == t("alerts_source_unavailable", "pt")
        assert msg != t("no_alerts", "pt")

    @pytest.mark.asyncio
    async def test_filter_with_no_matches_shows_the_type_specific_message(self):
        from bot.handlers.alerts import alerts_filter_callback
        from bot.utils.i18n import t

        update = _make_update(callback_data="alerts:filter:delay")
        with patch("bot.handlers.alerts.get_active_alerts",
                   new_callable=AsyncMock, return_value=self.ALERTS):
            await alerts_filter_callback(update, _make_context())

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert text == t("no_alerts_of_type", "pt")

    @pytest.mark.asyncio
    async def test_active_filter_is_marked_in_the_keyboard(self):
        from bot.handlers.alerts import alerts_filter_callback

        update = _make_update(callback_data="alerts:filter:delay")
        with patch("bot.handlers.alerts.get_active_alerts",
                   new_callable=AsyncMock, return_value=self.ALERTS):
            await alerts_filter_callback(update, _make_context())

        kb = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        marked = [b.text for row in kb.inline_keyboard for b in row
                  if b.text.startswith("•")]
        assert len(marked) == 1
        active = [b for row in kb.inline_keyboard for b in row
                  if b.text.startswith("•")][0]
        assert active.callback_data == "alerts:filter:delay"

    @pytest.mark.asyncio
    async def test_menu_view_marks_the_all_filter(self):
        from bot.handlers.alerts import alerts_menu_callback

        update = _make_update()
        with patch("bot.handlers.alerts.get_active_alerts",
                   new_callable=AsyncMock, return_value=self.ALERTS):
            await alerts_menu_callback(update, _make_context())

        kb = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        active = [b for row in kb.inline_keyboard for b in row
                  if b.text.startswith("•")]
        assert len(active) == 1
        assert active[0].callback_data == "alerts:filter:all"

    @pytest.mark.asyncio
    async def test_filter_keyboard_keeps_every_original_button(self):
        from bot.handlers.alerts import alerts_filter_callback
        from bot.keyboards.inline import alerts_keyboard

        update = _make_update(callback_data="alerts:filter:engineering")
        with patch("bot.handlers.alerts.get_active_alerts",
                   new_callable=AsyncMock, return_value=self.ALERTS):
            await alerts_filter_callback(update, _make_context())

        kb = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        original = [b.callback_data for row in alerts_keyboard("pt").inline_keyboard
                    for b in row]
        actual = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert actual == original

    @pytest.mark.asyncio
    async def test_source_unavailable_result_is_surfaced(self):
        """An AlertsResult flagged source_available=False must not read "normal"."""
        from bot.handlers.alerts import alerts_menu_callback
        from bot.utils.i18n import t

        class _Result(list):
            source_available = False

        update = _make_update()
        with patch("bot.handlers.alerts.get_active_alerts",
                   new_callable=AsyncMock, return_value=_Result()):
            await alerts_menu_callback(update, _make_context())

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert text == t("alerts_source_unavailable", "pt")

    @pytest.mark.asyncio
    async def test_dict_shaped_result_is_accepted(self):
        from bot.handlers.alerts import alerts_menu_callback

        update = _make_update()
        with patch("bot.handlers.alerts.get_active_alerts",
                   new_callable=AsyncMock,
                   return_value={"alerts": self.ALERTS, "source_available": True}):
            await alerts_menu_callback(update, _make_context())

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Linha A interrompida" in text

    @pytest.mark.asyncio
    async def test_service_crash_degrades_to_could_not_check(self):
        from bot.handlers.alerts import alerts_menu_callback
        from bot.utils.i18n import t

        update = _make_update()
        with patch("bot.handlers.alerts.get_active_alerts",
                   new_callable=AsyncMock, side_effect=RuntimeError("boom")):
            await alerts_menu_callback(update, _make_context())

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert text == t("alerts_source_unavailable", "pt")


# ===================================================================
# Bus route: direction toggle and tappable stops
# ===================================================================

_ROUTE_STOPS = {
    0: [{"stop_id": f"OUT{i}", "name": f"Paragem Ida {i}", "code": f"OUT{i}",
         "seq": i} for i in range(20)],
    1: [{"stop_id": f"RET{i}", "name": f"Paragem Volta {i}", "code": f"RET{i}",
         "seq": i} for i in range(20)],
}


def _patch_route_stops():
    async def _get(route_id, direction=0):
        return _ROUTE_STOPS[direction]
    return patch("bot.handlers.bus.stcp.get_route_stops", side_effect=_get)


class TestBusRouteDirection:

    def test_callback_parsing_defaults(self):
        from bot.handlers.bus import _parse_route_callback
        assert _parse_route_callback("bus:route:200") == ("200", 0, 0)

    def test_callback_parsing_with_direction_and_page(self):
        from bot.handlers.bus import _parse_route_callback
        assert _parse_route_callback("bus:route:200:1:3") == ("200", 1, 3)

    def test_callback_parsing_clamps_direction(self):
        from bot.handlers.bus import _parse_route_callback
        assert _parse_route_callback("bus:route:200:7:0")[1] == 1

    def test_callback_parsing_survives_garbage(self):
        from bot.handlers.bus import _parse_route_callback
        assert _parse_route_callback("bus:route:200:x:y") == ("200", 0, 0)

    def test_registered_pattern_still_matches_new_callback_data(self):
        """bot/main.py registers ^bus:route:.+$ — do not break it."""
        import re
        assert re.match(r"^bus:route:.+$", "bus:route:200:1:2")

    @pytest.mark.asyncio
    async def test_default_direction_is_outbound(self):
        from bot.handlers.bus import bus_route_callback
        update = _make_update(callback_data="bus:route:200")
        with _patch_route_stops():
            await bus_route_callback(update, _make_context())
        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Paragem Ida 0" in text

    @pytest.mark.asyncio
    async def test_return_direction_shows_the_other_stop_sequence(self):
        """The bug: direction was hardcoded to 0, so this was unreachable."""
        from bot.handlers.bus import bus_route_callback
        update = _make_update(callback_data="bus:route:200:1:0")
        with _patch_route_stops():
            await bus_route_callback(update, _make_context())
        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Paragem Volta 0" in text
        assert "Paragem Ida 0" not in text

    @pytest.mark.asyncio
    async def test_toggle_button_points_at_the_other_direction(self):
        from bot.handlers.bus import bus_route_callback
        update = _make_update(callback_data="bus:route:200")
        with _patch_route_stops():
            await bus_route_callback(update, _make_context())
        kb = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        data = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert "bus:route:200:1:0" in data

    @pytest.mark.asyncio
    async def test_toggle_from_return_goes_back_to_outbound(self):
        from bot.handlers.bus import bus_route_callback
        update = _make_update(callback_data="bus:route:200:1:0")
        with _patch_route_stops():
            await bus_route_callback(update, _make_context())
        kb = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        data = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert "bus:route:200:0:0" in data

    @pytest.mark.asyncio
    async def test_stops_are_tappable_buttons(self):
        from bot.handlers.bus import bus_route_callback
        update = _make_update(callback_data="bus:route:200")
        with _patch_route_stops():
            await bus_route_callback(update, _make_context())
        kb = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        data = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert "bus:stop:OUT0" in data

    @pytest.mark.asyncio
    async def test_paging_reaches_later_stops(self):
        from bot.handlers.bus import bus_route_callback
        update = _make_update(callback_data="bus:route:200:0:2")
        with _patch_route_stops():
            await bus_route_callback(update, _make_context())
        kb = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        data = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert "bus:stop:OUT16" in data
        assert "bus:route:200:0:1" in data  # previous page

    @pytest.mark.asyncio
    async def test_first_page_has_no_previous_button(self):
        from bot.handlers.bus import bus_route_callback
        update = _make_update(callback_data="bus:route:200:0:0")
        with _patch_route_stops():
            await bus_route_callback(update, _make_context())
        kb = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        data = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert "bus:route:200:0:-1" not in data

    @pytest.mark.asyncio
    async def test_back_from_a_stop_returns_to_the_route_view(self):
        from bot.handlers.bus import bus_route_callback
        ctx = _make_context()
        update = _make_update(callback_data="bus:route:200:1:1")
        with _patch_route_stops():
            await bus_route_callback(update, ctx)
        assert ctx.user_data["bus_back"] == "bus:route:200:1:1"

    @pytest.mark.asyncio
    async def test_direction_without_stops_says_so_and_keeps_the_toggle(self):
        from bot.handlers.bus import bus_route_callback

        async def _get(route_id, direction=0):
            return [] if direction else _ROUTE_STOPS[0]

        update = _make_update(callback_data="bus:route:ZC:1:0")
        with patch("bot.handlers.bus.stcp.get_route_stops", side_effect=_get):
            await bus_route_callback(update, _make_context())

        kb = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        data = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert "bus:route:ZC:0:0" in data

    @pytest.mark.asyncio
    async def test_unloadable_route_still_shows_an_error(self):
        from bot.handlers.bus import bus_route_callback

        update = _make_update(callback_data="bus:route:999")
        with patch("bot.handlers.bus.stcp.get_route_stops",
                   new_callable=AsyncMock, return_value=[]):
            await bus_route_callback(update, _make_context())
        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "999" in text


class TestBusStopInfoNoRawCoordinates:

    @pytest.mark.asyncio
    async def test_coordinates_are_not_dumped_on_the_user(self):
        from bot.handlers.bus import bus_stop_info_callback

        update = _make_update(callback_data="bus:info:BCM2")
        with patch("bot.handlers.bus.stcp.get_stop_info",
                   new_callable=AsyncMock, return_value={
                       "name": "Boavista", "zone": "PRT1",
                       "lat": 41.1588, "lon": -8.6310, "routes": [],
                   }), \
             patch("bot.handlers.bus.is_favorite",
                   new_callable=AsyncMock, return_value=False):
            await bus_stop_info_callback(update, _make_context())

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Coordenadas" not in text
        assert "41.1588" not in text
        assert "-8.6310" not in text
        assert "Boavista" in text


# ===================================================================
# Metrobus: every stop on a line must be reachable
# ===================================================================

class TestMetrobusAllStopsReachable:

    @pytest.mark.asyncio
    async def test_all_stops_get_a_button(self):
        from bot.handlers.metrobus import metrobus_line_callback
        from bot.services import metrobus

        update = _make_update(callback_data="metrobus:line:1")
        await metrobus_line_callback(update, _make_context())

        kb = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        data = [b.callback_data for row in kb.inline_keyboard for b in row]
        for stop in metrobus.get_line_stops("1"):
            assert f"metrobus:stop:{stop}" in data, f"{stop} unreachable"

    @pytest.mark.asyncio
    async def test_back_button_present(self):
        from bot.handlers.metrobus import metrobus_line_callback
        update = _make_update(callback_data="metrobus:line:1")
        await metrobus_line_callback(update, _make_context())
        kb = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        data = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert "metrobus:lines" in data

    def test_empty_stop_list_still_yields_a_usable_keyboard(self):
        from bot.handlers.metrobus import _line_stops_keyboard
        kb = _line_stops_keyboard([], {"emoji": "🚍"}, "pt")
        assert len(kb.inline_keyboard) == 1


# ===================================================================
# Accessibility: escapable prompt and helpful "not found"
# ===================================================================

class TestAccessibilitySearchPrompt:

    @pytest.mark.asyncio
    async def test_prompt_has_a_way_out(self):
        """The prompt used to have no keyboard at all — a dead end."""
        from bot.handlers.accessibility import accessibility_search_callback

        update = _make_update(callback_data="access:search")
        ctx = _make_context()
        await accessibility_search_callback(update, ctx)

        kb = update.callback_query.edit_message_text.call_args.kwargs["reply_markup"]
        assert kb is not None
        data = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert "menu:accessibility" in data
        assert ctx.user_data["accessibility_step"] == "search"


class TestAccessibilityNotFoundSuggestions:

    @pytest.mark.asyncio
    async def test_typo_search_offers_suggestions(self):
        from bot.handlers.accessibility import handle_accessibility_text_input

        update = _make_update()
        update.message.text = "Trindadex"
        ctx = _make_context({"accessibility_step": "search"})

        assert await handle_accessibility_text_input(update, ctx) is True
        kb = update.message.reply_text.call_args.kwargs["reply_markup"]
        assert kb is not None

    @pytest.mark.asyncio
    async def test_suggestion_buttons_use_the_station_callback(self):
        from bot.handlers.accessibility import _not_found_view

        text, kb = _not_found_view("Trindadex", "pt")
        data = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert "access:station:Trindade" in data

    def test_at_most_three_suggestions(self):
        from bot.handlers.accessibility import _not_found_view
        _text, kb = _not_found_view("sao", "pt")
        stations = [b for row in kb.inline_keyboard for b in row
                    if b.callback_data.startswith("access:station:")]
        assert len(stations) <= 3

    def test_suggestion_callback_data_is_within_the_byte_limit(self):
        from bot.handlers.accessibility import _not_found_view
        for query in ("sao", "hospital", "estadio", "povoa", "senhor"):
            _text, kb = _not_found_view(query, "pt")
            for row in kb.inline_keyboard:
                for button in row:
                    assert callback_data_ok(button.callback_data)

    def test_not_found_text_still_names_what_was_typed(self):
        from bot.handlers.accessibility import _not_found_view
        text, _kb = _not_found_view("NonExistentXYZ", "pt")
        assert "NonExistentXYZ" in text

    def test_hopeless_query_falls_back_to_the_menu(self):
        from bot.handlers.accessibility import _not_found_view
        _text, kb = _not_found_view("zzzqqqxxx999", "pt")
        data = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert not any(d.startswith("access:station:") for d in data)
        assert "menu:accessibility" in data or "menu:main" in data


class TestAccessibilityHonestSourcing:

    def test_station_view_names_its_data_source(self):
        from bot.handlers.accessibility import _format_station_info
        from bot.services.accessibility import get_station_accessibility

        data = get_station_accessibility("Trindade")
        text = _format_station_info(data, "pt")
        source = data.get("data_source")
        if source:
            assert source.split()[0] in text

    def test_lift_status_is_not_presented_as_live_when_it_is_not(self):
        from bot.handlers.accessibility import _elevator_status_text

        text = _elevator_status_text(
            {"elevator_status": "operational", "live_status_available": False},
            "pt")
        assert text  # a real string, and specifically not a bare "OK"
        live = _elevator_status_text(
            {"elevator_status": "operational", "live_status_available": True},
            "pt")
        assert text != live

    def test_no_hardcoded_portuguese_ui_text_left_in_the_handler(self):
        """Portuguese may only appear as an explicit t_safe() fallback."""
        source = open("bot/handlers/accessibility.py", encoding="utf-8").read()
        assert '"Elevadores em manutenção:" if lang' not in source
        for line in source.split("\n"):
            if 'if lang == "pt" else' in line:
                # Only selecting a data key is allowed, never UI copy.
                assert "notes_" in line, line

    @pytest.mark.asyncio
    async def test_elevator_overview_explains_the_absence_of_live_data(self):
        from bot.handlers.accessibility import accessibility_elevators_callback

        update = _make_update(callback_data="access:elevators")
        with patch("bot.handlers.accessibility.search_accessible_features",
                   return_value=[]), \
             patch("bot.handlers.accessibility._live_status_available",
                   return_value=False):
            await accessibility_elevators_callback(update, _make_context())

        text = update.callback_query.edit_message_text.call_args[0][0]
        assert len(text) > 40  # not just "0 under maintenance"
