"""Tests for the database layer (JSON fallback mode)."""

import json
import logging
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

import bot.database as db
from bot.database import (
    DEFAULT_SETTINGS,
    _json_load_favorites,
    _json_save_favorites,
    add_favorite,
    remove_favorite,
    get_favorites,
    get_favorite_count,
    is_favorite,
    get_or_create_user,
    get_user,
    get_user_settings,
    is_user_onboarded,
    set_user_onboarded,
    update_user_setting,
    get_commuter_profile,
    save_commuter_profile,
    delete_commuter_profile,
    init_db,
    close_db,
)


# ===================================================================
# Fake asyncpg pool, so the PostgreSQL code paths are actually executed
# ===================================================================

class FakeConn:
    """Minimal asyncpg-Connection stand-in that records the SQL it is given."""

    def __init__(self, rows=None, user_row=None):
        self.rows = rows or {}
        self.user_row = user_row if user_row is not None else {
            "id": 1, "language": "pt", "onboarded": False,
        }
        self.executed: list[tuple] = []
        self.queried: list[tuple] = []

    async def fetchrow(self, sql, *args):
        self.queried.append((sql, args))
        if "FROM users" in sql:
            return self.user_row
        if "FROM user_settings" in sql:
            return self.rows.get("user_settings")
        return None

    async def fetchval(self, sql, *args):
        self.queried.append((sql, args))
        if "FROM commuter_profiles" in sql:
            return self.rows.get("commuter_profiles")
        if "FROM favorites" in sql:
            return self.rows.get("favorites_scalar")
        if "onboarded FROM users" in sql:
            return self.user_row.get("onboarded")
        return None

    async def fetch(self, sql, *args):
        self.queried.append((sql, args))
        if "FROM favorites" in sql:
            return self.rows.get("favorites", [])
        return []

    async def execute(self, sql, *args):
        self.executed.append((sql, args))
        return self.rows.get("execute_result", "DELETE 1")


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        conn = self.conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _Ctx()


def use_fake_db(conn):
    """Context manager enabling the PostgreSQL path against *conn*."""
    from contextlib import ExitStack
    stack = ExitStack()
    stack.enter_context(patch("bot.database._use_db", True))
    stack.enter_context(patch("bot.database._pool", FakePool(conn)))
    return stack


# ===================================================================
# JSON fallback tests (no DATABASE_URL)
# ===================================================================


class TestJsonFallbackFavorites:
    """Test favorites operations using JSON file fallback."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.fav_dir = Path(self.tmpdir) / "favorites"
        self.fav_dir.mkdir()

    def _write_favs(self, user_id, favs):
        path = self.fav_dir / f"{user_id}.json"
        path.write_text(json.dumps(favs))

    def _read_favs(self, user_id):
        path = self.fav_dir / f"{user_id}.json"
        if not path.exists():
            return []
        return json.loads(path.read_text())

    @patch("bot.database._FAVORITES_DIR")
    def test_json_load_empty(self, mock_dir):
        mock_dir.__truediv__ = lambda s, k: self.fav_dir / k
        mock_dir.mkdir = lambda **kw: None
        mock_dir.exists = lambda: True

        # No file exists
        result = _json_load_favorites(99999)
        assert result == []

    @patch("bot.database._FAVORITES_DIR")
    def test_json_save_and_load(self, mock_dir):
        fav_dir = self.fav_dir

        class MockDir:
            def mkdir(self, **kw): fav_dir.mkdir(exist_ok=True)
            def __truediv__(self, other): return fav_dir / other

        with patch("bot.database._FAVORITES_DIR", MockDir()):
            favs = [{"type": "bus", "id": "BCM2", "name": "Boavista"}]
            _json_save_favorites(12345, favs)
            loaded = _json_load_favorites(12345)
            assert len(loaded) == 1
            assert loaded[0]["id"] == "BCM2"

    @patch("bot.database._FAVORITES_DIR")
    def test_json_load_corrupt_file(self, mock_dir):
        # Write corrupt JSON
        path = self.fav_dir / "12345.json"
        path.write_text("not valid json{{{")

        class MockDir:
            def mkdir(self, **kw): pass
            def __truediv__(self, other): return self.fav_dir / other

        mock_dir.__truediv__ = lambda s, k: self.fav_dir / k
        mock_dir.mkdir = lambda **kw: None

        result = _json_load_favorites(12345)
        # Should not raise, should return empty or the parsed result
        # The actual _FAVORITES_DIR path used here won't match, so it will return []
        assert isinstance(result, list)


class TestFavoritesOperationsJsonFallback:
    """Test async favorites operations with JSON fallback (_use_db=False)."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.fav_dir = Path(self.tmpdir) / "favorites"
        self.fav_dir.mkdir()

    @pytest.fixture(autouse=True)
    def mock_json_fallback(self):
        """Ensure _use_db is False and redirect favorites dir."""
        fav_dir = self.fav_dir
        with patch("bot.database._use_db", False), \
             patch("bot.database._FAVORITES_DIR", fav_dir):
            yield

    @pytest.mark.asyncio
    async def test_add_favorite(self):
        result = await add_favorite(100, "bus", "BCM2", "Boavista")
        assert result is True
        favs = await get_favorites(100)
        assert len(favs) == 1
        assert favs[0]["id"] == "BCM2"

    @pytest.mark.asyncio
    async def test_add_duplicate_favorite(self):
        await add_favorite(100, "bus", "BCM2", "Boavista")
        result = await add_favorite(100, "bus", "BCM2", "Boavista")
        assert result is False

    @pytest.mark.asyncio
    async def test_remove_favorite(self):
        await add_favorite(100, "bus", "BCM2", "Boavista")
        result = await remove_favorite(100, "bus", "BCM2")
        assert result is True
        favs = await get_favorites(100)
        assert len(favs) == 0

    @pytest.mark.asyncio
    async def test_remove_nonexistent(self):
        result = await remove_favorite(100, "bus", "NOPE")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_favorites_empty(self):
        favs = await get_favorites(999)
        assert favs == []

    @pytest.mark.asyncio
    async def test_get_favorite_count(self):
        await add_favorite(100, "bus", "BCM2", "Boavista")
        await add_favorite(100, "metro", "Trindade", "Trindade")
        count = await get_favorite_count(100)
        assert count == 2

    @pytest.mark.asyncio
    async def test_is_favorite(self):
        await add_favorite(100, "bus", "BCM2", "Boavista")
        assert await is_favorite(100, "bus", "BCM2") is True
        assert await is_favorite(100, "bus", "NOPE") is False
        assert await is_favorite(100, "metro", "BCM2") is False

    @pytest.mark.asyncio
    async def test_multiple_users_isolated(self):
        await add_favorite(100, "bus", "BCM2", "Boavista")
        await add_favorite(200, "metro", "Trindade", "Trindade")
        assert len(await get_favorites(100)) == 1
        assert len(await get_favorites(200)) == 1
        assert await is_favorite(100, "metro", "Trindade") is False


class TestDbInitFallback:
    """Test database initialization falls back to JSON gracefully."""

    @pytest.mark.asyncio
    async def test_init_without_database_url(self):
        """Should fall back to JSON when DATABASE_URL is not set."""
        with patch.dict("os.environ", {}, clear=True):
            await init_db()
            # Should not raise

    @pytest.mark.asyncio
    async def test_close_db_noop(self):
        """close_db should be safe to call even without a pool."""
        await close_db()
        # Should not raise


class TestGetOrCreateUserFallback:
    """Test user operations in JSON fallback mode."""

    @pytest.mark.asyncio
    async def test_returns_dict(self, tmp_path):
        with patch("bot.database._use_db", False), \
             patch("bot.database._USERS_DIR", tmp_path / "users"):
            user = await get_or_create_user(12345, "pt")
            assert user["id"] == 12345
            assert user["language"] == "pt"
            assert user["onboarded"] is False


# ===================================================================
# No-DATABASE_URL warning (Railway/Heroku data-loss guard)
# ===================================================================

class TestNoDatabaseUrlWarning:
    """Running without DATABASE_URL must warn loudly about ephemeral storage."""

    @pytest.mark.asyncio
    async def test_init_db_logs_warning(self, caplog):
        with patch.dict("os.environ", {}, clear=True):
            with caplog.at_level(logging.WARNING, logger="bot.database"):
                await init_db()

        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert warnings, "init_db() must WARN when DATABASE_URL is unset"
        text = "\n".join(r.getMessage() for r in warnings)
        assert "DATABASE_URL" in text
        # Must actually say data is lost, not just 'using JSON'.
        assert "WIPES" in text or "LOST" in text.upper()
        assert "postgres" in text.lower()

    @pytest.mark.asyncio
    async def test_init_db_does_not_raise(self):
        with patch.dict("os.environ", {}, clear=True):
            await init_db()  # loud, but must never crash the bot
        assert db._use_db is False

    def test_warning_mentions_the_data_that_is_lost(self):
        message = db._NO_DATABASE_URL_WARNING.lower()
        for word in ("favorites", "settings", "commuter", "redeploy", "volume"):
            assert word in message, f"warning should mention {word!r}"


# ===================================================================
# Onboarding state persistence (JSON <-> Postgres parity)
# ===================================================================

class TestOnboardingPersistence:
    """JSON mode used to drop onboarding state entirely (always False)."""

    @pytest.mark.asyncio
    async def test_json_roundtrip(self, tmp_path):
        with patch("bot.database._use_db", False), \
             patch("bot.database._USERS_DIR", tmp_path / "users"):
            assert await is_user_onboarded(4242) is False
            await set_user_onboarded(4242)
            assert await is_user_onboarded(4242) is True
            user = await get_or_create_user(4242)
            assert user["onboarded"] is True

    @pytest.mark.asyncio
    async def test_json_users_are_isolated(self, tmp_path):
        with patch("bot.database._use_db", False), \
             patch("bot.database._USERS_DIR", tmp_path / "users"):
            await set_user_onboarded(1)
            assert await is_user_onboarded(1) is True
            assert await is_user_onboarded(2) is False

    @pytest.mark.asyncio
    async def test_get_user_returns_none_for_unknown(self, tmp_path):
        with patch("bot.database._use_db", False), \
             patch("bot.database._USERS_DIR", tmp_path / "users"):
            assert await get_user(999123) is None
            await set_user_onboarded(999123)
            assert await get_user(999123) is not None

    @pytest.mark.asyncio
    async def test_corrupt_user_file_is_tolerated(self, tmp_path):
        users_dir = tmp_path / "users"
        users_dir.mkdir()
        (users_dir / "77.json").write_text("{{{not json")
        with patch("bot.database._use_db", False), \
             patch("bot.database._USERS_DIR", users_dir):
            assert await is_user_onboarded(77) is False


# ===================================================================
# The `notifications` setting (opt-in proactive notifications)
# ===================================================================

class TestNotificationsSetting:

    def test_default_is_off(self):
        assert DEFAULT_SETTINGS["notifications"] == "off", (
            "proactive notifications must be opt-in"
        )

    def test_present_in_column_allowlist(self):
        assert db._SETTINGS_COLUMNS["notifications"] == "notifications"

    @pytest.mark.asyncio
    async def test_json_path_roundtrip(self, tmp_path):
        with patch("bot.database._use_db", False), \
             patch("bot.database._SETTINGS_DIR", tmp_path / "settings"):
            assert (await get_user_settings(5150))["notifications"] == "off"
            await update_user_setting(5150, "notifications", "on")
            assert (await get_user_settings(5150))["notifications"] == "on"

    @pytest.mark.asyncio
    async def test_json_path_backfills_key_for_old_files(self, tmp_path):
        """Settings files written before the key existed must still work."""
        settings_dir = tmp_path / "settings"
        settings_dir.mkdir()
        (settings_dir / "606.json").write_text(json.dumps({"max_results": 8}))
        with patch("bot.database._use_db", False), \
             patch("bot.database._SETTINGS_DIR", settings_dir):
            settings = await get_user_settings(606)
            assert settings["notifications"] == "off"
            assert settings["max_results"] == 8

    @pytest.mark.asyncio
    async def test_postgres_path_uses_the_notifications_column(self):
        conn = FakeConn()
        with use_fake_db(conn):
            await update_user_setting(7, "notifications", "on")
        sql = " ".join(s for s, _ in conn.executed)
        assert "notifications" in sql
        assert "user_settings" in sql
        # The value must be bound, never inlined.
        assert ("on",) not in [a for _, a in conn.executed]
        assert (7, "on") in [a for _, a in conn.executed]

    @pytest.mark.asyncio
    async def test_postgres_path_selects_the_notifications_column(self):
        conn = FakeConn(rows={"user_settings": {
            "metro_radius_m": 500, "bus_radius_m": 200, "max_results": 5,
            "language": "auto", "notifications": "on",
        }})
        with use_fake_db(conn):
            settings = await get_user_settings(7)
        assert settings["notifications"] == "on"

    @pytest.mark.asyncio
    async def test_unknown_setting_still_rejected(self):
        for bad in ("nope", "language; DROP TABLE users --"):
            with patch("bot.database._use_db", False):
                with pytest.raises(ValueError):
                    await update_user_setting(1, bad, "x")


# ===================================================================
# JSON-fallback vs PostgreSQL semantic parity
# ===================================================================

class TestJsonPostgresParity:
    """Both storage backends must return the same shapes and defaults."""

    @pytest.mark.asyncio
    async def test_settings_keys_match(self, tmp_path):
        with patch("bot.database._use_db", False), \
             patch("bot.database._SETTINGS_DIR", tmp_path / "settings"):
            json_settings = await get_user_settings(11)

        conn = FakeConn(rows={"user_settings": {
            c: DEFAULT_SETTINGS[k] for k, c in db._SETTINGS_COLUMNS.items()
        }})
        with use_fake_db(conn):
            pg_settings = await get_user_settings(11)

        assert set(json_settings) == set(pg_settings) == set(DEFAULT_SETTINGS)
        assert json_settings == pg_settings

    @pytest.mark.asyncio
    async def test_settings_defaults_match_when_nothing_stored(self, tmp_path):
        with patch("bot.database._use_db", False), \
             patch("bot.database._SETTINGS_DIR", tmp_path / "settings"):
            json_settings = await get_user_settings(12)

        conn = FakeConn()  # no user_settings row at all
        with use_fake_db(conn):
            pg_settings = await get_user_settings(12)

        assert json_settings == pg_settings == dict(DEFAULT_SETTINGS)

    @pytest.mark.asyncio
    async def test_postgres_null_columns_fall_back_to_defaults(self):
        """A NULL column must not leak None into the settings dict."""
        conn = FakeConn(rows={"user_settings": {
            c: None for c in db._SETTINGS_COLUMNS.values()
        }})
        with use_fake_db(conn):
            settings = await get_user_settings(13)
        assert settings == dict(DEFAULT_SETTINGS)

    @pytest.mark.asyncio
    async def test_favorites_shape_matches(self, tmp_path):
        with patch("bot.database._use_db", False), \
             patch("bot.database._FAVORITES_DIR", tmp_path / "favorites"):
            await add_favorite(21, "bus", "BCM2", "Boavista")
            json_favs = await get_favorites(21)

        conn = FakeConn(rows={"favorites": [
            {"type": "bus", "stop_id": "BCM2", "name": "Boavista"},
        ]})
        with use_fake_db(conn):
            pg_favs = await get_favorites(21)

        assert json_favs == pg_favs
        assert set(json_favs[0]) == {"type", "id", "name"}

    @pytest.mark.asyncio
    async def test_favorites_empty_shape_matches(self, tmp_path):
        with patch("bot.database._use_db", False), \
             patch("bot.database._FAVORITES_DIR", tmp_path / "favorites"):
            json_favs = await get_favorites(22)
        conn = FakeConn(rows={"favorites": []})
        with use_fake_db(conn):
            pg_favs = await get_favorites(22)
        assert json_favs == pg_favs == []

    @pytest.mark.asyncio
    async def test_commuter_profile_shape_matches(self, tmp_path):
        profile = {"home_name": "Trindade", "work_name": "Bolhao"}

        with patch("bot.database._use_db", False), \
             patch("bot.database._COMMUTER_DIR", tmp_path / "commuter"):
            await save_commuter_profile(31, profile)
            json_profile = await get_commuter_profile(31)

        # Postgres stores whatever save_commuter_profile serialised.
        conn = FakeConn()
        with use_fake_db(conn):
            await save_commuter_profile(31, profile)
            stored_json = conn.executed[-1][1][1]
            conn.rows["commuter_profiles"] = stored_json
            pg_profile = await get_commuter_profile(31)

        assert json_profile == pg_profile
        assert set(json_profile) == set(db.DEFAULT_COMMUTER_PROFILE)

    @pytest.mark.asyncio
    async def test_commuter_profile_missing_returns_none_in_both(self, tmp_path):
        with patch("bot.database._use_db", False), \
             patch("bot.database._COMMUTER_DIR", tmp_path / "commuter"):
            assert await get_commuter_profile(32) is None
        conn = FakeConn()
        with use_fake_db(conn):
            assert await get_commuter_profile(32) is None

    @pytest.mark.asyncio
    async def test_commuter_delete_returns_bool_in_both(self, tmp_path):
        with patch("bot.database._use_db", False), \
             patch("bot.database._COMMUTER_DIR", tmp_path / "commuter"):
            assert await delete_commuter_profile(33) is False
            await save_commuter_profile(33, {})
            assert await delete_commuter_profile(33) is True

        conn = FakeConn(rows={"execute_result": "DELETE 0"})
        with use_fake_db(conn):
            assert await delete_commuter_profile(33) is False
        conn = FakeConn(rows={"execute_result": "DELETE 1"})
        with use_fake_db(conn):
            assert await delete_commuter_profile(33) is True

    @pytest.mark.asyncio
    async def test_get_or_create_user_keys_match(self, tmp_path):
        with patch("bot.database._use_db", False), \
             patch("bot.database._USERS_DIR", tmp_path / "users"):
            json_user = await get_or_create_user(41, "pt")

        conn = FakeConn(user_row={"id": 41, "language": "pt", "onboarded": False})
        with use_fake_db(conn):
            pg_user = await get_or_create_user(41, "pt")

        assert set(json_user) == set(dict(pg_user))
        assert dict(pg_user) == json_user

    @pytest.mark.asyncio
    async def test_is_favorite_returns_bool_in_both(self, tmp_path):
        with patch("bot.database._use_db", False), \
             patch("bot.database._FAVORITES_DIR", tmp_path / "favorites"):
            assert await is_favorite(51, "bus", "X1") is False

        conn = FakeConn(rows={"favorites_scalar": None})
        with use_fake_db(conn):
            assert await is_favorite(51, "bus", "X1") is False
        conn = FakeConn(rows={"favorites_scalar": 1})
        with use_fake_db(conn):
            assert await is_favorite(51, "bus", "X1") is True

    @pytest.mark.asyncio
    async def test_favorite_count_returns_int_in_both(self, tmp_path):
        with patch("bot.database._use_db", False), \
             patch("bot.database._FAVORITES_DIR", tmp_path / "favorites"):
            await add_favorite(61, "bus", "A1", "A")
            assert await get_favorite_count(61) == 1

        conn = FakeConn(rows={"favorites_scalar": 1})
        with use_fake_db(conn):
            assert await get_favorite_count(61) == 1
