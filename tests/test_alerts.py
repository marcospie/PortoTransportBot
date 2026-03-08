"""Comprehensive tests for the service alerts feature."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.services.alerts import (
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    SEVERITY_LOW,
    TYPE_DELAY,
    TYPE_DISRUPTION,
    TYPE_ENGINEERING,
    TYPE_INFO,
    _make_alert,
    _sort_alerts,
    get_active_alerts,
    get_alerts_for_line,
    get_alerts_for_stop,
    has_alerts_for_line,
    has_alerts_for_stop,
    _cache,
    ALERTS_CACHE_KEY,
)
from bot.handlers.alerts import (
    _format_alert,
    format_alerts_message,
    alertas_command,
    alerts_menu_callback,
    alerts_filter_callback,
)
from bot.keyboards.inline import alerts_keyboard, main_menu_keyboard


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


SAMPLE_ALERTS = [
    _make_alert("a1", TYPE_DISRUPTION, "Linha A interrompida",
                "Interrupção entre Trindade e Bolhão",
                affected_lines=["A"], severity=SEVERITY_HIGH),
    _make_alert("a2", TYPE_DELAY, "Atrasos na linha 200",
                "Atrasos de 10 min na linha 200",
                affected_lines=["200"], severity=SEVERITY_MEDIUM),
    _make_alert("a3", TYPE_INFO, "Novo horário de verão",
                "Horários de verão em vigor a partir de 1 de junho",
                severity=SEVERITY_LOW),
    _make_alert("a4", TYPE_ENGINEERING, "Obras na paragem BCM2",
                "Paragem BCM2 temporariamente desativada",
                affected_stops=["BCM2"], severity=SEVERITY_MEDIUM),
]


# ===================================================================
# Alert Service Tests
# ===================================================================

class TestAlertService:

    def setup_method(self):
        _cache.clear()

    def test_make_alert_creates_valid_dict(self):
        """Test _make_alert returns dict with all required fields."""
        alert = _make_alert("test1", TYPE_DELAY, "Test Title", "Test Desc",
                           affected_lines=["A", "B"], severity=SEVERITY_HIGH)
        assert alert["id"] == "test1"
        assert alert["type"] == TYPE_DELAY
        assert alert["title"] == "Test Title"
        assert alert["description"] == "Test Desc"
        assert alert["affected_lines"] == ["A", "B"]
        assert alert["affected_stops"] == []
        assert alert["severity"] == SEVERITY_HIGH
        assert alert["source"] == "api"

    def test_make_alert_defaults(self):
        """Test _make_alert uses sensible defaults."""
        alert = _make_alert("x", TYPE_INFO, "T", "D")
        assert alert["affected_lines"] == []
        assert alert["affected_stops"] == []
        assert alert["start_time"] is None
        assert alert["end_time"] is None
        assert alert["severity"] == SEVERITY_LOW

    def test_sort_alerts_by_severity(self):
        """Test alerts are sorted high -> medium -> low."""
        alerts = [
            _make_alert("low", TYPE_INFO, "Low", "", severity=SEVERITY_LOW),
            _make_alert("high", TYPE_DISRUPTION, "High", "", severity=SEVERITY_HIGH),
            _make_alert("med", TYPE_DELAY, "Med", "", severity=SEVERITY_MEDIUM),
        ]
        sorted_alerts = _sort_alerts(alerts)
        assert sorted_alerts[0]["id"] == "high"
        assert sorted_alerts[1]["id"] == "med"
        assert sorted_alerts[2]["id"] == "low"

    @pytest.mark.asyncio
    async def test_get_active_alerts_uses_cache(self):
        """Test that get_active_alerts returns cached results on second call."""
        _cache.set(ALERTS_CACHE_KEY, SAMPLE_ALERTS, ttl=300)
        result = await get_active_alerts()
        assert result == SAMPLE_ALERTS

    @pytest.mark.asyncio
    async def test_get_active_alerts_fallback(self):
        """Test that get_active_alerts returns fallback when APIs fail."""
        with patch("bot.services.alerts._fetch_stcp_alerts", new_callable=AsyncMock, return_value=[]), \
             patch("bot.services.alerts._fetch_metro_alerts", new_callable=AsyncMock, return_value=[]):
            result = await get_active_alerts()
            assert len(result) > 0  # Should have fallback alerts
            assert any(a.get("source") == "fallback" for a in result)

    @pytest.mark.asyncio
    async def test_get_alerts_for_line(self):
        """Test filtering alerts by line."""
        _cache.set(ALERTS_CACHE_KEY, SAMPLE_ALERTS, ttl=300)
        result = await get_alerts_for_line("A")
        assert any(a["id"] == "a1" for a in result)
        # a3 has no affected_lines so it matches all lines
        assert any(a["id"] == "a3" for a in result)
        # a2 affects line 200, not A
        assert not any(a["id"] == "a2" for a in result)

    @pytest.mark.asyncio
    async def test_get_alerts_for_line_case_insensitive(self):
        """Test line filtering is case-insensitive."""
        _cache.set(ALERTS_CACHE_KEY, SAMPLE_ALERTS, ttl=300)
        result = await get_alerts_for_line("a")
        assert any(a["id"] == "a1" for a in result)

    @pytest.mark.asyncio
    async def test_get_alerts_for_stop(self):
        """Test filtering alerts by stop."""
        _cache.set(ALERTS_CACHE_KEY, SAMPLE_ALERTS, ttl=300)
        result = await get_alerts_for_stop("BCM2")
        assert any(a["id"] == "a4" for a in result)

    def test_has_alerts_for_line_sync(self):
        """Test synchronous line alert check."""
        assert has_alerts_for_line(SAMPLE_ALERTS, "A") is True
        assert has_alerts_for_line(SAMPLE_ALERTS, "Z") is False

    def test_has_alerts_for_stop_sync(self):
        """Test synchronous stop alert check."""
        assert has_alerts_for_stop(SAMPLE_ALERTS, "BCM2") is True
        assert has_alerts_for_stop(SAMPLE_ALERTS, "XYZ9") is False


# ===================================================================
# Alert Formatting Tests
# ===================================================================

class TestAlertFormatting:

    def test_format_alert_contains_title(self):
        """Test that formatted alert contains the title."""
        alert = SAMPLE_ALERTS[0]
        result = _format_alert(alert, "pt")
        assert "Linha A interrompida" in result

    def test_format_alert_contains_severity(self):
        """Test that formatted alert contains severity label."""
        alert = SAMPLE_ALERTS[0]
        result = _format_alert(alert, "pt")
        assert "Severidade" in result

    def test_format_alert_contains_affected_lines(self):
        """Test that formatted alert shows affected lines."""
        alert = SAMPLE_ALERTS[0]
        result = _format_alert(alert, "pt")
        assert "A" in result

    def test_format_alerts_message_no_alerts(self):
        """Test message when there are no alerts."""
        result = format_alerts_message([], "pt")
        assert "Sem alertas" in result

    def test_format_alerts_message_with_alerts(self):
        """Test message with multiple alerts."""
        result = format_alerts_message(SAMPLE_ALERTS, "pt")
        assert "Alertas" in result
        assert "Linha A interrompida" in result
        assert "Atrasos na linha 200" in result

    def test_format_alerts_message_en(self):
        """Test English message when no alerts."""
        result = format_alerts_message([], "en")
        assert "No alerts" in result


# ===================================================================
# Alert Handler Tests
# ===================================================================

class TestAlertHandlers:

    @pytest.mark.asyncio
    async def test_alertas_command(self):
        """Test /alertas command sends a message with alerts."""
        update = _make_update()
        context = _make_context()

        with patch("bot.handlers.alerts.get_active_alerts", new_callable=AsyncMock,
                    return_value=SAMPLE_ALERTS):
            await alertas_command(update, context)

        update.message.reply_text.assert_called_once()
        call_args = update.message.reply_text.call_args
        assert "MarkdownV2" in str(call_args)

    @pytest.mark.asyncio
    async def test_alerts_menu_callback(self):
        """Test menu:alerts callback edits message with alerts."""
        update = _make_update()
        context = _make_context()

        with patch("bot.handlers.alerts.get_active_alerts", new_callable=AsyncMock,
                    return_value=SAMPLE_ALERTS):
            await alerts_menu_callback(update, context)

        update.callback_query.answer.assert_called_once()
        update.callback_query.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_alerts_filter_callback_delays(self):
        """Test filtering alerts by type via callback."""
        update = _make_update()
        update.callback_query.data = "alerts:filter:delay"
        context = _make_context()

        with patch("bot.handlers.alerts.get_active_alerts", new_callable=AsyncMock,
                    return_value=SAMPLE_ALERTS):
            await alerts_filter_callback(update, context)

        update.callback_query.edit_message_text.assert_called_once()
        call_text = update.callback_query.edit_message_text.call_args[0][0]
        # Should contain delay alert but not disruption
        assert "Atrasos na linha 200" in call_text

    @pytest.mark.asyncio
    async def test_alerts_filter_callback_all(self):
        """Test 'all' filter shows all alerts."""
        update = _make_update()
        update.callback_query.data = "alerts:filter:all"
        context = _make_context()

        with patch("bot.handlers.alerts.get_active_alerts", new_callable=AsyncMock,
                    return_value=SAMPLE_ALERTS):
            await alerts_filter_callback(update, context)

        call_text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Linha A interrompida" in call_text
        assert "Atrasos na linha 200" in call_text


# ===================================================================
# Keyboard Tests
# ===================================================================

class TestAlertKeyboards:

    def test_alerts_keyboard_has_filter_buttons(self):
        """Test alerts keyboard contains filter and back buttons."""
        kb = alerts_keyboard("pt")
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "alerts:filter:all" in all_data
        assert "alerts:filter:delay" in all_data
        assert "alerts:filter:disruption" in all_data
        assert "alerts:filter:engineering" in all_data
        assert "menu:main" in all_data

    def test_main_menu_has_alerts_button(self):
        """Test main menu keyboard contains alerts button."""
        kb = main_menu_keyboard("pt")
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row
                    if btn.callback_data]
        assert "menu:alerts" in all_data

    def test_alerts_keyboard_en(self):
        """Test alerts keyboard works with English lang."""
        kb = alerts_keyboard("en")
        all_text = [btn.text for row in kb.inline_keyboard for btn in row]
        # Should contain English labels
        assert any("All" in text for text in all_text)


# ===================================================================
# Edge Case / Expired Alert Tests
# ===================================================================

class TestAlertEdgeCases:

    def setup_method(self):
        _cache.clear()

    @pytest.mark.asyncio
    async def test_expired_alerts_filtered(self):
        """Test that expired alerts are excluded."""
        expired_alert = _make_alert(
            "expired", TYPE_INFO, "Old alert", "Already expired",
            end_time="2020-01-01T00:00:00",
            severity=SEVERITY_LOW,
        )
        with patch("bot.services.alerts._fetch_stcp_alerts", new_callable=AsyncMock,
                    return_value=[expired_alert]), \
             patch("bot.services.alerts._fetch_metro_alerts", new_callable=AsyncMock,
                    return_value=[]):
            result = await get_active_alerts()
            assert not any(a["id"] == "expired" for a in result)

    @pytest.mark.asyncio
    async def test_get_alerts_for_stop_no_match(self):
        """Test stop query returns empty when no alerts match."""
        _cache.set(ALERTS_CACHE_KEY, [
            _make_alert("x", TYPE_DELAY, "T", "D",
                        affected_lines=["A"], affected_stops=["XYZ1"]),
        ], ttl=300)
        result = await get_alerts_for_stop("BCM2")
        assert len(result) == 0
