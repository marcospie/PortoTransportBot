"""Regression tests for data honesty.

Every test here pins down one rule: the bot must never present invented data as
fact, and must never let "the data source failed" look like "there is nothing to
report". These are user-safety properties, not cosmetics — a fabricated lift
outage or a bogus "no buses coming" can leave someone stranded.

All tests are offline: every upstream call is patched.
"""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest


# ===================================================================
# 1. STCP real-time: "API down" must not read as "no buses"
# ===================================================================

class TestSTCPErrorVersusEmpty:

    def setup_method(self):
        import bot.services.stcp as stcp
        stcp._cache.clear()
        stcp.reset_failure_cache()

    @pytest.mark.asyncio
    async def test_api_failure_is_flagged_as_error(self):
        from bot.services.stcp import (get_stop_real_time, STCPUnavailable,
                                       SOURCE_UNAVAILABLE)
        with patch("bot.services.stcp._get", new_callable=AsyncMock,
                   side_effect=STCPUnavailable("timeout")):
            data = await get_stop_real_time("BCM2")
        assert data["error"] is True
        assert data["source"] == SOURCE_UNAVAILABLE
        assert data["realtime"] is False
        assert list(data["arrivals"]) == []

    @pytest.mark.asyncio
    async def test_unknown_stop_is_distinguished_from_outage(self):
        from bot.services.stcp import (get_stop_real_time, STCPNotFound,
                                       SOURCE_NOT_FOUND)
        with patch("bot.services.stcp._get", new_callable=AsyncMock,
                   side_effect=STCPNotFound("404")):
            data = await get_stop_real_time("NOPE9")
        assert data["error"] is True
        assert data["source"] == SOURCE_NOT_FOUND

    @pytest.mark.asyncio
    async def test_genuine_empty_is_not_an_error(self):
        from bot.services.stcp import get_stop_real_time
        payload = {"stop_id": "BCM2", "stop_name": "Bolhão", "arrivals": [],
                   "data_source": "realtime"}
        with patch("bot.services.stcp._get", new_callable=AsyncMock,
                   return_value=payload):
            data = await get_stop_real_time("BCM2")
        assert data["error"] is False
        assert list(data["arrivals"]) == []
        assert data["realtime"] is True

    @pytest.mark.asyncio
    async def test_arrivals_carry_error_metadata_for_bare_callers(self):
        """Callers that only forward data["arrivals"] must still see the error."""
        from bot.services.stcp import get_stop_real_time, STCPUnavailable
        with patch("bot.services.stcp._get", new_callable=AsyncMock,
                   side_effect=STCPUnavailable("boom")):
            data = await get_stop_real_time("BCM2")
        arrivals = data["arrivals"]
        assert getattr(arrivals, "error") is True
        assert getattr(arrivals, "source") == "unavailable"

    @pytest.mark.asyncio
    async def test_failures_are_negative_cached(self):
        """A down API must not cost every request a fresh timeout."""
        import bot.services.stcp as stcp

        class Boom(Exception):
            pass

        session_get = patch("aiohttp.ClientSession.get",
                            side_effect=Boom("connection refused"))
        with session_get as mocked:
            first = await stcp.get_stop_real_time("BCM2")
            assert first["error"] is True
            assert stcp.api_unavailable() is True
            attempts_after_first = mocked.call_count

            # A second lookup short-circuits on the negative cache instead of
            # spending another 10-second timeout.
            second = await stcp.get_stop_real_time("OTHER1")
            assert second["error"] is True
            assert mocked.call_count == attempts_after_first

    @pytest.mark.asyncio
    async def test_stop_info_reports_error(self):
        from bot.services.stcp import get_stop_info, STCPUnavailable
        with patch("bot.services.stcp._get", new_callable=AsyncMock,
                   side_effect=STCPUnavailable("down")):
            info = await get_stop_info("BCM2")
        assert info["error"] is True
        assert info["routes"] == []

    @pytest.mark.asyncio
    async def test_routes_never_invented(self):
        """With no API route list and no GTFS loaded, return nothing."""
        import bot.services.stcp as stcp
        original = stcp._gtfs_bus_routes
        stcp._gtfs_bus_routes = []
        try:
            with patch("bot.services.stcp._get", new_callable=AsyncMock,
                       side_effect=stcp.STCPNotFound("404")):
                routes = await stcp.get_routes()
            assert routes == []
        finally:
            stcp._gtfs_bus_routes = original


# ===================================================================
# 2. Formatting: an outage must be shown as an outage
# ===================================================================

class TestFormattingHonesty:

    def test_error_renders_unavailable_not_no_buses(self):
        from bot.utils.formatting import format_bus_arrivals
        text = format_bus_arrivals("BCM2", "Bolhão", [], error=True)
        assert "indisponíveis" in text
        assert "Sem autocarros" not in text

    def test_error_renders_unavailable_in_english(self):
        from bot.utils.formatting import format_bus_arrivals
        text = format_bus_arrivals("BCM2", "Bolhão", [], error=True, lang="en")
        assert "unavailable" in text
        assert "No buses expected" not in text

    def test_not_found_has_its_own_message(self):
        from bot.utils.formatting import format_bus_arrivals
        text = format_bus_arrivals("NOPE9", "NOPE9", [], error=True,
                                   source="not_found")
        assert "não encontrada" in text

    def test_empty_without_error_still_says_no_buses(self):
        from bot.utils.formatting import format_bus_arrivals
        text = format_bus_arrivals("BCM2", "Bolhão", [])
        assert "Sem autocarros" in text

    @pytest.mark.asyncio
    async def test_error_detected_from_arrivals_metadata_alone(self):
        """The 3-argument call used by handlers must still be honest."""
        from bot.services.stcp import get_stop_real_time, STCPUnavailable
        from bot.utils.formatting import format_bus_arrivals
        with patch("bot.services.stcp._get", new_callable=AsyncMock,
                   side_effect=STCPUnavailable("down")):
            data = await get_stop_real_time("BCM2")
        text = format_bus_arrivals("BCM2", data["stop_name"], data["arrivals"])
        assert "indisponíveis" in text
        assert "Sem autocarros" not in text

    def test_scheduled_data_is_not_labelled_as_live(self):
        from bot.utils.formatting import format_metro_schedule
        deps = [{"direction": "Dragão", "time": "15:30"}]
        assert "Horário previsto" in format_metro_schedule("Trindade", "", deps)

    def test_realtime_data_is_labelled_as_updated(self):
        from bot.utils.formatting import format_metro_schedule
        deps = [{"direction": "Dragão", "time": "3 min", "realtime": True}]
        assert "Atualizado" in format_metro_schedule("Trindade", "", deps)

    def test_estimated_data_is_labelled_as_estimate(self):
        from bot.utils.formatting import format_metro_schedule
        deps = [{"direction": "Dragão", "time": "~3 min", "estimated": True}]
        assert "Estimativa" in format_metro_schedule("Trindade", "", deps)

    def test_no_dead_slice_swallows_arrivals(self):
        """The old arrivals[:0] branch silently dropped every arrival."""
        from bot.utils.formatting import format_bus_arrivals
        arrivals = [
            {"line": "204", "destination": "A", "time": "1 min", "minutes": 1},
            {"line": "300", "destination": "B", "time": "2 min", "minutes": 2},
        ]
        text = format_bus_arrivals("BCM2", "Bolhão", arrivals)
        assert "204" in text and "300" in text


# ===================================================================
# 3. Alerts: no fabrication, and network-wide != every line
# ===================================================================

class TestAlertsHonesty:

    def setup_method(self):
        import bot.services.alerts as alerts
        alerts.reset_cache()

    def test_no_fabricated_fallback_list_exists(self):
        import bot.services.alerts as alerts
        assert not hasattr(alerts, "_FALLBACK_ALERTS")

    def test_no_module_level_alert_data(self):
        """No hardcoded alert dicts may live in the module at all."""
        import bot.services.alerts as alerts
        for name in dir(alerts):
            if name.startswith("__"):
                continue
            value = getattr(alerts, name)
            if not isinstance(value, (list, tuple)):
                continue
            for item in value:
                assert not (isinstance(item, dict) and "title" in item), (
                    f"alerts.{name} contains a hardcoded alert: {item}"
                )

    @pytest.mark.asyncio
    async def test_all_sources_down_is_empty_and_flagged(self):
        from bot.services.alerts import get_active_alerts
        with patch("bot.services.alerts._fetch_stcp_alerts", new_callable=AsyncMock,
                   side_effect=RuntimeError("down")), \
             patch("bot.services.alerts._fetch_metro_alerts", new_callable=AsyncMock,
                   side_effect=RuntimeError("down")):
            result = await get_active_alerts()
        assert list(result) == []
        assert result.source_available is False
        assert not any(a.get("source") == "fallback" for a in result)

    @pytest.mark.asyncio
    async def test_status_message_says_could_not_check(self):
        from bot.services.alerts import get_alerts_status
        with patch("bot.services.alerts._fetch_stcp_alerts", new_callable=AsyncMock,
                   side_effect=RuntimeError("down")), \
             patch("bot.services.alerts._fetch_metro_alerts", new_callable=AsyncMock,
                   side_effect=RuntimeError("down")):
            status = await get_alerts_status()
        assert status["source_available"] is False
        assert "Não foi possível verificar" in status["message_pt"]
        assert "could not be checked" in status["message_en"]
        assert status["alerts"] == []

    @pytest.mark.asyncio
    async def test_status_message_distinguishes_genuine_quiet(self):
        from bot.services.alerts import get_alerts_status
        with patch("bot.services.alerts._fetch_stcp_alerts", new_callable=AsyncMock,
                   return_value=[]), \
             patch("bot.services.alerts._fetch_metro_alerts", new_callable=AsyncMock,
                   return_value=[]):
            status = await get_alerts_status()
        assert status["source_available"] is True
        assert "Sem alertas" in status["message_pt"]

    @pytest.mark.asyncio
    async def test_source_failure_is_negative_cached(self):
        import bot.services.alerts as alerts
        fetch = AsyncMock(side_effect=RuntimeError("down"))
        with patch("bot.services.alerts._fetch_stcp_alerts", fetch), \
             patch("bot.services.alerts._fetch_metro_alerts", new_callable=AsyncMock,
                   side_effect=RuntimeError("down")):
            await alerts.get_active_alerts()
            calls_after_first = fetch.await_count
            await alerts.get_active_alerts()
            assert fetch.await_count == calls_after_first  # no retry storm

    def test_empty_affected_lines_means_network_wide(self):
        from bot.services.alerts import (_make_alert, is_network_wide,
                                         SCOPE_NETWORK, SCOPE_LINE, TYPE_INFO)
        generic = _make_alert("g", TYPE_INFO, "Aviso geral", "")
        assert generic["scope"] == SCOPE_NETWORK
        assert is_network_wide(generic) is True

        specific = _make_alert("s", TYPE_INFO, "Linha D", "",
                               affected_lines=["D"])
        assert specific["scope"] == SCOPE_LINE
        assert is_network_wide(specific) is False

    @pytest.mark.asyncio
    async def test_network_wide_alert_can_be_excluded_from_line_query(self):
        import bot.services.alerts as alerts
        generic = alerts._make_alert("g", alerts.TYPE_INFO, "Aviso geral", "")
        line_d = alerts._make_alert("d", alerts.TYPE_INFO, "Linha D", "",
                                    affected_lines=["D"])
        alerts._cache.set(alerts.ALERTS_CACHE_KEY, [generic, line_d], ttl=300)

        with_generic = await alerts.get_alerts_for_line("A")
        assert [a["id"] for a in with_generic] == ["g"]

        without_generic = await alerts.get_alerts_for_line(
            "A", include_network_wide=False)
        assert list(without_generic) == []

        only_d = await alerts.get_alerts_for_line("D", include_network_wide=False)
        assert [a["id"] for a in only_d] == ["d"]

    def test_line_badge_does_not_fire_for_generic_alert(self):
        from bot.services.alerts import _make_alert, has_alerts_for_line, TYPE_INFO
        generic = [_make_alert("g", TYPE_INFO, "Aviso geral", "")]
        # A network-wide notice must not badge every single line by default.
        assert has_alerts_for_line(generic, "A") is False
        assert has_alerts_for_line(generic, "A", include_network_wide=True) is True

    def test_stcp_parser_extracts_lines_and_dates(self):
        from bot.services.alerts import _parse_stcp_service_changes
        html = '''
        <div class="list-changes">
        <div class="card regular-shadow"><div class="card-body">
          <div class="date">ENTRE DIA 27 E 29 JULHO 2026</div>
          <span class="list-change-title">ALTERA&Ccedil;&Atilde;O PERCURSO - OBRAS - R. FORMOSA</span>
          <div class="list-lines"><div class="line csp-inline-1" >305</div>
          <div class="line csp-inline-2" >7M</div></div>
          <div class="resume"></div>
          <a href="/pt/viajar/alteracoes-de-servico/obras-formosa" class="view-details">Ver</a>
        </div></div></div>
        '''
        parsed = _parse_stcp_service_changes(html)
        assert len(parsed) == 1
        alert = parsed[0]
        assert alert["affected_lines"] == ["305", "7M"]
        assert alert["scope"] == "line"
        assert alert["end_time"].startswith("2026-07-29")
        assert alert["url"].startswith("https://stcp.pt/")

    def test_open_ended_notice_gets_no_invented_end_date(self):
        from bot.services.alerts import _parse_closed_end_date
        assert _parse_closed_end_date("A PARTIR 24 JULHO 2026") is None
        assert _parse_closed_end_date("DESDE 11 JANEIRO 2023") is None
        assert _parse_closed_end_date("DIA 27 JULHO 2026").startswith("2026-07-27")

    def test_line_letter_extraction_ignores_portuguese_conjunction(self):
        """"linha e outros" must not be read as Line E."""
        from bot.services.alerts import _extract_lines
        assert _extract_lines("informação sobre a linha e outros assuntos") == []
        assert _extract_lines("Obras na Linha D") == ["D"]
        assert _extract_lines("Encerramento da Linha Amarela") == ["D"]

    def test_metro_rss_ignores_pr_news(self):
        """PR items whose body merely mentions 'manutenção' are not alerts."""
        from bot.services.alerts import _parse_metro_rss
        recent = (datetime.now(timezone.utc) - timedelta(days=1))
        pubdate = recent.strftime("%a, %d %b %Y %H:%M:%S +0000")
        xml = f'''<?xml version="1.0"?><rss version="2.0"><channel>
        <item><title>Concurso de subconcess&#227;o lan&#231;ado hoje</title>
        <description>O caderno de encargos prev&#234; manuten&#231;&#227;o da frota.</description>
        <pubDate>{pubdate}</pubDate><link>http://x/1</link></item>
        <item><title>Interrup&#231;&#227;o na Linha B este fim de semana</title>
        <description>Obras entre duas esta&#231;&#245;es.</description>
        <pubDate>{pubdate}</pubDate><link>http://x/2</link></item>
        </channel></rss>'''
        parsed = _parse_metro_rss(xml)
        titles = [a["title"] for a in parsed]
        assert any("Interrupção" in t for t in titles)
        assert not any("Concurso" in t for t in titles)

    def test_metro_rss_ignores_stale_items(self):
        from bot.services.alerts import _parse_metro_rss
        old = (datetime.now(timezone.utc) - timedelta(days=400))
        pubdate = old.strftime("%a, %d %b %Y %H:%M:%S +0000")
        xml = f'''<?xml version="1.0"?><rss version="2.0"><channel>
        <item><title>Interrup&#231;&#227;o na Linha B</title>
        <description>Antigo</description><pubDate>{pubdate}</pubDate>
        <link>http://x/1</link></item></channel></rss>'''
        assert _parse_metro_rss(xml) == []


# ===================================================================
# 4. Accessibility: no invented live status
# ===================================================================

class TestAccessibilityHonesty:

    def test_no_station_claims_maintenance(self):
        from bot.services.accessibility import ACCESSIBILITY
        assert ACCESSIBILITY  # dataset is populated
        assert all(d["elevator_status"] != "maintenance"
                   for d in ACCESSIBILITY.values())

    def test_maintenance_search_returns_nothing_without_a_source(self):
        from bot.services.accessibility import (search_accessible_features,
                                                has_live_elevator_status)
        assert has_live_elevator_status() is False
        assert search_accessible_features("elevator_maintenance") == []

    def test_data_carries_source_and_date(self):
        from bot.services.accessibility import get_station_accessibility
        data = get_station_accessibility("Bolhão")
        assert data["data_source"]
        assert data["data_date"]
        assert data["verified_live"] is False

    def test_note_points_to_official_information(self):
        from bot.services.accessibility import get_data_source_note
        for lang in ("pt", "en"):
            note = get_data_source_note(lang)
            assert "metrodoporto" in note.lower()
            assert note

    def test_no_hardcoded_maintenance_list_in_source(self):
        from pathlib import Path
        import bot.services.accessibility as mod
        source = Path(mod.__file__).read_text(encoding="utf-8")
        # The invented station names must not survive as data.
        assert '_MAINTENANCE_STATIONS = {' not in source
        assert 'Elevador em manutenção. Use a rampa' not in source


# ===================================================================
# 5. Events: timezone correctness and stale-dataset detection
# ===================================================================

class TestEventsTimezone:

    def test_today_uses_europe_lisbon_not_host_tz(self):
        import bot.services.events as events
        expected = datetime.now(ZoneInfo("Europe/Lisbon")).date()
        assert events.today_in_porto() == expected

    def test_getters_do_not_use_host_local_date(self):
        """Just after midnight in Lisbon, a UTC-behind host must not lag a day."""
        import bot.services.events as events
        lisbon_midnight = datetime(2026, 7, 15, 0, 30,
                                   tzinfo=ZoneInfo("Europe/Lisbon"))
        with patch("bot.services.events.datetime") as mock_dt:
            mock_dt.now.return_value = lisbon_midnight
            assert events.today_in_porto() == date(2026, 7, 15)
        mock_dt.now.assert_called_with(events.PORTO_TZ)

    def test_no_naive_date_today_in_source(self):
        from pathlib import Path
        import bot.services.events as events
        source = Path(events.__file__).read_text(encoding="utf-8")
        assert "date.today()" not in source


class TestEventsStaleness:

    def test_dataset_end_date_is_the_latest_event_end(self):
        import bot.services.events as events
        assert events.dataset_end_date() == max(e.end_date for e in events.EVENTS)

    def test_stale_detected_after_last_event(self):
        import bot.services.events as events
        end = events.dataset_end_date()
        assert events.is_dataset_stale(end) is False
        assert events.is_dataset_stale(end + timedelta(days=1)) is True

    def test_stale_period_reports_no_data_state(self):
        import bot.services.events as events
        far_future = date(2099, 1, 1)
        status = events.get_events_status(today=far_future)
        assert status["state"] == events.STATE_NO_DATA
        assert status["stale"] is True
        assert status["today"] == []
        assert status["upcoming"] == []
        # Must read as "no data", not as "there are no events".
        assert "Sem dados de eventos" in status["message_pt"]
        assert "No event data available" in status["message_en"]

    def test_stale_query_logs_a_warning(self, caplog):
        import logging
        import bot.services.events as events
        with caplog.at_level(logging.WARNING, logger="bot.services.events"):
            events.get_todays_events(today=date(2099, 1, 1))
        assert any("stale" in r.message.lower() or "stale" in r.getMessage().lower()
                   for r in caplog.records)

    def test_ok_and_none_today_states_are_distinguishable(self):
        import bot.services.events as events
        first = min(events.EVENTS, key=lambda e: e.start_date)
        on_day = events.get_events_status(today=first.start_date)
        assert on_day["state"] == events.STATE_OK

        before = events.get_events_status(
            today=first.start_date - timedelta(days=1))
        assert before["state"] == events.STATE_NONE_TODAY

    def test_no_hardcoded_last_season_fixtures(self):
        """Static football fixtures go stale after a season; they must be gone."""
        import bot.services.events as events
        curated_football = [e for e in events._CURATED_EVENTS
                            if e.category == "football"]
        assert curated_football == []

    @pytest.mark.asyncio
    async def test_fixture_fetch_failure_adds_no_invented_matches(self):
        import bot.services.events as events
        before = list(events.EVENTS)
        with patch("bot.services.events.fetch_fcporto_fixtures",
                   new_callable=AsyncMock, side_effect=RuntimeError("down")):
            ok = await events.refresh_events(force=True)
        assert ok is False
        assert list(events.EVENTS) == before

    @pytest.mark.asyncio
    async def test_fixtures_are_merged_when_available(self):
        import bot.services.events as events
        fixture = events.Event(
            name_pt="FC Porto vs Teste", name_en="FC Porto vs Test",
            venue_pt=events.DRAGAO_VENUE, venue_en=events.DRAGAO_VENUE,
            date_info_pt="1 de setembro", date_info_en="September 1",
            nearest_station=events.DRAGAO_VENUE,
            transport_tip_pt="Metro", transport_tip_en="Metro",
            category="football", emoji="⚽",
            start_date=date(2026, 9, 1), end_date=date(2026, 9, 1),
            source=events.SOURCE_FCPORTO,
        )
        original = list(events.EVENTS)
        try:
            with patch("bot.services.events.fetch_fcporto_fixtures",
                       new_callable=AsyncMock, return_value=[fixture]):
                assert await events.refresh_events(force=True) is True
            assert fixture in events.EVENTS
            assert events.get_events("football") == [fixture]
            # Curated entries survive the merge.
            assert all(e in events.EVENTS for e in events._CURATED_EVENTS)
        finally:
            events.EVENTS[:] = original

    def test_only_dragao_fixtures_are_kept(self):
        import bot.services.events as events
        away = {"date": "2026-08-01 19:15:00",
                "place": {"name": "Estádio Cidade de Coimbra"},
                "home_team": {"short_name": "FC Porto"},
                "away_team": {"short_name": "SCU Torreense"}}
        home = {"date": "2026-08-09 17:00:00", "has_hour": "1",
                "place": {"name": "Estádio do Dragão"},
                "home_team": {"short_name": "FC Porto"},
                "away_team": {"short_name": "FC Alverca"},
                "competition": {"top_level": {"name": "Primeira Liga"}}}
        assert events._parse_fixture(away) is None
        parsed = events._parse_fixture(home)
        assert parsed is not None
        assert parsed.start_date == date(2026, 8, 9)
        assert parsed.category == "football"
        assert parsed.source == events.SOURCE_FCPORTO
        assert "17h00" in parsed.date_info_pt
