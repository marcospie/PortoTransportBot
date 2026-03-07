"""Tests for keyboard builders."""

from telegram import InlineKeyboardMarkup

from bot.keyboards.inline import (
    main_menu_keyboard,
    bus_menu_keyboard,
    bus_stop_results_keyboard,
    bus_stop_actions_keyboard,
    metro_menu_keyboard,
    metro_lines_keyboard,
    metro_station_results_keyboard,
    favorites_keyboard,
)


class TestMainMenuKeyboard:
    def test_returns_markup(self):
        kb = main_menu_keyboard()
        assert isinstance(kb, InlineKeyboardMarkup)

    def test_has_bus_and_metro(self):
        kb = main_menu_keyboard()
        all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert any("Autocarro" in t for t in all_texts)
        assert any("Metro" in t for t in all_texts)


class TestBusMenuKeyboard:
    def test_returns_markup(self):
        kb = bus_menu_keyboard()
        assert isinstance(kb, InlineKeyboardMarkup)

    def test_has_search_option(self):
        kb = bus_menu_keyboard()
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "bus:search" in all_data

    def test_has_back_button(self):
        kb = bus_menu_keyboard()
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "menu:main" in all_data


class TestBusStopResults:
    def test_empty_stops(self):
        kb = bus_stop_results_keyboard([])
        # Should still have back button
        assert len(kb.inline_keyboard) >= 1

    def test_with_stops(self):
        stops = [
            {"stop_id": "BCM2", "name": "Boavista"},
            {"stop_id": "TRIN2", "name": "Trindade"},
        ]
        kb = bus_stop_results_keyboard(stops)
        assert len(kb.inline_keyboard) >= 3  # 2 stops + back button

    def test_max_results(self):
        stops = [{"stop_id": f"S{i}", "name": f"Stop {i}"} for i in range(20)]
        kb = bus_stop_results_keyboard(stops)
        # Should show max 8 + back button
        assert len(kb.inline_keyboard) <= 9


class TestBusStopActions:
    def test_has_refresh(self):
        kb = bus_stop_actions_keyboard("BCM2")
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "bus:stop:BCM2" in all_data

    def test_has_favorite(self):
        kb = bus_stop_actions_keyboard("BCM2")
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert any("fav:add" in d for d in all_data)


class TestMetroMenuKeyboard:
    def test_returns_markup(self):
        kb = metro_menu_keyboard()
        assert isinstance(kb, InlineKeyboardMarkup)

    def test_has_search(self):
        kb = metro_menu_keyboard()
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "metro:search" in all_data


class TestMetroLinesKeyboard:
    def test_has_all_lines(self):
        kb = metro_lines_keyboard()
        from bot.config import METRO_LINES
        # Should have one button per line + back
        assert len(kb.inline_keyboard) == len(METRO_LINES) + 1


class TestMetroStationResults:
    def test_with_stations(self):
        stations = [
            {
                "name": "Trindade",
                "lines": [
                    {"code": "A", "name": "Linha Azul", "emoji": "🔵"},
                    {"code": "D", "name": "Linha Amarela", "emoji": "🟡"},
                ],
            }
        ]
        kb = metro_station_results_keyboard(stations)
        assert len(kb.inline_keyboard) >= 2  # 1 station + back


class TestFavoritesKeyboard:
    def test_empty_favorites(self):
        kb = favorites_keyboard([])
        assert isinstance(kb, InlineKeyboardMarkup)
        # Should have navigation buttons
        assert len(kb.inline_keyboard) >= 2

    def test_with_bus_favorite(self):
        favs = [{"type": "bus", "id": "BCM2", "name": "Boavista"}]
        kb = favorites_keyboard(favs)
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert any("bus:stop:BCM2" in d for d in all_data)

    def test_with_metro_favorite(self):
        favs = [{"type": "metro", "id": "Trindade", "name": "Trindade"}]
        kb = favorites_keyboard(favs)
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert any("metro:station:Trindade" in d for d in all_data)
