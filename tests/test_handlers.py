"""Integration tests for handler modules."""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers to build mock Update / Context objects
# ---------------------------------------------------------------------------

def _make_context(user_data=None):
    ctx = MagicMock()
    ctx.user_data = user_data if user_data is not None else {}
    ctx.args = []
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()
    ctx.bot.send_location = AsyncMock()
    return ctx


def _make_update(user_id=123, text="", lang="pt", chat_id=456):
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_user.language_code = lang
    update.effective_chat.id = chat_id

    # message
    msg = MagicMock()
    msg.text = text
    msg.from_user.id = user_id
    msg.from_user.language_code = lang
    msg.reply_text = AsyncMock()
    msg.chat_id = chat_id
    update.message = msg

    # callback_query (set up but may be overridden per test)
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
# Route handler tests
# ===================================================================

class TestRouteHandlers:

    @pytest.mark.asyncio
    async def test_route_command_sets_awaiting(self):
        """Test that /route sets AWAITING_ROUTE_ORIGIN in user_data."""
        from bot.handlers.routes import route_command, AWAITING_ROUTE_ORIGIN

        update = _make_update()
        context = _make_context()

        await route_command(update, context)

        assert AWAITING_ROUTE_ORIGIN in context.user_data
        assert isinstance(context.user_data[AWAITING_ROUTE_ORIGIN], datetime)
        update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_route_origin_resolved_asks_dest(self):
        """Test that typing a valid origin resolves it and asks for destination."""
        from bot.handlers.routes import handle_route_text_input, AWAITING_ROUTE_ORIGIN, AWAITING_ROUTE_DEST

        update = _make_update(text="Trindade")
        context = _make_context(user_data={
            AWAITING_ROUTE_ORIGIN: datetime.now(),
        })

        with patch("bot.handlers.routes.resolve_location") as mock_resolve:
            mock_resolve.return_value = {
                "type": "metro",
                "name": "Trindade",
                "lat": 41.1519,
                "lon": -8.6099,
                "lines": ["A", "B"],
            }

            handled = await handle_route_text_input(update, context)

        assert handled is True
        assert "route_origin" in context.user_data
        assert context.user_data["route_origin"]["name"] == "Trindade"
        assert AWAITING_ROUTE_DEST in context.user_data
        update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_trip_planner_direct_metro(self):
        """Test trip planner finds direct metro route (same line)."""
        from bot.services.trip_planner import plan_trip

        options = plan_trip("Trindade", "Bolhão")
        assert len(options) >= 1
        assert options[0].transfers == 0

    @pytest.mark.asyncio
    async def test_trip_planner_metro_with_transfer(self):
        """Test trip planner finds metro route with transfer."""
        from bot.services.trip_planner import plan_trip

        options = plan_trip("Senhor de Matosinhos", "Santo Ovídio")
        assert len(options) >= 1
        # At least one option should have a transfer
        has_transfer = any(o.transfers >= 1 for o in options)
        assert has_transfer


# ===================================================================
# Location handler tests
# ===================================================================

class TestLocationHandler:

    @pytest.mark.asyncio
    async def test_location_finds_nearby(self):
        """Test that a location message shows nearby stations and stops."""
        from bot.handlers.location import location_handler

        update = _make_update()
        update.message.location = MagicMock(latitude=41.15, longitude=-8.61)
        context = _make_context()

        with patch("bot.handlers.location.get_user_settings", new_callable=AsyncMock) as mock_settings, \
             patch("bot.handlers.location.metro") as mock_metro, \
             patch("bot.handlers.location._get_nearby_bus_stops", new_callable=AsyncMock) as mock_bus:

            mock_settings.return_value = {
                "metro_radius_m": 500,
                "bus_radius_m": 200,
                "max_results": 5,
            }
            mock_metro.get_nearby_stations.return_value = [
                {
                    "name": "Trindade",
                    "distance_m": 120,
                    "lines": [{"emoji": "🔵", "name": "Azul", "code": "A"}],
                },
            ]
            mock_bus.return_value = [
                {"name": "Pr. da Liberdade", "distance_m": 80, "stop_id": "PRL1"},
            ]

            await location_handler(update, context)

        update.message.reply_text.assert_called_once()
        assert context.user_data["last_location"] == {"lat": 41.15, "lon": -8.61}

    @pytest.mark.asyncio
    async def test_location_nothing_nearby(self):
        """Test when no stops/stations are nearby."""
        from bot.handlers.location import location_handler

        update = _make_update()
        update.message.location = MagicMock(latitude=40.0, longitude=-9.0)
        context = _make_context()

        with patch("bot.handlers.location.get_user_settings", new_callable=AsyncMock) as mock_settings, \
             patch("bot.handlers.location.metro") as mock_metro, \
             patch("bot.handlers.location._get_nearby_bus_stops", new_callable=AsyncMock) as mock_bus:

            mock_settings.return_value = {
                "metro_radius_m": 500,
                "bus_radius_m": 200,
                "max_results": 5,
            }
            mock_metro.get_nearby_stations.return_value = []
            mock_bus.return_value = []

            await location_handler(update, context)

        update.message.reply_text.assert_called_once()
        call_kwargs = update.message.reply_text.call_args
        # The text should mention that nothing was found (nearby_empty)
        assert call_kwargs is not None

    @pytest.mark.asyncio
    async def test_nearby_refresh_works(self):
        """Test that the refresh callback re-queries with stored location."""
        from bot.handlers.location import nearby_refresh_callback

        update = _make_update()
        update.callback_query.data = "nearby:refresh"
        context = _make_context(user_data={
            "last_location": {"lat": 41.15, "lon": -8.61},
        })

        with patch("bot.handlers.location.get_user_settings", new_callable=AsyncMock) as mock_settings, \
             patch("bot.handlers.location.metro") as mock_metro, \
             patch("bot.handlers.location._get_nearby_bus_stops", new_callable=AsyncMock) as mock_bus:

            mock_settings.return_value = {
                "metro_radius_m": 500,
                "bus_radius_m": 200,
                "max_results": 5,
            }
            mock_metro.get_nearby_stations.return_value = [
                {
                    "name": "Bolhão",
                    "distance_m": 200,
                    "lines": [{"emoji": "🔵", "name": "Azul", "code": "A"}],
                },
            ]
            mock_bus.return_value = []

            await nearby_refresh_callback(update, context)

        update.callback_query.answer.assert_called_once()
        update.callback_query.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_nearby_refresh_no_location(self):
        """Test refresh callback when no stored location exists."""
        from bot.handlers.location import nearby_refresh_callback

        update = _make_update()
        update.callback_query.data = "nearby:refresh"
        context = _make_context()  # no last_location

        await nearby_refresh_callback(update, context)

        update.callback_query.answer.assert_called_once()
        update.callback_query.edit_message_text.assert_called_once()


# ===================================================================
# handle_text tests (main.py)
# ===================================================================

class TestHandleText:

    @pytest.mark.asyncio
    async def test_stop_code_detected(self):
        """Short text with digits should trigger bus stop lookup."""
        from bot.main import handle_text

        update = _make_update(text="BCM2")
        context = _make_context()

        with patch("bot.handlers.routes.handle_route_text_input", new_callable=AsyncMock, return_value=False), \
             patch("bot.handlers.bus.handle_bus_text_input", new_callable=AsyncMock, return_value=False), \
             patch("bot.handlers.metro.handle_metro_text_input", new_callable=AsyncMock, return_value=False), \
             patch("bot.services.stcp.get_stop_real_time", new_callable=AsyncMock) as mock_rt, \
             patch("bot.database.is_favorite", new_callable=AsyncMock, return_value=False):

            mock_rt.return_value = {
                "stop_name": "Boavista - Casa da Música",
                "arrivals": [{"line": "204", "destination": "Marquês", "time": "3 min"}],
            }

            await handle_text(update, context)

        update.message.reply_text.assert_called_once()
        call_args = update.message.reply_text.call_args
        assert call_args is not None

    @pytest.mark.asyncio
    async def test_metro_station_search(self):
        """Text matching a metro station should show station results."""
        from bot.main import handle_text

        update = _make_update(text="Trindade")
        context = _make_context()

        with patch("bot.handlers.routes.handle_route_text_input", new_callable=AsyncMock, return_value=False), \
             patch("bot.handlers.bus.handle_bus_text_input", new_callable=AsyncMock, return_value=False), \
             patch("bot.handlers.metro.handle_metro_text_input", new_callable=AsyncMock, return_value=False), \
             patch("bot.services.metro.search_stations") as mock_search, \
             patch("bot.services.metro.get_next_departures") as mock_deps, \
             patch("bot.database.is_favorite", new_callable=AsyncMock, return_value=False):

            mock_search.return_value = [
                {
                    "name": "Trindade",
                    "zone": "PRT",
                    "lines": [{"emoji": "🔵", "name": "Linha Azul", "code": "A"}],
                },
            ]
            mock_deps.return_value = [
                {"direction": "Senhor de Matosinhos", "time": "5 min", "estimated": False},
            ]

            await handle_text(update, context)

        update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_results_fallback(self):
        """When nothing matches, show the no-results menu."""
        from bot.main import handle_text

        update = _make_update(text="xyznonexistent")
        context = _make_context()

        with patch("bot.handlers.routes.handle_route_text_input", new_callable=AsyncMock, return_value=False), \
             patch("bot.handlers.bus.handle_bus_text_input", new_callable=AsyncMock, return_value=False), \
             patch("bot.handlers.metro.handle_metro_text_input", new_callable=AsyncMock, return_value=False), \
             patch("bot.services.metro.search_stations", return_value=[]), \
             patch("bot.services.stcp.search_stops", new_callable=AsyncMock, return_value=[]):

            await handle_text(update, context)

        update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_favorites_keyboard_button(self):
        """The star Favoritos button text should route to favorites_command."""
        from bot.main import handle_text

        update = _make_update(text="⭐ Favoritos")
        context = _make_context()

        with patch("bot.main.favorites") as mock_fav_module:
            mock_fav_module.favorites_command = AsyncMock()
            await handle_text(update, context)

        mock_fav_module.favorites_command.assert_awaited_once_with(update, context)


# ===================================================================
# Favorites handler tests
# ===================================================================

class TestFavoritesHandlers:

    @pytest.mark.asyncio
    async def test_add_favorite_bus(self):
        """Test adding a bus stop as a favorite."""
        from bot.handlers.favorites import add_favorite_callback

        update = _make_update()
        update.callback_query.data = "fav:add:bus:BCM2"
        context = _make_context()

        with patch("bot.handlers.favorites.is_favorite", new_callable=AsyncMock, return_value=False), \
             patch("bot.handlers.favorites.add_favorite", new_callable=AsyncMock) as mock_add, \
             patch("bot.services.stcp.get_stop_info", new_callable=AsyncMock, return_value={"name": "Boavista"}):

            await add_favorite_callback(update, context)

        mock_add.assert_awaited_once_with(123, "bus", "BCM2", "Boavista")
        update.callback_query.answer.assert_called_once()

    @pytest.mark.asyncio
    async def test_remove_favorite(self):
        """Test removing a favorite and refreshing the list."""
        from bot.handlers.favorites import remove_favorite_callback

        update = _make_update()
        update.callback_query.data = "fav:remove:bus:BCM2"
        context = _make_context()

        with patch("bot.handlers.favorites.remove_favorite", new_callable=AsyncMock) as mock_rm, \
             patch("bot.handlers.favorites.get_favorites", new_callable=AsyncMock, return_value=[]):

            await remove_favorite_callback(update, context)

        mock_rm.assert_awaited_once_with(123, "bus", "BCM2")
        update.callback_query.answer.assert_called_once()
        update.callback_query.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_fav_quick_no_favorites(self):
        """/fav with no favorites should show empty message."""
        from bot.handlers.favorites import fav_quick_command

        update = _make_update()
        context = _make_context()

        with patch("bot.handlers.favorites.get_favorites", new_callable=AsyncMock, return_value=[]):
            await fav_quick_command(update, context)

        update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_fav_quick_with_bus_favorite(self):
        """/fav with a bus favorite should call _send_stop_realtime."""
        from bot.handlers.favorites import fav_quick_command

        update = _make_update()
        context = _make_context()

        with patch("bot.handlers.favorites.get_favorites", new_callable=AsyncMock,
                    return_value=[{"type": "bus", "id": "BCM2", "name": "Boavista"}]), \
             patch("bot.handlers.bus._send_stop_realtime", new_callable=AsyncMock) as mock_send:

            await fav_quick_command(update, context)

        mock_send.assert_awaited_once()
