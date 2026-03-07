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

    def test_with_arrivals(self):
        arrivals = [
            {"line": "204", "destination": "Hosp. S. João", "time": "3 minutos"},
            {"line": "508", "destination": "Casa da Música", "time": "6 minutos"},
        ]
        result = format_bus_arrivals("BCM2", "Boavista", arrivals)
        assert "BCM2" in result
        assert "204" in result
        assert "508" in result
        assert "Próximas passagens" in result

    def test_arrival_contains_stop_name(self):
        result = format_bus_arrivals("TEST1", "Test Stop", [
            {"line": "1", "destination": "Dest", "time": "5 min"},
        ])
        assert "Test Stop" in result


class TestFormatMetroSchedule:
    def test_no_departures(self):
        result = format_metro_schedule("Trindade", "🔵 Linha A", [])
        assert "Trindade" in result
        assert "Sem informação" in result

    def test_with_departures(self):
        deps = [
            {"direction": "Senhor de Matosinhos", "time": "~15:30"},
            {"direction": "Estádio do Dragão", "time": "~15:35"},
        ]
        result = format_metro_schedule("Trindade", "🔵 Linha A", deps)
        assert "Trindade" in result
        assert "Próximas partidas" in result


class TestFormatRouteInfo:
    def test_basic_route(self):
        stops = ["Stop A", "Stop B", "Stop C"]
        result = format_route_info("204", "Hosp. S. João - Foz", stops)
        assert "204" in result
        assert "Stop A" in result
        assert "Stop C" in result


class TestFormatMetroLineInfo:
    def test_basic_line(self):
        line_data = {"emoji": "🔵", "name": "Linha Azul", "route": "A ↔ B"}
        stations = ["Station 1", "Station 2", "Station 3"]
        result = format_metro_line_info("A", line_data, stations)
        assert "Linha Azul" in result
        assert "Station 1" in result
        assert "3" in result  # station count
