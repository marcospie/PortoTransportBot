"""Tests for the Andante Zone Calculator feature."""

import pytest
from unittest.mock import AsyncMock, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_context(user_data=None, args=None):
    ctx = MagicMock()
    ctx.user_data = user_data if user_data is not None else {}
    ctx.args = args if args is not None else []
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
# Zone service tests
# ===================================================================

class TestZoneService:
    """Tests for bot.services.zones module."""

    # -- station -> official zone code -------------------------------------

    def test_zone_codes_are_real_andante_names(self):
        """Zones must be real signposted codes (PRT1, VNG1), never Z2/Z12."""
        from bot.services.zones import ZONES, ANDANTE_ZONES
        assert set(ZONES.values()) <= set(ANDANTE_ZONES)
        assert not any(z.startswith("Z") and z[1:].isdigit()
                       for z in ZONES.values())

    def test_get_zone_for_known_station(self):
        from bot.services.zones import get_zone_for_station
        assert get_zone_for_station("Trindade") == "PRT1"

    def test_get_zone_for_airport(self):
        from bot.services.zones import get_zone_for_station
        assert get_zone_for_station("Aeroporto") == "VCD8"

    def test_get_zone_for_gaia_station(self):
        from bot.services.zones import get_zone_for_station
        assert get_zone_for_station("Santo Ovídio") == "VNG1"

    def test_get_zone_for_unknown_station(self):
        from bot.services.zones import get_zone_for_station
        assert get_zone_for_station("Estação Inexistente XYZ") is None

    def test_get_zone_case_insensitive(self):
        from bot.services.zones import get_zone_for_station
        assert get_zone_for_station("trindade") == "PRT1"
        assert get_zone_for_station("AEROPORTO") == "VCD8"

    def test_get_zone_accent_insensitive(self):
        """Accents must not change the result -- datasets disagree on them."""
        from bot.services.zones import get_zone_for_station
        assert get_zone_for_station("santo ovidio") == "VNG1"
        assert get_zone_for_station("Fanzeres") == get_zone_for_station("Fânzeres")

    # -- zone graph --------------------------------------------------------

    def test_adjacency_is_symmetric(self):
        from bot.services.zones import ZONE_ADJACENCY
        for zone, neighbours in ZONE_ADJACENCY.items():
            for neighbour in neighbours:
                assert zone in ZONE_ADJACENCY[neighbour], (
                    f"{zone}->{neighbour} not mirrored"
                )

    def test_adjacency_covers_every_zone(self):
        from bot.services.zones import ZONE_ADJACENCY, ANDANTE_ZONES
        assert set(ZONE_ADJACENCY) == set(ANDANTE_ZONES)
        assert len(ANDANTE_ZONES) == 154

    def test_zone_distance_same_zone_is_one(self):
        from bot.services.zones import zone_distance
        assert zone_distance("PRT1", "PRT1") == 1

    def test_zone_distance_neighbour_is_two(self):
        from bot.services.zones import zone_distance, ZONE_ADJACENCY
        neighbour = ZONE_ADJACENCY["PRT1"][0]
        assert zone_distance("PRT1", neighbour) == 2

    def test_zone_distance_matches_official_values(self):
        """Spot-checks against Andante's published distance matrix."""
        from bot.services.zones import zone_distance
        official = {
            ("PRT1", "PRT2"): 2,
            ("PRT1", "PRT3"): 2,
            ("PRT1", "VNG1"): 2,
            ("PRT1", "MTS1"): 3,
            ("PRT1", "MAI4"): 3,
            ("PRT1", "GDM1"): 3,
            ("PRT1", "VCD8"): 4,
            ("PRT1", "VCD3"): 5,
            ("PRT1", "PV_VC"): 6,
            ("MTS1", "GDM1"): 4,
        }
        for (a, b), expected in official.items():
            assert zone_distance(a, b) == expected, f"{a}->{b}"
            assert zone_distance(b, a) == expected, f"{b}->{a}"

    def test_zone_distance_unknown_zone(self):
        from bot.services.zones import zone_distance
        assert zone_distance("PRT1", "NOPE9") is None

    def test_two_stations_in_far_apart_zones_are_not_one_zone(self):
        """The old linear model made opposite sides of Porto look adjacent."""
        from bot.services.zones import calculate_zones
        result = calculate_zones("Matosinhos Sul", "Fânzeres")
        assert result["zones_needed"] == 4
        assert result["title"] == "Z4"

    # -- fares -------------------------------------------------------------

    def test_calculate_zones_same_zone(self):
        from bot.services.zones import calculate_zones
        result = calculate_zones("Trindade", "Bolhão")
        assert result is not None
        assert result["zones_needed"] == 1
        assert result["origin_zone"] == "PRT1"
        assert result["dest_zone"] == "PRT1"
        # A single-zone trip still needs the minimum Z2 title.
        assert result["title"] == "Z2"
        assert result["price"] == 1.40

    def test_calculate_zones_cross_city(self):
        """Porto -> Gaia is officially 2 zones / Z2, not 4 zones."""
        from bot.services.zones import calculate_zones
        result = calculate_zones("Trindade", "Santo Ovídio")
        assert result["zones_needed"] == 2
        assert result["origin_zone"] == "PRT1"
        assert result["dest_zone"] == "VNG1"
        assert result["title"] == "Z2"
        assert result["price"] == 1.40

    def test_calculate_zones_airport(self):
        from bot.services.zones import calculate_zones
        result = calculate_zones("Trindade", "Aeroporto")
        assert result["zones_needed"] == 4
        assert result["title"] == "Z4"
        assert result["price"] == 2.30

    def test_calculate_zones_not_found(self):
        from bot.services.zones import calculate_zones
        assert calculate_zones("Trindade", "Nonexistent Station XYZ") is None

    def test_calculate_zones_symmetric(self):
        from bot.services.zones import calculate_zones
        ab = calculate_zones("Trindade", "Aeroporto")
        ba = calculate_zones("Aeroporto", "Trindade")
        assert ab["zones_needed"] == ba["zones_needed"]
        assert ab["price"] == ba["price"]

    def test_calculate_zones_povoa(self):
        from bot.services.zones import calculate_zones
        result = calculate_zones("Trindade", "Póvoa de Varzim")
        assert result["zones_needed"] == 6
        assert result["dest_zone"] == "PV_VC"
        assert result["title"] == "Z6"

    def test_calculate_zones_marks_estimates(self):
        """Stations whose zone we could not confirm are flagged, not faked."""
        from bot.services.zones import calculate_zones, ESTIMATED_ZONES
        assert "Império" in ESTIMATED_ZONES
        result = calculate_zones("Trindade", "Império")
        assert result["exact"] is False

    def test_calculate_zones_exact_for_metro(self):
        from bot.services.zones import calculate_zones
        assert calculate_zones("Trindade", "Aeroporto")["exact"] is True

    def test_station_outside_andante_is_not_priced(self):
        from bot.services.zones import calculate_zones, OUTSIDE_ANDANTE
        assert "Braga" in OUTSIDE_ANDANTE
        result = calculate_zones("Trindade", "Braga")
        assert result is not None
        assert result["covered"] is False
        assert result["price"] is None
        assert result["zones_needed"] is None

    def test_price_beyond_published_table_is_none(self):
        """Z10+ exists but has no published price -- never invent one."""
        from bot.services.zones import calculate_zones
        result = calculate_zones("Trindade", "Aveiro")
        assert result["zones_needed"] > 9
        assert result["price"] is None
        assert result["price_published"] is False

    def test_get_price_single_zone(self):
        from bot.services.zones import get_price
        assert get_price(1) == 1.40

    def test_get_price_multi_zone(self):
        from bot.services.zones import get_price
        assert get_price(2) == 1.40
        assert get_price(3) == 1.85
        assert get_price(5) == 2.80

    def test_get_price_minimum(self):
        from bot.services.zones import get_price
        assert get_price(0) == 1.40
        assert get_price(-1) == 1.40

    def test_get_day_pass_price(self):
        from bot.services.zones import get_day_pass_price
        assert get_day_pass_price(1) == 5.35
        assert get_day_pass_price(2) == 5.35
        assert get_day_pass_price(3) == 6.85

    def test_get_day_pass_price_beyond_table(self):
        from bot.services.zones import get_day_pass_price
        assert get_day_pass_price(9) == 17.30
        assert get_day_pass_price(11) is None

    def test_prices_come_from_fares_module(self):
        """zones.py must not keep its own price table."""
        from bot.services import fares
        import bot.services.zones as zones
        assert zones.ZONE_PRICES is fares.OCCASIONAL_PRICES
        assert zones.DAY_PASS_PRICES is fares.DAY_PASS_PRICES
        assert zones.ANDANTE_TOUR_PRICE == fares.ANDANTE_TOUR_3_PRICE

    # -- name resolution ---------------------------------------------------

    def test_cp_station_zones(self):
        from bot.services.zones import get_zone_for_station
        assert get_zone_for_station("Porto-São Bento") == "PRT1"
        assert get_zone_for_station("Porto-Campanhã") == "PRT1"

    def test_cp_station_misspellings_resolve(self):
        """cp.py has historically dropped the tilde/cedilla on these."""
        from bot.services.zones import get_zone_for_station
        assert get_zone_for_station("Porto-Campanha") == "PRT1"
        assert get_zone_for_station("Receão") == get_zone_for_station("Receção")
        assert get_zone_for_station("Lousãdo") == get_zone_for_station("Lousado")

    def test_dead_cp_suffix_keys_now_resolve(self):
        """The old '<name> CP' keys could never match a real lookup."""
        from bot.services.zones import get_zone_for_station
        assert get_zone_for_station("Contumil CP") == get_zone_for_station("Contumil")
        assert get_zone_for_station("Rio Tinto CP") == get_zone_for_station("Rio Tinto")
        assert get_zone_for_station("General Torres CP") == \
            get_zone_for_station("General Torres")

    def test_metrobus_stops_match_real_network(self):
        """Only the seven real Boavista-line stops, and no invented ones."""
        from bot.services.zones import ZONES
        for stop in ("Casa da Música (MetroBus)", "Guerra Junqueiro", "Bessa",
                     "Pinheiro Manso", "Serralves", "João de Barros", "Império"):
            assert stop in ZONES, stop
        for ghost in ("Praça da Galiza", "Arrábida", "Passeio Alegre",
                      "Via de Cintura Interna Este", "Matosinhos (MetroBus)"):
            assert ghost not in ZONES, ghost

    def test_metrobus_line_stays_in_porto(self):
        from bot.services.zones import get_zone_for_station
        assert get_zone_for_station("Casa da Música (MetroBus)") == "PRT1"
        assert get_zone_for_station("Império") == "PRT2"

    def test_resolve_station_reports_confidence(self):
        from bot.services.zones import resolve_station
        assert resolve_station("Trindade") == {
            "name": "Trindade", "zone": "PRT1", "covered": True, "exact": True,
        }
        assert resolve_station("Braga")["covered"] is False
        assert resolve_station("Nonexistent XYZ") is None

    def test_suggest_stations_offers_close_matches(self):
        from bot.services.zones import suggest_stations
        assert "Trindade" in suggest_stations("Trindad")
        assert "Aeroporto" in suggest_stations("Aeroprto")
        assert len(suggest_stations("Campanha")) <= 3

    def test_suggest_stations_empty_query(self):
        from bot.services.zones import suggest_stations
        assert suggest_stations("") == []

    # -- browsing ----------------------------------------------------------

    def test_get_stations_in_zone(self):
        from bot.services.zones import get_stations_in_zone
        stations = get_stations_in_zone("PRT1")
        assert "Trindade" in stations
        assert "Bolhão" in stations
        assert "Aliados" in stations

    def test_get_stations_in_zone_empty(self):
        from bot.services.zones import get_stations_in_zone
        assert get_stations_in_zone("Z99") == []
        assert get_stations_in_zone("") == []

    def test_get_all_zones(self):
        from bot.services.zones import get_all_zones
        zones = get_all_zones()
        assert zones[0] == "PRT1"
        for code in ("PRT1", "PRT2", "VNG1", "VCD8", "PV_VC"):
            assert code in zones
        # ordered outwards from the city centre
        assert zones.index("PRT2") < zones.index("PV_VC")

    def test_search_station(self):
        from bot.services.zones import search_station
        results = search_station("Trindade")
        assert results[0] == ("Trindade", "PRT1")

    def test_search_station_partial(self):
        from bot.services.zones import search_station
        results = search_station("Aero")
        assert any("Aeroporto" in name for name, _ in results)

    def test_search_station_accent_insensitive(self):
        from bot.services.zones import search_station
        assert search_station("bolhao") == search_station("Bolhão")

    def test_search_station_empty(self):
        from bot.services.zones import search_station
        assert search_station("") == []

    def test_no_dead_alias_table(self):
        """_CP_ALIASES used to map names to themselves and was never used."""
        import bot.services.zones as zones
        assert not hasattr(zones, "_CP_ALIASES")
        assert not hasattr(zones, "ZONE_ORDER")


# ===================================================================
# Zone keyboard tests
# ===================================================================

class TestZoneKeyboards:
    """Tests for zone-related keyboards."""

    def test_zones_menu_keyboard(self):
        from bot.keyboards.inline import zones_menu_keyboard
        kb = zones_menu_keyboard("pt")
        assert kb is not None
        all_buttons = [btn for row in kb.inline_keyboard for btn in row]
        callbacks = [btn.callback_data for btn in all_buttons]
        assert "zones:calculate" in callbacks
        assert "zones:map" in callbacks
        assert "menu:main" in callbacks

    def test_zones_result_keyboard(self):
        from bot.keyboards.inline import zones_result_keyboard
        kb = zones_result_keyboard("Trindade", "Aeroporto", "pt")
        assert kb is not None
        all_buttons = [btn for row in kb.inline_keyboard for btn in row]
        callbacks = [btn.callback_data for btn in all_buttons]
        assert "zones:calculate" in callbacks
        assert "zones:map" in callbacks

    def test_zones_map_keyboard(self):
        from bot.keyboards.inline import zones_map_keyboard
        kb = zones_map_keyboard("pt")
        assert kb is not None
        all_buttons = [btn for row in kb.inline_keyboard for btn in row]
        zone_buttons = [btn for btn in all_buttons if btn.callback_data and btn.callback_data.startswith("zones:zone:")]
        assert len(zone_buttons) > 0

    def test_zone_detail_keyboard(self):
        from bot.keyboards.inline import zone_detail_keyboard
        kb = zone_detail_keyboard("Z2", "pt")
        assert kb is not None


# ===================================================================
# Zone handler tests
# ===================================================================

class TestZoneHandlers:
    """Tests for zone handler functions."""

    @pytest.mark.asyncio
    async def test_zones_command_no_args(self):
        """Test /zonas command with no arguments shows menu."""
        from bot.handlers.zones import zones_command
        update = _make_update()
        context = _make_context(args=[])
        await zones_command(update, context)
        update.message.reply_text.assert_called_once()
        call_args = update.message.reply_text.call_args[0][0]
        assert "Andante" in call_args or "Zonas" in call_args

    @pytest.mark.asyncio
    async def test_zones_command_quick(self):
        """Test /zonas Trindade Aeroporto quick calculation."""
        from bot.handlers.zones import zones_command
        update = _make_update()
        context = _make_context(args=["Trindade", "Aeroporto"])
        await zones_command(update, context)
        update.message.reply_text.assert_called_once()
        call_args = update.message.reply_text.call_args[0][0]
        assert "Z" in call_args

    @pytest.mark.asyncio
    async def test_zones_menu_callback(self):
        """Test zone menu callback."""
        from bot.handlers.zones import zones_menu_callback
        update = _make_update()
        context = _make_context()
        await zones_menu_callback(update, context)
        update.callback_query.answer.assert_called_once()
        update.callback_query.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_zones_calculate_callback(self):
        """Test starting zone calculation sets step to origin."""
        from bot.handlers.zones import zones_calculate_callback
        update = _make_update()
        context = _make_context()
        await zones_calculate_callback(update, context)
        assert context.user_data.get("zones_step") == "origin"

    @pytest.mark.asyncio
    async def test_zones_map_callback(self):
        """Test zone map display."""
        from bot.handlers.zones import zones_map_callback
        update = _make_update()
        context = _make_context()
        await zones_map_callback(update, context)
        update.callback_query.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_zones_zone_callback(self):
        """Test zone detail display shows stations."""
        from bot.handlers.zones import zones_zone_callback
        update = _make_update()
        update.callback_query.data = "zones:zone:PRT1"
        context = _make_context()
        await zones_zone_callback(update, context)
        update.callback_query.edit_message_text.assert_called_once()
        call_args = update.callback_query.edit_message_text.call_args[0][0]
        # PRT1 has many stations; check for one that appears early alphabetically
        assert "Aliados" in call_args

    @pytest.mark.asyncio
    async def test_handle_zones_text_origin(self):
        """Test handling text input for origin station."""
        from bot.handlers.zones import handle_zones_text_input
        update = _make_update(text="Trindade")
        context = _make_context(user_data={"zones_step": "origin"})
        result = await handle_zones_text_input(update, context)
        assert result is True
        assert context.user_data.get("zones_origin") == "Trindade"
        assert context.user_data.get("zones_step") == "dest"

    @pytest.mark.asyncio
    async def test_handle_zones_text_dest(self):
        """Test handling text input for destination station."""
        from bot.handlers.zones import handle_zones_text_input
        update = _make_update(text="Aeroporto")
        context = _make_context(user_data={
            "zones_step": "dest",
            "zones_origin": "Trindade",
        })
        result = await handle_zones_text_input(update, context)
        assert result is True
        update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_zones_text_not_awaiting(self):
        """Test that text handler returns False when not in zone flow."""
        from bot.handlers.zones import handle_zones_text_input
        update = _make_update(text="Trindade")
        context = _make_context()
        result = await handle_zones_text_input(update, context)
        assert result is False

    @pytest.mark.asyncio
    async def test_handle_zones_text_unknown_station(self):
        """Test handling unknown station name during zone flow."""
        from bot.handlers.zones import handle_zones_text_input
        update = _make_update(text="NonExistentStationXYZ123")
        context = _make_context(user_data={"zones_step": "origin"})
        result = await handle_zones_text_input(update, context)
        assert result is True
        update.message.reply_text.assert_called_once()
        call_args = update.message.reply_text.call_args[0][0]
        assert "NonExistentStationXYZ123" in call_args


    # -- UX fixes ----------------------------------------------------------

    @pytest.mark.asyncio
    async def test_zones_ask_origin_has_cancel_keyboard(self):
        """The origin prompt must always offer a way out."""
        from bot.handlers.zones import zones_calculate_callback
        update = _make_update()
        context = _make_context()
        await zones_calculate_callback(update, context)
        kwargs = update.callback_query.edit_message_text.call_args[1]
        kb = kwargs["reply_markup"]
        assert kb is not None
        data = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert "menu:zones" in data

    @pytest.mark.asyncio
    async def test_ask_dest_prompt_has_cancel_keyboard(self):
        from bot.handlers.zones import handle_zones_text_input
        update = _make_update(text="Trindade")
        context = _make_context(user_data={"zones_step": "origin"})
        await handle_zones_text_input(update, context)
        kb = update.message.reply_text.call_args[1]["reply_markup"]
        data = [b.callback_data for row in kb.inline_keyboard for b in row]
        assert "menu:zones" in data

    @pytest.mark.asyncio
    async def test_typo_offers_tappable_suggestions(self):
        from bot.handlers.zones import handle_zones_text_input
        update = _make_update(text="Aeropuerto")
        context = _make_context(user_data={"zones_step": "origin"})
        handled = await handle_zones_text_input(update, context)
        assert handled is True
        kb = update.message.reply_text.call_args[1]["reply_markup"]
        assert kb is not None
        labels = [b.text for row in kb.inline_keyboard for b in row]
        assert any("Aeroporto" in label for label in labels)

    @pytest.mark.asyncio
    async def test_near_miss_is_auto_corrected(self):
        """A one-character typo should just work."""
        from bot.handlers.zones import handle_zones_text_input
        update = _make_update(text="Trindad3")
        context = _make_context(user_data={"zones_step": "origin"})
        await handle_zones_text_input(update, context)
        assert context.user_data["zones_origin"] == "Trindade"

    @pytest.mark.asyncio
    async def test_suggestion_button_is_routable(self):
        """Suggestion callback_data must match a registered pattern."""
        import re
        from bot.handlers.zones import _suggestions_keyboard
        kb = _suggestions_keyboard(["Trindade", "Aeroporto"], "pt")
        for row in kb.inline_keyboard:
            for button in row:
                assert re.match(r"^(zones:zone:.+|menu:zones)$",
                                button.callback_data), button.callback_data
                assert len(button.callback_data.encode("utf-8")) <= 64

    @pytest.mark.asyncio
    async def test_tapping_a_suggestion_sets_origin(self):
        from bot.handlers.zones import zones_zone_callback
        update = _make_update()
        update.callback_query.data = "zones:zone:Trindade"
        context = _make_context(user_data={"zones_step": "origin"})
        await zones_zone_callback(update, context)
        assert context.user_data["zones_origin"] == "Trindade"
        assert context.user_data["zones_step"] == "dest"

    @pytest.mark.asyncio
    async def test_zones_command_single_arg_prefills_origin(self):
        """`/zonas Trindade` used to silently drop the argument."""
        from bot.handlers.zones import zones_command
        update = _make_update()
        context = _make_context(args=["Trindade"])
        await zones_command(update, context)
        assert context.user_data["zones_origin"] == "Trindade"
        assert context.user_data["zones_step"] == "dest"
        text = update.message.reply_text.call_args[0][0]
        assert "Trindade" in text

    @pytest.mark.asyncio
    async def test_result_shows_verified_date(self):
        """Stale prices must be visible, not silently wrong."""
        from bot.handlers.zones import zones_command
        from bot.services import fares
        update = _make_update()
        context = _make_context(args=["Trindade", "Aeroporto"])
        await zones_command(update, context)
        text = update.message.reply_text.call_args[0][0]
        assert fares.LAST_VERIFIED.replace("-", "\\-") in text

    @pytest.mark.asyncio
    async def test_result_flags_estimates(self):
        from bot.handlers.zones import zones_command
        update = _make_update()
        context = _make_context(args=["Trindade", "Império"])
        await zones_command(update, context)
        text = update.message.reply_text.call_args[0][0]
        assert "⚠️" in text

    @pytest.mark.asyncio
    async def test_outside_andante_says_so(self):
        from bot.handlers.zones import zones_command
        update = _make_update()
        context = _make_context(args=["Trindade", "Braga"])
        await zones_command(update, context)
        text = update.message.reply_text.call_args[0][0]
        assert "Braga" in text
        assert "Andante" in text

    @pytest.mark.asyncio
    async def test_zone_empty_message_is_translated(self):
        """The hardcoded Portuguese string must not reach English users."""
        from bot.handlers.zones import zones_zone_callback
        update = _make_update(lang="en")
        update.callback_query.data = "zones:zone:ARC1"  # no stations
        context = _make_context()
        await zones_zone_callback(update, context)
        text = update.callback_query.edit_message_text.call_args[0][0]
        assert "Nenhuma" not in text
        assert "No stations" in text

    def test_fallback_strings_never_leak_raw_keys(self):
        """t() falling back to the raw key must not crash or show the key."""
        from bot.handlers.zones import _s, NEW_I18N_KEYS
        for key in NEW_I18N_KEYS:
            for lang in ("pt", "en"):
                value = _s(key, lang)
                assert value and value != key

    def test_safe_edit_message_is_used(self):
        """Refresh paths must tolerate "Message is not modified"."""
        import inspect
        import bot.handlers.zones as handler
        source = inspect.getsource(handler)
        assert "safe_edit_message" in source
        assert "query.edit_message_text" not in source


# ===================================================================
# i18n tests
# ===================================================================

class TestZoneI18n:
    """Tests for zone-related translations."""

    def test_zone_translations_exist_pt(self):
        from bot.utils.i18n import t
        assert "Andante" in t("zones_title", "pt") or "Zonas" in t("zones_title", "pt")
        assert t("zones_ask_origin", "pt") != "zones_ask_origin"
        assert t("zones_result", "pt") != "zones_result"

    def test_zone_translations_exist_en(self):
        from bot.utils.i18n import t
        assert "Andante" in t("zones_title", "en") or "Zone" in t("zones_title", "en")
        assert t("zones_ask_origin", "en") != "zones_ask_origin"
        assert t("zones_result", "en") != "zones_result"

    def test_zone_keyboard_labels_exist(self):
        from bot.utils.i18n import t
        for lang in ("pt", "en"):
            assert t("kb_zones", lang) != "kb_zones"
            assert t("kb_zones_calculate", lang) != "kb_zones_calculate"
            assert t("kb_zones_map", lang) != "kb_zones_map"
            assert t("kb_zones_new_calc", lang) != "kb_zones_new_calc"
