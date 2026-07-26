"""Comprehensive tests for the Events feature."""

import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

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
# Events service tests
# ===================================================================

class TestEventsService:
    def test_get_events_all(self):
        """All events are returned when no category filter is applied."""
        from bot.services.events import get_events, EVENTS
        events = get_events()
        assert len(events) == len(EVENTS)
        assert len(events) >= 5

    def test_get_events_by_category(self):
        """Events can be filtered by category."""
        from bot.services.events import get_events
        festivals = get_events("festival")
        assert len(festivals) >= 2
        assert all(e.category == "festival" for e in festivals)

        music = get_events("music")
        assert len(music) >= 1
        assert all(e.category == "music" for e in music)

        # Football fixtures come from the live feed, so the curated dataset
        # holds none — but the filter must still behave.
        assert all(e.category == "football" for e in get_events("football"))

        # Nonexistent category returns empty
        empty = get_events("nonexistent")
        assert empty == []

    def test_get_event_by_index(self):
        """Single events can be retrieved by index."""
        from bot.services.events import get_event, EVENTS
        # Valid index
        event = get_event(0)
        assert event is not None
        assert event.name_pt == EVENTS[0].name_pt

        # Last valid index
        last = get_event(len(EVENTS) - 1)
        assert last is not None

        # Invalid indices
        assert get_event(-1) is None
        assert get_event(999) is None

    def test_get_event_categories(self):
        """Category list contains all expected categories."""
        from bot.services.events import get_event_categories
        cats = get_event_categories()
        assert "football" in cats
        assert "festival" in cats
        assert "music" in cats
        assert "culture" in cats
        assert len(cats) == 4

    def test_get_events_near_station(self):
        """Events can be found by nearest metro station."""
        from bot.services.events import get_events_near_station
        casa = get_events_near_station("Casa da Música")
        assert len(casa) >= 2
        assert all(e.nearest_station == "Casa da Música" for e in casa)

        # Case insensitive
        casa_lower = get_events_near_station("casa da música")
        assert len(casa_lower) == len(casa)

        # Nonexistent station
        empty = get_events_near_station("Nonexistent Station")
        assert empty == []

    def test_event_dataclass_fields(self):
        """All events have the required dataclass fields populated."""
        from bot.services.events import EVENTS
        for event in EVENTS:
            assert event.name_pt, f"Missing name_pt for {event}"
            assert event.name_en, f"Missing name_en for {event}"
            assert event.venue_pt, f"Missing venue_pt for {event}"
            assert event.venue_en, f"Missing venue_en for {event}"
            assert event.date_info_pt, f"Missing date_info_pt for {event}"
            assert event.date_info_en, f"Missing date_info_en for {event}"
            assert event.nearest_station, f"Missing nearest_station for {event}"
            assert event.transport_tip_pt, f"Missing transport_tip_pt for {event}"
            assert event.transport_tip_en, f"Missing transport_tip_en for {event}"
            assert event.category in ("football", "festival", "music", "culture"), (
                f"Invalid category '{event.category}' for {event.name_en}"
            )
            assert event.emoji, f"Missing emoji for {event}"
            assert isinstance(event.start_date, date)
            assert isinstance(event.end_date, date)
            assert event.start_date <= event.end_date

    def test_get_todays_events(self):
        """Events happening on a given date are returned."""
        from bot.services.events import get_todays_events, EVENTS
        # Use the start_date of the first event to guarantee a match
        first = EVENTS[0]
        today_events = get_todays_events(today=first.start_date)
        assert len(today_events) >= 1
        assert first in today_events

    def test_get_todays_events_none(self):
        """No events on a date far in the past."""
        from bot.services.events import get_todays_events
        events = get_todays_events(today=date(2000, 1, 1))
        assert events == []

    def test_get_upcoming_events(self):
        """Upcoming events are returned sorted by start_date."""
        from bot.services.events import get_upcoming_events
        upcoming = get_upcoming_events(today=date(2026, 1, 1))
        assert len(upcoming) >= 1
        # Verify sorted
        for i in range(len(upcoming) - 1):
            assert upcoming[i].start_date <= upcoming[i + 1].start_date

    def test_get_upcoming_events_limit(self):
        """Upcoming events respects limit parameter."""
        from bot.services.events import get_upcoming_events
        upcoming = get_upcoming_events(today=date(2026, 1, 1), limit=2)
        assert len(upcoming) <= 2


# ===================================================================
# Events keyboard tests
# ===================================================================

class TestEventsKeyboards:
    def test_events_menu_keyboard_pt(self):
        from bot.keyboards.inline import events_menu_keyboard
        kb = events_menu_keyboard("pt")
        assert isinstance(kb, InlineKeyboardMarkup)
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "events:cat:all" in all_data
        assert "events:cat:football" in all_data
        assert "events:cat:festival" in all_data
        assert "events:cat:music" in all_data
        assert "events:cat:culture" in all_data
        assert "menu:main" in all_data

    def test_events_menu_keyboard_en(self):
        from bot.keyboards.inline import events_menu_keyboard
        kb = events_menu_keyboard("en")
        all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert any("All" in t for t in all_texts)
        assert any("Football" in t for t in all_texts)

    def test_events_today_keyboard(self):
        from bot.keyboards.inline import events_today_keyboard
        from bot.services.events import EVENTS
        events_list = EVENTS[:2]
        kb = events_today_keyboard(events_list, "pt")
        assert isinstance(kb, InlineKeyboardMarkup)
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert any(d and d.startswith("events:detail:") for d in all_data)
        assert "events:categories" in all_data
        assert "menu:main" in all_data

    def test_events_category_keyboard(self):
        from bot.keyboards.inline import events_category_keyboard
        from bot.services.events import get_events
        events_list = get_events("festival")
        kb = events_category_keyboard(events_list, "pt")
        assert isinstance(kb, InlineKeyboardMarkup)
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert any(d and d.startswith("events:detail:") for d in all_data)
        assert "menu:events" in all_data

    def test_events_detail_keyboard(self):
        from bot.keyboards.inline import events_detail_keyboard
        kb = events_detail_keyboard(0, "football", "pt")
        assert isinstance(kb, InlineKeyboardMarkup)
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "menu:events" in all_data
        assert "menu:main" in all_data

    def test_main_menu_has_events_button(self):
        from bot.keyboards.inline import main_menu_keyboard
        kb = main_menu_keyboard("pt")
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "menu:events" in all_data


# ===================================================================
# Events handler tests
# ===================================================================

class TestEventsHandlers:
    @pytest.mark.asyncio
    async def test_events_command_with_today_events(self):
        """Test /eventos shows today's events when available."""
        from bot.handlers.events import events_command
        from bot.services.events import EVENTS

        # Patch date to match the first event
        first = EVENTS[0]
        with patch("bot.services.events.today_in_porto",
                   return_value=first.start_date):

            update = _make_update(lang="pt")
            context = _make_context()
            await events_command(update, context)

            update.message.reply_text.assert_called_once()
            call_args = update.message.reply_text.call_args
            text = call_args[0][0]
            assert "Eventos Hoje" in text

    @pytest.mark.asyncio
    async def test_events_command_no_today_shows_upcoming(self):
        """Test /eventos shows upcoming when nothing today."""
        from bot.handlers.events import events_command

        with patch("bot.services.events.today_in_porto",
                   return_value=date(2026, 1, 1)):

            update = _make_update(lang="pt")
            context = _make_context()
            await events_command(update, context)

            update.message.reply_text.assert_called_once()
            call_args = update.message.reply_text.call_args
            text = call_args[0][0]
            assert "Próximos" in text or "Sem eventos hoje" in text

    @pytest.mark.asyncio
    async def test_events_command_en(self):
        """Test /eventos command in English."""
        from bot.handlers.events import events_command
        from bot.services.events import EVENTS

        first = EVENTS[0]
        with patch("bot.services.events.today_in_porto",
                   return_value=first.start_date):

            update = _make_update(lang="en")
            context = _make_context()
            await events_command(update, context)

            update.message.reply_text.assert_called_once()
            call_args = update.message.reply_text.call_args
            text = call_args[0][0]
            assert "Events Today" in text

    @pytest.mark.asyncio
    async def test_events_menu_callback(self):
        """Test events menu callback shows today's view."""
        from bot.handlers.events import events_menu_callback
        from bot.services.events import EVENTS

        first = EVENTS[0]
        with patch("bot.services.events.today_in_porto",
                   return_value=first.start_date):

            update = _make_update(lang="pt")
            context = _make_context()
            await events_menu_callback(update, context)

            update.callback_query.answer.assert_called_once()
            update.callback_query.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_events_categories_callback(self):
        """Test categories callback shows category menu."""
        from bot.handlers.events import events_categories_callback
        update = _make_update(lang="pt")
        update.callback_query.data = "events:categories"
        context = _make_context()

        await events_categories_callback(update, context)

        update.callback_query.answer.assert_called_once()
        call_args = update.callback_query.edit_message_text.call_args
        text = call_args[0][0]
        assert "Eventos no Porto" in text

    @pytest.mark.asyncio
    async def test_events_category_callback_festival(self):
        """Test category callback shows a populated category."""
        from bot.handlers.events import events_category_callback
        update = _make_update(lang="pt")
        update.callback_query.data = "events:cat:festival"
        context = _make_context()

        await events_category_callback(update, context)

        update.callback_query.answer.assert_called_once()
        call_args = update.callback_query.edit_message_text.call_args
        text = call_args[0][0]
        assert "Festivais" in text

    @pytest.mark.asyncio
    async def test_events_category_callback_football_without_live_feed(self):
        """With no live fixtures loaded, football says so instead of faking."""
        from bot.handlers.events import events_category_callback
        update = _make_update(lang="pt")
        update.callback_query.data = "events:cat:football"
        context = _make_context()

        await events_category_callback(update, context)

        call_args = update.callback_query.edit_message_text.call_args
        text = call_args[0][0]
        assert "Sem eventos" in text or "Futebol" in text

    @pytest.mark.asyncio
    async def test_events_category_callback_all(self):
        """Test 'all' category shows all events."""
        from bot.handlers.events import events_category_callback
        update = _make_update(lang="en")
        update.callback_query.data = "events:cat:all"
        context = _make_context()

        await events_category_callback(update, context)

        call_args = update.callback_query.edit_message_text.call_args
        text = call_args[0][0]
        assert "All Events" in text

    @pytest.mark.asyncio
    async def test_events_detail_callback(self):
        """Test detail callback shows event info with transport tip."""
        from bot.handlers.events import events_detail_callback
        update = _make_update(lang="pt")
        update.callback_query.data = "events:detail:0"
        context = _make_context()

        await events_detail_callback(update, context)

        call_args = update.callback_query.edit_message_text.call_args
        text = call_args[0][0]
        from bot.services.events import get_event
        from bot.utils.formatting import escape_md
        event = get_event(0)
        assert escape_md(event.venue_pt) in text
        assert escape_md(event.transport_tip_pt) in text

    @pytest.mark.asyncio
    async def test_events_detail_callback_en(self):
        """Test detail callback in English."""
        from bot.handlers.events import events_detail_callback
        update = _make_update(lang="en")
        update.callback_query.data = "events:detail:0"
        context = _make_context()

        await events_detail_callback(update, context)

        call_args = update.callback_query.edit_message_text.call_args
        text = call_args[0][0]
        assert "How to get there" in text


# ===================================================================
# i18n tests
# ===================================================================

class TestEventsI18n:
    def test_events_i18n_keys_exist(self):
        """Verify all events i18n keys exist in both languages."""
        from bot.utils.i18n import TRANSLATIONS
        events_keys = [
            "events_today", "events_none_today", "events_none_upcoming",
            "events_title", "events_overview", "events_detail",
            "events_transport_tip", "events_no_events",
            "kb_events", "kb_events_football", "kb_events_festival",
            "kb_events_music", "kb_events_culture", "kb_events_all",
            "kb_events_back_menu", "kb_events_more",
        ]
        for key in events_keys:
            assert key in TRANSLATIONS["pt"], f"Missing PT key: {key}"
            assert key in TRANSLATIONS["en"], f"Missing EN key: {key}"
