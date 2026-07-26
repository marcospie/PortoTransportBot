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

    def test_has_find_option(self):
        kb = bus_menu_keyboard()
        # Now uses switch_inline_query_current_chat for autocomplete
        all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert any("Pesquisar" in t for t in all_texts)

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
        # Now uses switch_inline_query_current_chat for autocomplete
        all_texts = [btn.text for row in kb.inline_keyboard for btn in row]
        assert any("Pesquisar" in t for t in all_texts)


class TestMetroLinesKeyboard:
    def test_has_all_lines(self):
        kb = metro_lines_keyboard()
        from bot.config import METRO_LINES
        # All line buttons should be present (shown in pairs)
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        for code in METRO_LINES:
            assert f"metro:line:{code}" in all_data


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


# ===================================================================
# Main menu completeness — zones and commuter used to be unreachable
# except by typing the command.
# ===================================================================

class TestMainMenuCompleteness:
    def test_has_zones_button(self):
        all_data = [btn.callback_data for row in main_menu_keyboard().inline_keyboard
                    for btn in row]
        assert "menu:zones" in all_data

    def test_has_commuter_button(self):
        all_data = [btn.callback_data for row in main_menu_keyboard().inline_keyboard
                    for btn in row]
        assert "menu:commuter" in all_data

    def test_every_registered_menu_entry_present(self):
        all_data = [btn.callback_data for row in main_menu_keyboard().inline_keyboard
                    for btn in row]
        for expected in ("menu:bus", "menu:metro", "menu:metrobus", "menu:trains",
                         "menu:favorites", "menu:events", "menu:weather",
                         "menu:alerts", "menu:accessibility", "menu:settings",
                         "menu:zones", "menu:commuter", "menu:help",
                         "plan:route", "tourist:menu"):
            assert expected in all_data, expected

    def test_zones_and_commuter_localized(self):
        from bot.utils.i18n import t
        for lang in ("pt", "en"):
            texts = [btn.text for row in main_menu_keyboard(lang).inline_keyboard
                     for btn in row]
            assert t("kb_zones", lang) in texts
            assert t("kb_commuter", lang) in texts

    def test_all_callback_data_within_64_bytes(self):
        for lang in ("pt", "en"):
            for row in main_menu_keyboard(lang).inline_keyboard:
                for btn in row:
                    if btn.callback_data:
                        assert len(btn.callback_data.encode("utf-8")) <= 64


# ===================================================================
# Favorites keyboard routes every type to its own handler
# ===================================================================

class TestFavoritesKeyboardRouting:
    """A saved train/MetroBus favorite used to open the METRO handler."""

    CASES = [
        ("bus", "BCM2", "bus:stop:BCM2", "🚌"),
        ("metro", "Trindade", "metro:station:Trindade", "🚇"),
        ("metrobus", "Boavista", "metrobus:stop:Boavista", "\U0001f68d"),
        ("train", "Porto-Campanha", "train:station:Porto-Campanha", "\U0001f686"),
    ]

    def test_each_type_routes_to_its_own_handler(self):
        for ftype, fid, expected_cb, _emoji in self.CASES:
            favs = [{"type": ftype, "id": fid, "name": fid}]
            kb = favorites_keyboard(favs)
            all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
            assert expected_cb in all_data, f"{ftype} should open {expected_cb}"

    def test_no_type_falls_through_to_metro(self):
        """Only metro favorites may produce a metro:station: callback."""
        for ftype, fid, _cb, _emoji in self.CASES:
            if ftype == "metro":
                continue
            kb = favorites_keyboard([{"type": ftype, "id": fid, "name": fid}])
            all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
            assert not any(d and d.startswith("metro:station:") for d in all_data), ftype

    def test_each_type_has_its_own_emoji(self):
        for ftype, fid, _cb, emoji in self.CASES:
            kb = favorites_keyboard([{"type": ftype, "id": fid, "name": fid}])
            texts = [btn.text for row in kb.inline_keyboard for btn in row]
            assert any(t.startswith(emoji) for t in texts), f"{ftype} -> {emoji}"

    def test_emojis_are_distinct_per_mode(self):
        emojis = {ftype: emoji for ftype, _f, _c, emoji in self.CASES}
        assert len(set(emojis.values())) == 4

    def test_every_favorite_keeps_a_delete_button(self):
        favs = [{"type": ftype, "id": fid, "name": fid}
                for ftype, fid, _c, _e in self.CASES]
        kb = favorites_keyboard(favs)
        removes = [btn.callback_data for row in kb.inline_keyboard for btn in row
                   if btn.callback_data and btn.callback_data.startswith("fav:remove:")]
        assert len(removes) == 4
        for ftype, fid, _c, _e in self.CASES:
            assert f"fav:remove:{ftype}:{fid}" in removes

    def test_callback_data_within_64_bytes_for_longest_names(self):
        """Accented names are multi-byte; every produced callback must fit."""
        from bot.services.cp import STATIONS as CP_STATIONS
        from bot.services.metro import STATIONS as METRO_STATIONS
        from bot.services.metrobus import STOPS as MB_STOPS

        favs = []
        favs += [{"type": "metro", "id": n, "name": n} for n in METRO_STATIONS]
        favs += [{"type": "train", "id": n, "name": n} for n in CP_STATIONS]
        favs += [{"type": "metrobus", "id": n, "name": n} for n in MB_STOPS]

        # favorites_keyboard renders 10 at a time; walk the whole corpus.
        for start in range(0, len(favs), 10):
            kb = favorites_keyboard(favs[start:start + 10])
            for row in kb.inline_keyboard:
                for btn in row:
                    if btn.callback_data:
                        assert len(btn.callback_data.encode("utf-8")) <= 64, btn.callback_data

    def test_overlong_name_never_yields_invalid_callback(self):
        long_id = "Ç" * 60
        kb = favorites_keyboard([{"type": "metro", "id": long_id, "name": long_id}])
        for row in kb.inline_keyboard:
            for btn in row:
                if btn.callback_data:
                    assert len(btn.callback_data.encode("utf-8")) <= 64

    def test_empty_state_offers_all_four_modes(self):
        kb = favorites_keyboard([])
        queries = [btn.switch_inline_query_current_chat
                   for row in kb.inline_keyboard for btn in row
                   if btn.switch_inline_query_current_chat is not None]
        assert set(queries) == {"bus ", "metro ", "metrobus ", "train "}


# ===================================================================
# Metro line detail keyboard — every station tappable + pagination
# ===================================================================

class TestMetroLineDetailKeyboard:
    def test_all_stations_tappable_without_pagination(self):
        from bot.keyboards.inline import metro_line_detail_keyboard
        from bot.services.metro import get_line_stations, STATIONS

        stations = get_line_stations("B")
        kb = metro_line_detail_keyboard("B", stations, stations_data=STATIONS)
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        for name in stations:
            assert f"metro:station:{name}" in all_data, name

    def test_mid_line_station_is_reachable(self):
        """The old keyboard only showed ~6 'key' stations."""
        from bot.keyboards.inline import metro_line_detail_keyboard
        from bot.services.metro import get_line_stations, STATIONS

        stations = get_line_stations("A")
        middle = stations[len(stations) // 2]
        kb = metro_line_detail_keyboard("A", stations, stations_data=STATIONS)
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert f"metro:station:{middle}" in all_data

    def test_no_pagination_buttons_when_page_is_none(self):
        from bot.keyboards.inline import metro_line_detail_keyboard
        from bot.services.metro import get_line_stations

        kb = metro_line_detail_keyboard("B", get_line_stations("B"))
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert not any(d and ":page:" in d for d in all_data)

    def test_pagination_limits_page_size(self):
        from bot.keyboards.inline import metro_line_detail_keyboard
        stations = [f"Station {i}" for i in range(25)]
        kb = metro_line_detail_keyboard("A", stations, page=0, per_page=10)
        station_btns = [btn for row in kb.inline_keyboard for btn in row
                        if btn.callback_data and btn.callback_data.startswith("metro:station:")]
        assert len(station_btns) == 10

    def test_pagination_next_and_prev(self):
        from bot.keyboards.inline import metro_line_detail_keyboard
        stations = [f"Station {i}" for i in range(25)]

        first = [btn.callback_data for row in
                 metro_line_detail_keyboard("A", stations, page=0, per_page=10).inline_keyboard
                 for btn in row]
        assert "metro:line:A:page:1" in first
        assert "metro:line:A:page:-1" not in first

        middle = [btn.callback_data for row in
                  metro_line_detail_keyboard("A", stations, page=1, per_page=10).inline_keyboard
                  for btn in row]
        assert "metro:line:A:page:0" in middle
        assert "metro:line:A:page:2" in middle

        last = [btn.callback_data for row in
                metro_line_detail_keyboard("A", stations, page=2, per_page=10).inline_keyboard
                for btn in row]
        assert "metro:line:A:page:1" in last
        assert "metro:line:A:page:3" not in last

    def test_pagination_covers_every_station(self):
        from bot.keyboards.inline import metro_line_detail_keyboard
        from bot.services.metro import get_line_stations

        stations = get_line_stations("C")
        seen = set()
        for page in range(10):
            kb = metro_line_detail_keyboard("C", stations, page=page, per_page=8)
            seen.update(btn.callback_data[len("metro:station:"):]
                        for row in kb.inline_keyboard for btn in row
                        if btn.callback_data and btn.callback_data.startswith("metro:station:"))
        assert seen == set(stations)

    def test_out_of_range_page_is_clamped(self):
        from bot.keyboards.inline import metro_line_detail_keyboard
        stations = [f"Station {i}" for i in range(25)]
        kb = metro_line_detail_keyboard("A", stations, page=99, per_page=10)
        station_btns = [btn for row in kb.inline_keyboard for btn in row
                        if btn.callback_data and btn.callback_data.startswith("metro:station:")]
        assert station_btns  # last page, not an empty keyboard

    def test_keeps_frequencies_and_back(self):
        from bot.keyboards.inline import metro_line_detail_keyboard
        from bot.services.metro import get_line_stations

        kb = metro_line_detail_keyboard("A", get_line_stations("A"))
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "metro:line_freq:A" in all_data
        assert "metro:lines" in all_data

    def test_all_callback_data_within_64_bytes_real_lines(self):
        from bot.config import METRO_LINES
        from bot.keyboards.inline import metro_line_detail_keyboard
        from bot.services.metro import get_line_stations, STATIONS

        for code in METRO_LINES:
            stations = get_line_stations(code)
            for page in (None, 0, 1, 2):
                kb = metro_line_detail_keyboard(code, stations,
                                                 stations_data=STATIONS, page=page)
                for row in kb.inline_keyboard:
                    for btn in row:
                        if btn.callback_data:
                            assert len(btn.callback_data.encode("utf-8")) <= 64, btn.callback_data

    def test_empty_station_list(self):
        from bot.keyboards.inline import metro_line_detail_keyboard
        kb = metro_line_detail_keyboard("A", [])
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "metro:lines" in all_data


# ===================================================================
# events_today_keyboard now honours show_more / upcoming
# ===================================================================

class TestEventsTodayKeyboardParams:
    def _events(self, n=2):
        from bot.services.events import EVENTS
        return EVENTS[:n]

    def test_show_more_false_hides_more_button(self):
        from bot.keyboards.inline import events_today_keyboard
        kb = events_today_keyboard(self._events(), "pt", show_more=False)
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "events:categories" not in all_data

    def test_show_more_true_shows_more_button(self):
        from bot.keyboards.inline import events_today_keyboard
        kb = events_today_keyboard(self._events(), "pt", show_more=True)
        all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
        assert "events:categories" in all_data

    def test_upcoming_adds_all_events_shortcut(self):
        from bot.keyboards.inline import events_today_keyboard
        today = [btn.callback_data for row in
                 events_today_keyboard(self._events(), "pt").inline_keyboard for btn in row]
        upcoming = [btn.callback_data for row in
                    events_today_keyboard(self._events(), "pt", upcoming=True).inline_keyboard
                    for btn in row]
        assert "events:cat:all" not in today
        assert "events:cat:all" in upcoming

    def test_upcoming_view_differs_from_today_view(self):
        from bot.keyboards.inline import events_today_keyboard
        today = events_today_keyboard(self._events(), "pt")
        upcoming = events_today_keyboard(self._events(), "pt", upcoming=True)
        assert len(upcoming.inline_keyboard) != len(today.inline_keyboard)

    def test_back_to_main_always_present(self):
        from bot.keyboards.inline import events_today_keyboard
        for show_more in (True, False):
            for upcoming in (True, False):
                kb = events_today_keyboard(self._events(), "pt",
                                            show_more=show_more, upcoming=upcoming)
                all_data = [btn.callback_data for row in kb.inline_keyboard for btn in row]
                assert "menu:main" in all_data

    def test_transfer_stations_are_flagged(self):
        from bot.keyboards.inline import metro_line_detail_keyboard
        stations = ["S1", "S2", "S3"]
        stations_data = {"S1": {"lines": ["A"]},
                         "S2": {"lines": ["A", "B"]},
                         "S3": {"lines": ["A"]}}
        kb = metro_line_detail_keyboard("A", stations, stations_data=stations_data)
        labels = {btn.callback_data: btn.text for row in kb.inline_keyboard
                  for btn in row if btn.callback_data}
        assert "🔄" in labels["metro:station:S2"]
        assert "🔄" not in labels["metro:station:S1"]

    def test_no_transfer_flag_without_station_data(self):
        from bot.keyboards.inline import metro_line_detail_keyboard
        kb = metro_line_detail_keyboard("A", ["S1", "S2"])
        for row in kb.inline_keyboard:
            for btn in row:
                if btn.callback_data and btn.callback_data.startswith("metro:station:"):
                    assert "🔄" not in btn.text
