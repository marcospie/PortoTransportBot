"""Tests for the trip-planner buttons, the location handler and push notifications.

Covers the user-facing bugs fixed in this change:

* the "Use my location" button in the trip planner was dead (no handler
  registered, so it fell through to the catch-all and stripped the keyboard);
* a location shared while planning a trip was swallowed by the nearby-stops
  screen instead of setting the origin;
* nearby search never showed CP train stations;
* ``trip_detail_callback`` answered twice and showed hardcoded English;
* the global error handler was hardcoded Portuguese;
* proactive notifications did not exist at all (and must be opt-in).
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from telegram import InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import CallbackQueryHandler

from bot.handlers import location as location_handler_mod
from bot.handlers import routes as routes_mod
from bot.services import notifications
from bot.services.trip_planner import TripOption, TripStep


PORTO_TZ = ZoneInfo("Europe/Lisbon")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_update(lang="pt", user_id=999001, text="", lat=None, lon=None):
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_user.language_code = lang
    update.effective_chat.id = user_id

    msg = MagicMock()
    msg.text = text
    msg.reply_text = AsyncMock()
    if lat is None:
        msg.location = None
    else:
        msg.location = MagicMock(latitude=lat, longitude=lon)
    update.message = msg

    query = MagicMock()
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.edit_message_reply_markup = AsyncMock()
    query.message = MagicMock()
    query.message.reply_text = AsyncMock()
    query.data = ""
    query.from_user.id = user_id
    query.from_user.language_code = lang
    update.callback_query = query
    return update


def _make_context(user_data=None, bot_data=None):
    ctx = MagicMock()
    ctx.user_data = {} if user_data is None else user_data
    ctx.bot_data = {} if bot_data is None else bot_data
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()
    return ctx


def _fallback_option():
    return TripOption(
        steps=[TripStep(mode="metro", from_name="A", to_name="B",
                        line="Linha Azul", duration_min=8)],
        total_time_min=8,
        transfers=0,
        estimated=True,
        source="estimate",
    )


def _motis_option():
    return TripOption(
        steps=[TripStep(mode="bus", from_name="VALE FORMOSO", to_name="FOZ",
                        line="204", duration_min=20, direction="Foz",
                        departure_time="09:12", wait_min=4)],
        total_time_min=25,
        transfers=0,
        estimated=False,
        source="motis",
        departure_time="09:08",
        arrival_time="09:33",
    )


# ===================================================================
# 1. "Use my location" is wired up
# ===================================================================

class TestUseLocationCallbackRegistered:

    def _registered_patterns(self):
        from bot import main

        app = MagicMock()
        handlers = []
        app.add_handler.side_effect = lambda h, *a, **k: handlers.append(h)
        main.register_handlers(app)
        return handlers

    def test_use_location_pattern_is_registered(self):
        handlers = self._registered_patterns()
        matches = [
            h for h in handlers
            if isinstance(h, CallbackQueryHandler)
            and h.pattern is not None
            and h.pattern.match("trip:use_location_origin")
        ]
        assert matches, "trip:use_location_origin has no handler registered"

    def test_use_location_routes_to_the_right_callback(self):
        handlers = self._registered_patterns()
        for h in handlers:
            if isinstance(h, CallbackQueryHandler) and h.pattern is not None \
                    and h.pattern.match("trip:use_location_origin"):
                assert h.callback is routes_mod.trip_use_location_callback
                return
        pytest.fail("no handler matched trip:use_location_origin")

    def test_button_callback_data_is_within_telegram_limit(self):
        markup = routes_mod._origin_prompt_keyboard("pt")
        for row in markup.inline_keyboard:
            for button in row:
                if button.callback_data:
                    assert len(button.callback_data.encode("utf-8")) <= 64


class TestUseLocationCallbackBehaviour:

    @pytest.mark.asyncio
    async def test_answers_and_arms_origin_state(self):
        update = _make_update()
        context = _make_context()

        await routes_mod.trip_use_location_callback(update, context)

        update.callback_query.answer.assert_awaited()
        assert routes_mod.AWAITING_ROUTE_ORIGIN in context.user_data
        assert isinstance(context.user_data[routes_mod.AWAITING_ROUTE_ORIGIN], datetime)

    @pytest.mark.asyncio
    async def test_keyboard_is_not_stripped(self):
        """The old behaviour removed the keyboard via the catch-all handler."""
        update = _make_update()
        context = _make_context()

        await routes_mod.trip_use_location_callback(update, context)

        update.callback_query.edit_message_reply_markup.assert_not_called()
        update.callback_query.edit_message_text.assert_awaited()

    @pytest.mark.asyncio
    async def test_offers_a_share_location_button(self):
        update = _make_update()
        context = _make_context()

        await routes_mod.trip_use_location_callback(update, context)

        update.callback_query.message.reply_text.assert_awaited()
        markup = update.callback_query.message.reply_text.call_args.kwargs["reply_markup"]
        assert isinstance(markup, ReplyKeyboardMarkup)
        assert markup.keyboard[0][0].request_location is True

    @pytest.mark.asyncio
    async def test_prompt_is_localized(self):
        for lang in ("pt", "en"):
            update = _make_update(lang=lang)
            context = _make_context()
            await routes_mod.trip_use_location_callback(update, context)
            text = update.callback_query.edit_message_text.call_args[0][0]
            expected = routes_mod.tf("trip_share_location_prompt", lang)
            assert expected in text


# ===================================================================
# 2. A location shared during trip planning sets the origin
# ===================================================================

class TestLocationDuringTripPlanning:

    @pytest.mark.asyncio
    async def test_handle_route_location_sets_origin(self):
        update = _make_update(lat=41.1621, lon=-8.6109)
        context = _make_context(user_data={
            routes_mod.AWAITING_ROUTE_ORIGIN: datetime.now(),
        })

        handled = await routes_mod.handle_route_location(update, context)

        assert handled is True
        assert context.user_data["route_origin"]["lat"] == 41.1621
        assert context.user_data["route_origin"]["lon"] == -8.6109
        assert routes_mod.AWAITING_ROUTE_DEST in context.user_data
        assert routes_mod.AWAITING_ROUTE_ORIGIN not in context.user_data

    @pytest.mark.asyncio
    async def test_handle_route_location_ignored_when_not_planning(self):
        update = _make_update(lat=41.1621, lon=-8.6109)
        context = _make_context()

        assert await routes_mod.handle_route_location(update, context) is False

    @pytest.mark.asyncio
    async def test_expired_state_is_not_consumed(self):
        update = _make_update(lat=41.1621, lon=-8.6109)
        context = _make_context(user_data={
            routes_mod.AWAITING_ROUTE_ORIGIN: datetime.now() - timedelta(hours=2),
        })

        assert await routes_mod.handle_route_location(update, context) is False

    @pytest.mark.asyncio
    async def test_location_handler_delegates_to_trip_planner(self):
        """The nearby screen must not steal a location meant for the planner."""
        update = _make_update(lat=41.1621, lon=-8.6109)
        context = _make_context(user_data={
            routes_mod.AWAITING_ROUTE_ORIGIN: datetime.now(),
        })

        with patch.object(location_handler_mod, "_collect_nearby",
                          new_callable=AsyncMock) as nearby:
            await location_handler_mod.location_handler(update, context)

        nearby.assert_not_called()
        assert context.user_data["route_origin"]["lat"] == 41.1621
        # The nearby handler also stores last_location; it must not have run.
        assert "last_location" not in context.user_data

    @pytest.mark.asyncio
    async def test_location_handler_still_shows_nearby_otherwise(self):
        update = _make_update(lat=41.1496, lon=-8.6109)
        context = _make_context()

        with patch.object(location_handler_mod, "_load_settings",
                          new_callable=AsyncMock) as settings, \
             patch.object(location_handler_mod, "_collect_nearby",
                          new_callable=AsyncMock) as nearby:
            settings.return_value = {"metro_radius_m": 500, "bus_radius_m": 200,
                                     "max_results": 5}
            nearby.return_value = ([], [], [], [])
            await location_handler_mod.location_handler(update, context)

        nearby.assert_awaited()
        assert context.user_data["last_location"] == {"lat": 41.1496, "lon": -8.6109}


# ===================================================================
# 3. CP trains in the nearby screen
# ===================================================================

class TestNearbyIncludesTrains:

    def test_cp_stations_found_near_campanha(self):
        trains = location_handler_mod._get_nearby_trains(41.1489, -8.5856, 1.0)
        names = [s["name"] for s in trains]
        assert any("Campanh" in n for n in names)

    def test_cp_stations_found_near_sao_bento(self):
        trains = location_handler_mod._get_nearby_trains(41.1455, -8.6103, 1.0)
        assert trains, "São Bento should have a CP station nearby"

    def test_train_section_rendered(self):
        settings = {"metro_radius_m": 500, "bus_radius_m": 200, "max_results": 5}
        trains = location_handler_mod._get_nearby_trains(41.1489, -8.5856, 1.0)
        assert trains
        text, keyboard = location_handler_mod._render_nearby(
            "pt", settings, [], [], trains, [])
        assert routes_mod.tf("train_stations", "pt") in text
        assert isinstance(keyboard, InlineKeyboardMarkup)
        callbacks = [b.callback_data for row in keyboard.inline_keyboard for b in row]
        assert any(c.startswith("train:station:") for c in callbacks)

    def test_train_buttons_respect_callback_data_limit(self):
        settings = {"metro_radius_m": 500, "bus_radius_m": 200, "max_results": 10}
        trains = location_handler_mod._get_nearby_trains(41.1489, -8.5856, 5.0)
        _text, keyboard = location_handler_mod._render_nearby(
            "pt", settings, [], [], trains, [])
        for row in keyboard.inline_keyboard:
            for button in row:
                if button.callback_data:
                    assert len(button.callback_data.encode("utf-8")) <= 64

    @pytest.mark.asyncio
    async def test_collect_nearby_returns_four_buckets(self):
        settings = {"metro_radius_m": 500, "bus_radius_m": 200, "max_results": 5}
        with patch.object(location_handler_mod, "_get_nearby_bus_stops",
                          new_callable=AsyncMock) as bus:
            bus.return_value = []
            result = await location_handler_mod._collect_nearby(
                41.1489, -8.5856, settings)
        assert len(result) == 4
        trains = result[2]
        assert any("Campanh" in s["name"] for s in trains)


# ===================================================================
# 4. trip_detail_callback: one localized answer, stale message refreshed
# ===================================================================

class TestTripDetailCallback:

    @pytest.mark.asyncio
    async def test_expired_options_answer_once_and_localized(self):
        from bot.utils.i18n import t

        update = _make_update(lang="pt")
        update.callback_query.data = "trip:detail:3"
        context = _make_context(user_data={"trip_options": []})

        await routes_mod.trip_detail_callback(update, context)

        assert update.callback_query.answer.await_count == 1
        answer_text = update.callback_query.answer.call_args[0][0]
        assert answer_text == routes_mod.plain(t("option_not_available", "pt"))
        assert "Option not available" not in answer_text
        # The stale message is refreshed with a way to start over.
        update.callback_query.edit_message_text.assert_awaited()

    @pytest.mark.asyncio
    async def test_expired_options_english(self):
        update = _make_update(lang="en")
        update.callback_query.data = "trip:detail:9"
        context = _make_context(user_data={"trip_options": []})

        await routes_mod.trip_detail_callback(update, context)

        answer_text = update.callback_query.answer.call_args[0][0]
        assert "no longer available" in answer_text
        assert "\\" not in answer_text  # plain text, not MarkdownV2

    @pytest.mark.asyncio
    async def test_valid_option_renders_detail(self):
        update = _make_update()
        update.callback_query.data = "trip:detail:0"
        context = _make_context(user_data={"trip_options": [_motis_option()]})

        await routes_mod.trip_detail_callback(update, context)

        assert update.callback_query.answer.await_count == 1
        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "204" in text


# ===================================================================
# 5. Estimate labelling
# ===================================================================

class TestEstimateLabelling:

    def test_fallback_option_is_labelled(self):
        from bot.utils.i18n import t

        text = routes_mod.format_trip_option(_fallback_option(), 1, "pt")
        assert t("data_estimated", "pt") in text

    def test_motis_option_is_not_labelled(self):
        from bot.utils.i18n import t

        text = routes_mod.format_trip_option(_motis_option(), 1, "pt")
        assert t("data_estimated", "pt") not in text

    def test_motis_option_shows_real_times(self):
        text = routes_mod.format_trip_option(_motis_option(), 1, "pt")
        assert "09:08" in text and "09:33" in text
        assert "09:12" in text          # the leg's own departure
        assert "4" in text              # the waiting time

    def test_bus_step_rendered_for_stcp(self):
        text = routes_mod.format_trip_option(_motis_option(), 1, "en")
        assert "Bus" in text
        assert "VALE FORMOSO" in text


# ===================================================================
# 6. Localized global error handler
# ===================================================================

class TestErrorHandlerLocalization:

    @pytest.mark.asyncio
    async def test_callback_error_is_localized_en(self):
        from bot import main
        from bot.utils.i18n import t
        from telegram import Update as TgUpdate

        update = MagicMock(spec=TgUpdate)
        update.callback_query = MagicMock()
        update.callback_query.answer = AsyncMock()
        update.effective_user = MagicMock()
        update.effective_user.language_code = "en"
        context = MagicMock()
        context.error = RuntimeError("boom")

        await main.error_handler(update, context)

        text = update.callback_query.answer.call_args[0][0]
        assert text == main.routes.plain(t("error_generic", "en"))
        assert "Erro interno" not in text

    @pytest.mark.asyncio
    async def test_message_error_is_localized_en(self):
        from bot import main
        from telegram import Update as TgUpdate

        update = MagicMock(spec=TgUpdate)
        update.callback_query = None
        update.effective_message = MagicMock()
        update.effective_message.reply_text = AsyncMock()
        update.effective_user = MagicMock()
        update.effective_user.language_code = "en"
        context = MagicMock()
        context.error = RuntimeError("boom")

        await main.error_handler(update, context)

        text = update.effective_message.reply_text.call_args[0][0]
        assert "error occurred" in text
        assert "Ocorreu um erro" not in text

    @pytest.mark.asyncio
    async def test_message_error_is_localized_pt(self):
        from bot import main
        from bot.utils.i18n import t
        from telegram import Update as TgUpdate

        update = MagicMock(spec=TgUpdate)
        update.callback_query = None
        update.effective_message = MagicMock()
        update.effective_message.reply_text = AsyncMock()
        update.effective_user = MagicMock()
        update.effective_user.language_code = "pt"
        context = MagicMock()
        context.error = RuntimeError("boom")

        await main.error_handler(update, context)

        assert update.effective_message.reply_text.call_args[0][0] == \
            t("error_generic", "pt")


# ===================================================================
# 7. Daily GTFS refresh + dead handler removal
# ===================================================================

class TestMainWiring:

    def test_dead_trip_planner_handler_is_gone(self):
        import importlib
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("bot.handlers.trip_planner")

    def test_gtfs_refresh_job_exists(self):
        from bot import main
        assert callable(main.gtfs_refresh_job)
        assert main.GTFS_REFRESH_TIME.tzinfo is not None

    @pytest.mark.asyncio
    async def test_post_init_schedules_daily_refresh(self):
        from bot import main

        app = MagicMock()
        app.bot.set_my_commands = AsyncMock()
        app.bot.set_chat_menu_button = AsyncMock()
        app.bot.get_my_commands = AsyncMock(return_value=[])
        app.bot.set_my_description = AsyncMock()
        app.bot.set_my_short_description = AsyncMock()
        app.job_queue = MagicMock()

        with patch.object(main, "init_db", new_callable=AsyncMock), \
             patch.object(main, "refresh_gtfs", new_callable=AsyncMock), \
             patch.object(main.notifications, "register_jobs") as reg:
            await main.post_init(app)

        app.job_queue.run_daily.assert_called_once()
        assert app.job_queue.run_daily.call_args.kwargs["time"] is main.GTFS_REFRESH_TIME
        reg.assert_called_once_with(app)


# ===================================================================
# 8. Notifications: opt-in, dedup, quiet hours, Forbidden
# ===================================================================

def _real_alert(alert_id="a1", lines=None, severity="high"):
    return {
        "id": alert_id,
        "title": "Linha A interrompida",
        "description": "Circulação suspensa entre Trindade e Bolhão.",
        "affected_lines": lines if lines is not None else ["A"],
        "affected_stops": [],
        "severity": severity,
        "source": "stcp",
    }


class TestNotificationOptIn:

    @pytest.mark.asyncio
    async def test_off_by_default(self):
        with patch("bot.database.get_user_settings", new_callable=AsyncMock) as gs:
            gs.return_value = {"notifications": "off"}
            assert await notifications.user_has_notifications_on(1) is False

    @pytest.mark.asyncio
    async def test_missing_key_is_treated_as_off(self):
        with patch("bot.database.get_user_settings", new_callable=AsyncMock) as gs:
            gs.return_value = {"metro_radius_m": 500}
            assert await notifications.user_has_notifications_on(1) is False

    @pytest.mark.asyncio
    async def test_settings_failure_is_treated_as_off(self):
        with patch("bot.database.get_user_settings", new_callable=AsyncMock) as gs:
            gs.side_effect = RuntimeError("db down")
            assert await notifications.user_has_notifications_on(1) is False

    @pytest.mark.asyncio
    async def test_on_is_respected(self):
        with patch("bot.database.get_user_settings", new_callable=AsyncMock) as gs:
            gs.return_value = {"notifications": "on"}
            assert await notifications.user_has_notifications_on(1) is True

    @pytest.mark.asyncio
    async def test_alerts_job_only_messages_opted_in_users(self):
        context = _make_context()
        with patch.object(notifications, "in_quiet_hours", return_value=False), \
             patch("bot.services.alerts.get_active_alerts",
                   new_callable=AsyncMock) as alerts, \
             patch.object(notifications, "get_opted_in_user_ids",
                          new_callable=AsyncMock) as opted, \
             patch.object(notifications, "user_alert_matches",
                          new_callable=AsyncMock) as matches:
            alerts.return_value = [_real_alert()]
            opted.return_value = [42]
            matches.return_value = True
            await notifications.alerts_job(context)

        assert context.bot.send_message.await_count == 1
        assert context.bot.send_message.call_args.kwargs["chat_id"] == 42

    @pytest.mark.asyncio
    async def test_alerts_job_sends_nothing_when_nobody_opted_in(self):
        context = _make_context()
        with patch.object(notifications, "in_quiet_hours", return_value=False), \
             patch("bot.services.alerts.get_active_alerts",
                   new_callable=AsyncMock) as alerts, \
             patch.object(notifications, "get_opted_in_user_ids",
                          new_callable=AsyncMock) as opted:
            alerts.return_value = [_real_alert()]
            opted.return_value = []
            await notifications.alerts_job(context)

        context.bot.send_message.assert_not_called()


class TestNotificationAlertFiltering:

    def test_fabricated_fallback_alert_is_not_pushable(self):
        alert = _real_alert()
        alert["source"] = "fallback"
        assert notifications.is_pushable_alert(alert) is False

    def test_unavailable_source_alert_is_not_pushable(self):
        alert = _real_alert()
        alert["source"] = "unavailable"
        assert notifications.is_pushable_alert(alert) is False

    def test_alert_flagged_as_error_is_not_pushable(self):
        alert = _real_alert()
        alert["error"] = True
        assert notifications.is_pushable_alert(alert) is False

    def test_real_alert_is_pushable(self):
        assert notifications.is_pushable_alert(_real_alert()) is True

    def test_low_severity_network_wide_info_is_not_pushable(self):
        alert = _real_alert(lines=[], severity="low")
        assert notifications.is_pushable_alert(alert) is False

    @pytest.mark.asyncio
    async def test_fabricated_alerts_are_never_sent(self):
        context = _make_context()
        alert = _real_alert()
        alert["source"] = "fallback"
        with patch.object(notifications, "in_quiet_hours", return_value=False), \
             patch("bot.services.alerts.get_active_alerts",
                   new_callable=AsyncMock) as alerts, \
             patch.object(notifications, "get_opted_in_user_ids",
                          new_callable=AsyncMock) as opted:
            alerts.return_value = [alert]
            opted.return_value = [42]
            await notifications.alerts_job(context)

        context.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_matching_uses_user_favourites(self):
        with patch("bot.database.get_favorites", new_callable=AsyncMock) as favs, \
             patch("bot.database.get_commuter_profile",
                   new_callable=AsyncMock) as prof:
            favs.return_value = [{"stop_id": "BCM2", "name": "Bolhão"}]
            prof.return_value = None
            alert = _real_alert(lines=[])
            alert["affected_stops"] = ["BCM2"]
            assert await notifications.user_alert_matches(7, alert) is True

    @pytest.mark.asyncio
    async def test_non_matching_alert_is_skipped(self):
        with patch("bot.database.get_favorites", new_callable=AsyncMock) as favs, \
             patch("bot.database.get_commuter_profile",
                   new_callable=AsyncMock) as prof:
            favs.return_value = [{"stop_id": "ZZZ9", "name": "Outra"}]
            prof.return_value = None
            alert = _real_alert(lines=[])
            alert["affected_stops"] = ["BCM2"]
            assert await notifications.user_alert_matches(7, alert) is False


class TestNotificationDedup:

    @pytest.mark.asyncio
    async def test_same_alert_not_pushed_twice(self):
        bot_data = {}
        with patch.object(notifications, "in_quiet_hours", return_value=False), \
             patch("bot.services.alerts.get_active_alerts",
                   new_callable=AsyncMock) as alerts, \
             patch.object(notifications, "get_opted_in_user_ids",
                          new_callable=AsyncMock) as opted, \
             patch.object(notifications, "user_alert_matches",
                          new_callable=AsyncMock) as matches:
            alerts.return_value = [_real_alert()]
            opted.return_value = [42]
            matches.return_value = True

            first = _make_context(bot_data=bot_data)
            await notifications.alerts_job(first)
            second = _make_context(bot_data=bot_data)
            await notifications.alerts_job(second)

        assert first.bot.send_message.await_count == 1
        second.bot.send_message.assert_not_called()

    def test_dedup_expires(self):
        context = _make_context()
        now = notifications.now_porto()
        notifications.mark_alert_sent(context, 1, "x", now)
        assert notifications.already_sent_alert(context, 1, "x", now) is True
        later = now + timedelta(hours=notifications.ALERT_DEDUP_TTL_H + 1)
        assert notifications.already_sent_alert(context, 1, "x", later) is False

    def test_reminder_dedup_is_per_day(self):
        context = _make_context()
        day = datetime(2026, 7, 27, 8, 0, tzinfo=PORTO_TZ)
        notifications.mark_reminder_sent(context, 1, "to_work", day)
        assert notifications.already_sent_reminder(context, 1, "to_work", day) is True
        assert notifications.already_sent_reminder(
            context, 1, "to_work", day + timedelta(days=1)) is False


class TestNotificationQuietHours:

    def test_middle_of_the_night_is_quiet(self):
        assert notifications.in_quiet_hours(
            datetime(2026, 7, 27, 3, 0, tzinfo=PORTO_TZ)) is True

    def test_late_evening_is_quiet(self):
        assert notifications.in_quiet_hours(
            datetime(2026, 7, 27, 23, 30, tzinfo=PORTO_TZ)) is True

    def test_daytime_is_not_quiet(self):
        assert notifications.in_quiet_hours(
            datetime(2026, 7, 27, 12, 0, tzinfo=PORTO_TZ)) is False

    def test_uses_lisbon_time_not_server_time(self):
        # 05:00 UTC is 06:00 in Lisbon during summer -> still quiet.
        utc_moment = datetime(2026, 7, 27, 5, 0, tzinfo=ZoneInfo("UTC"))
        assert notifications.in_quiet_hours(utc_moment) is True
        # 07:00 UTC is 08:00 Lisbon -> no longer quiet.
        assert notifications.in_quiet_hours(
            datetime(2026, 7, 27, 7, 0, tzinfo=ZoneInfo("UTC"))) is False

    def test_now_porto_is_timezone_aware_lisbon(self):
        assert notifications.now_porto().tzinfo is not None
        assert "Lisbon" in str(notifications.now_porto().tzinfo)

    @pytest.mark.asyncio
    async def test_alerts_job_skipped_during_quiet_hours(self):
        context = _make_context()
        with patch.object(notifications, "now_porto",
                          return_value=datetime(2026, 7, 27, 3, 0, tzinfo=PORTO_TZ)), \
             patch.object(notifications, "get_opted_in_user_ids",
                          new_callable=AsyncMock) as opted:
            await notifications.alerts_job(context)
        opted.assert_not_called()
        context.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_commute_job_skipped_during_quiet_hours(self):
        context = _make_context()
        with patch.object(notifications, "now_porto",
                          return_value=datetime(2026, 7, 27, 4, 0, tzinfo=PORTO_TZ)), \
             patch.object(notifications, "get_opted_in_user_ids",
                          new_callable=AsyncMock) as opted:
            await notifications.commute_reminder_job(context)
        opted.assert_not_called()


class TestNotificationForbidden:

    @pytest.mark.asyncio
    async def test_forbidden_is_swallowed(self):
        from telegram.error import Forbidden

        context = _make_context()
        context.bot.send_message.side_effect = Forbidden("bot was blocked by the user")

        assert await notifications.send_push(context, 1, "hello") is False

    @pytest.mark.asyncio
    async def test_forbidden_does_not_stop_the_job(self):
        from telegram.error import Forbidden

        context = _make_context()
        context.bot.send_message.side_effect = [
            Forbidden("blocked"), None,
        ]
        with patch.object(notifications, "in_quiet_hours", return_value=False), \
             patch("bot.services.alerts.get_active_alerts",
                   new_callable=AsyncMock) as alerts, \
             patch.object(notifications, "get_opted_in_user_ids",
                          new_callable=AsyncMock) as opted, \
             patch.object(notifications, "user_alert_matches",
                          new_callable=AsyncMock) as matches:
            alerts.return_value = [_real_alert()]
            opted.return_value = [1, 2]
            matches.return_value = True
            await notifications.alerts_job(context)

        assert context.bot.send_message.await_count == 2

    @pytest.mark.asyncio
    async def test_blocked_user_is_not_marked_as_sent(self):
        from telegram.error import Forbidden

        context = _make_context()
        context.bot.send_message.side_effect = Forbidden("blocked")
        await notifications.send_push(context, 1, "hi")
        assert notifications.already_sent_alert(context, 1, "a1") is False


class TestCommuteReminder:

    def test_due_ten_minutes_before(self):
        moment = datetime(2026, 7, 27, 7, 50, tzinfo=PORTO_TZ)
        assert notifications.is_reminder_due("08:00", moment) is True

    def test_not_due_long_before(self):
        moment = datetime(2026, 7, 27, 7, 0, tzinfo=PORTO_TZ)
        assert notifications.is_reminder_due("08:00", moment) is False

    def test_not_due_after(self):
        moment = datetime(2026, 7, 27, 8, 10, tzinfo=PORTO_TZ)
        assert notifications.is_reminder_due("08:00", moment) is False

    def test_invalid_time_is_never_due(self):
        assert notifications.is_reminder_due("", notifications.now_porto()) is False
        assert notifications.is_reminder_due("banana") is False

    @pytest.mark.asyncio
    async def test_reminder_sent_for_opted_in_user(self):
        # Monday 07:50 Lisbon, departure at 08:00
        moment = datetime(2026, 7, 27, 7, 50, tzinfo=PORTO_TZ)
        assert moment.weekday() == 0
        context = _make_context()
        profile = {
            "home_name": "Trindade", "work_name": "Aeroporto",
            "usual_departure_time": "08:00", "usual_return_time": "18:00",
        }
        with patch.object(notifications, "now_porto", return_value=moment), \
             patch.object(notifications, "get_opted_in_user_ids",
                          new_callable=AsyncMock) as opted, \
             patch("bot.database.get_commuter_profile",
                   new_callable=AsyncMock) as prof, \
             patch("bot.database.get_user_settings", new_callable=AsyncMock) as gs:
            opted.return_value = [5]
            prof.return_value = profile
            gs.return_value = {"language": "pt", "notifications": "on"}
            await notifications.commute_reminder_job(context)

        assert context.bot.send_message.await_count == 1
        text = context.bot.send_message.call_args.kwargs["text"]
        assert "08:00" in text

    @pytest.mark.asyncio
    async def test_reminder_not_repeated_same_day(self):
        moment = datetime(2026, 7, 27, 7, 50, tzinfo=PORTO_TZ)
        bot_data = {}
        profile = {
            "home_name": "Trindade", "work_name": "Aeroporto",
            "usual_departure_time": "08:00", "usual_return_time": "18:00",
        }
        with patch.object(notifications, "now_porto", return_value=moment), \
             patch.object(notifications, "get_opted_in_user_ids",
                          new_callable=AsyncMock) as opted, \
             patch("bot.database.get_commuter_profile",
                   new_callable=AsyncMock) as prof, \
             patch("bot.database.get_user_settings", new_callable=AsyncMock) as gs:
            opted.return_value = [5]
            prof.return_value = profile
            gs.return_value = {"language": "pt"}
            first = _make_context(bot_data=bot_data)
            await notifications.commute_reminder_job(first)
            second = _make_context(bot_data=bot_data)
            await notifications.commute_reminder_job(second)

        assert first.bot.send_message.await_count == 1
        second.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_reminders_at_the_weekend(self):
        saturday = datetime(2026, 8, 1, 7, 50, tzinfo=PORTO_TZ)
        assert saturday.weekday() == 5
        context = _make_context()
        with patch.object(notifications, "now_porto", return_value=saturday), \
             patch.object(notifications, "get_opted_in_user_ids",
                          new_callable=AsyncMock) as opted:
            await notifications.commute_reminder_job(context)
        opted.assert_not_called()


class TestNotificationRegistration:

    def test_register_jobs_uses_the_job_queue(self):
        app = MagicMock()
        app.job_queue = MagicMock()
        assert notifications.register_jobs(app) is True
        assert app.job_queue.run_repeating.call_count == 2
        names = {c.kwargs["name"] for c in app.job_queue.run_repeating.call_args_list}
        assert names == {notifications.ALERTS_JOB_NAME,
                         notifications.COMMUTE_JOB_NAME}

    def test_register_jobs_degrades_without_job_queue(self):
        app = MagicMock()
        app.job_queue = None
        assert notifications.register_jobs(app) is False

    def test_push_bodies_are_localized(self):
        from bot.utils.i18n import t

        pt = notifications.format_alert_push(_real_alert(), "pt")
        en = notifications.format_alert_push(_real_alert(), "en")
        assert t("notif_alert_title", "pt") in pt
        assert t("notif_alert_title", "en") in en

    def test_commute_push_localized(self):
        from bot.utils.i18n import t

        profile = {"home_name": "Trindade", "work_name": "Aeroporto",
                   "usual_departure_time": "08:00", "usual_return_time": "18:00"}
        for lang in ("pt", "en"):
            text = notifications.format_commute_push(profile, "to_work", lang)
            assert t("notif_commute_reminder", lang) in text
            assert "Trindade" in text
