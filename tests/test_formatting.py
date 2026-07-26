"""Tests for formatting utilities."""

from bot.utils.formatting import (
    escape_md,
    format_bus_arrivals,
    format_metro_schedule,
    format_route_info,
    format_metro_line_info,
)


class TestEscapeMd:
    def test_no_special_chars(self):
        assert escape_md("hello world") == "hello world"

    def test_asterisk(self):
        assert escape_md("*bold*") == "\\*bold\\*"

    def test_underscore(self):
        assert escape_md("_italic_") == "\\_italic\\_"

    def test_parentheses(self):
        assert escape_md("(test)") == "\\(test\\)"

    def test_multiple_special_chars(self):
        result = escape_md("Hello *world* (test) [link]")
        assert "\\*" in result
        assert "\\(" in result
        assert "\\[" in result

    def test_dot(self):
        assert escape_md("1.2.3") == "1\\.2\\.3"

    def test_empty_string(self):
        assert escape_md("") == ""

    def test_numeric(self):
        assert escape_md(123) == "123"


class TestFormatBusArrivals:
    def test_no_arrivals(self):
        result = format_bus_arrivals("BCM2", "Boavista", [])
        assert "BCM2" in result
        assert "Boavista" in result
        assert "Sem autocarros" in result
        assert "━━━━" in result

    def test_with_arrivals(self):
        arrivals = [
            {"line": "204", "destination": "Hosp. S. João", "time": "3 minutos", "minutes": 3},
            {"line": "508", "destination": "Casa da Música", "time": "6 minutos", "minutes": 6},
        ]
        result = format_bus_arrivals("BCM2", "Boavista", arrivals)
        assert "BCM2" in result
        assert "204" in result
        assert "508" in result
        assert "Atualizado" in result

    def test_arrival_contains_stop_name(self):
        result = format_bus_arrivals("TEST1", "Test Stop", [
            {"line": "1", "destination": "Dest", "time": "5 min", "minutes": 5},
        ])
        assert "Test Stop" in result

    def test_urgency_grouping(self):
        arrivals = [
            {"line": "204", "destination": "Marquês", "time": "2 minutos", "minutes": 2},
            {"line": "300", "destination": "Campainha", "time": "8 minutos", "minutes": 8},
        ]
        result = format_bus_arrivals("BCM2", "Bolhao", arrivals)
        assert "A chegar" in result
        assert "Seguintes" in result

    def test_no_urgency_split_when_all_same_group(self):
        arrivals = [
            {"line": "204", "destination": "Marquês", "time": "8 minutos", "minutes": 8},
            {"line": "300", "destination": "Campainha", "time": "12 minutos", "minutes": 12},
        ]
        result = format_bus_arrivals("BCM2", "Bolhao", arrivals)
        assert "A chegar:" not in result
        assert "Seguintes:" not in result

    def test_status_emoji_preserved(self):
        arrivals = [
            {"line": "204", "destination": "Marquês", "time": "✅ 3 minutos", "minutes": 3},
        ]
        result = format_bus_arrivals("BCM2", "Bolhao", arrivals)
        assert "✅" in result

    def test_compact_single_line_format(self):
        arrivals = [
            {"line": "204", "destination": "Marquês", "time": "8 minutos", "minutes": 8},
        ]
        result = format_bus_arrivals("BCM2", "Bolhao", arrivals)
        # Each arrival should be on a single line with dash separator
        assert "—" in result
        # Should NOT have per-row bus emoji
        assert "🚌" not in result
        # Should NOT have per-row timer emoji
        assert "⏱" not in result


class TestFormatMetroSchedule:
    def test_no_departures(self):
        result = format_metro_schedule("Trindade", "🔵 Linha A", [])
        assert "Trindade" in result
        assert "Sem informação" in result
        assert "━━━━" in result

    def test_with_departures(self):
        deps = [
            {"direction": "Senhor de Matosinhos", "time": "~15:30"},
            {"direction": "Estádio do Dragão", "time": "~15:35"},
        ]
        result = format_metro_schedule("Trindade", "🔵 Linha A", deps)
        assert "Trindade" in result
        # Timetable data (no realtime flag) must not claim to be live.
        assert "Horário previsto" in result
        assert "Atualizado" not in result

    def test_realtime_departures_label(self):
        deps = [
            {"direction": "Senhor de Matosinhos", "time": "3 min", "realtime": True},
        ]
        result = format_metro_schedule("Trindade", "🔵 Linha A", deps)
        assert "Atualizado" in result

    def test_estimated_departures_label(self):
        deps = [
            {"direction": "Senhor de Matosinhos", "time": "~15:30", "estimated": True},
        ]
        result = format_metro_schedule("Trindade", "🔵 Linha A", deps)
        assert "Estimativa" in result

    def test_compact_single_line_format(self):
        deps = [
            {"direction": "Senhor de Matosinhos", "time": "~15:30"},
        ]
        result = format_metro_schedule("Trindade", "🔵 Linha A", deps)
        # Each departure on single line with dash separator
        assert "—" in result
        # Should NOT have per-row emoji
        assert "🚃" not in result
        assert "⏱" not in result


class TestFormatRouteInfo:
    def test_basic_route(self):
        stops = ["Stop A", "Stop B", "Stop C"]
        result = format_route_info("204", "Hosp. S. João - Foz", stops)
        assert "204" in result
        assert "Stop A" in result
        assert "Stop C" in result

    def test_stops_use_monospace(self):
        stops = ["Stop A", "Stop B"]
        result = format_route_info("204", "Direction", stops)
        # Stops should be wrapped in backticks for monospace
        assert "`" in result


class TestFormatMetroLineInfo:
    def test_basic_line(self):
        line_data = {"emoji": "🔵", "name": "Linha Azul", "route": "A ↔ B"}
        stations = ["Station 1", "Station 2", "Station 3"]
        result = format_metro_line_info("A", line_data, stations)
        assert "Linha Azul" in result
        assert "Station 1" in result
        assert "3" in result  # station count

    def test_visual_map_connector(self):
        line_data = {"emoji": "🔵", "name": "Linha Azul", "route": "A ↔ B"}
        stations = ["Station 1", "Station 2"]
        result = format_metro_line_info("A", line_data, stations)
        assert "│" in result  # vertical connector between stations
