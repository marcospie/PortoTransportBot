"""PostgreSQL database layer with JSON file fallback.

If DATABASE_URL is set, uses asyncpg connection pool.
Otherwise, falls back to the existing JSON file storage.
"""

import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Connection pool (only set when DATABASE_URL is available)
# ---------------------------------------------------------------------------
_pool = None
_use_db: bool = False

DATABASE_URL: str = os.getenv("DATABASE_URL", "")

# ---------------------------------------------------------------------------
# SQL schema
# ---------------------------------------------------------------------------
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id          BIGINT PRIMARY KEY,
    language    VARCHAR(10) NOT NULL DEFAULT 'pt',
    onboarded   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMP NOT NULL DEFAULT now(),
    updated_at  TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS favorites (
    id          SERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type        VARCHAR(20) NOT NULL,
    stop_id     VARCHAR(100) NOT NULL,
    name        VARCHAR(255) NOT NULL,
    created_at  TIMESTAMP NOT NULL DEFAULT now(),
    UNIQUE(user_id, type, stop_id)
);

CREATE TABLE IF NOT EXISTS user_settings (
    user_id         BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    metro_radius_m  INTEGER NOT NULL DEFAULT 500,
    bus_radius_m    INTEGER NOT NULL DEFAULT 200,
    max_results     INTEGER NOT NULL DEFAULT 5,
    language        VARCHAR(10) NOT NULL DEFAULT 'auto',
    daily_digest    BOOLEAN NOT NULL DEFAULT FALSE,
    digest_time     TIME NOT NULL DEFAULT '07:30',
    digest_days     VARCHAR(50) NOT NULL DEFAULT 'weekdays',
    notifications   VARCHAR(10) NOT NULL DEFAULT 'off'
);

CREATE TABLE IF NOT EXISTS commuter_profiles (
    user_id      BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    profile_data JSONB,
    updated_at   TIMESTAMP NOT NULL DEFAULT now()
);
"""

# Migrations for existing tables (add columns if missing)
_MIGRATIONS_SQL = [
    "ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS metro_radius_m INTEGER NOT NULL DEFAULT 500",
    "ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS bus_radius_m INTEGER NOT NULL DEFAULT 200",
    "ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS max_results INTEGER NOT NULL DEFAULT 5",
    "ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS language VARCHAR(10) NOT NULL DEFAULT 'auto'",
    "ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS notifications VARCHAR(10) NOT NULL DEFAULT 'off'",
]

# ===================================================================
# JSON fallback helpers (mirrors the original favorites.py logic)
# ===================================================================
from bot.config import DATA_DIR  # noqa: E402

_FAVORITES_DIR = DATA_DIR / "favorites"
_SETTINGS_DIR = DATA_DIR / "settings"
_USERS_DIR = DATA_DIR / "users"

# Default settings values.
# NOTE: ``notifications`` is intentionally opt-in ('off') - proactive pushes must
# never be enabled without the user explicitly asking for them.
DEFAULT_SETTINGS = {
    "metro_radius_m": 500,
    "bus_radius_m": 200,
    "max_results": 5,
    "language": "auto",
    "notifications": "off",
}

# ---------------------------------------------------------------------------
# SQL-injection guard for the settings column names
# ---------------------------------------------------------------------------
# ``update_user_setting`` and ``get_user_settings`` have to interpolate a COLUMN
# NAME into the SQL text (Postgres does not allow parameter placeholders for
# identifiers).  The *only* thing that makes that safe is that the identifier is
# never taken from the caller: it is looked up in this hard-coded map, and the
# lookup fails closed with ValueError for anything unknown.  If you add a new
# setting, add it here AND to _SCHEMA_SQL/_MIGRATIONS_SQL - never build the
# column name from user input, and never interpolate ``key`` directly.
_SETTINGS_COLUMNS: dict[str, str] = {
    "metro_radius_m": "metro_radius_m",
    "bus_radius_m": "bus_radius_m",
    "max_results": "max_results",
    "language": "language",
    "notifications": "notifications",
}

# A bare, lowercase SQL identifier - anything else must never reach the SQL text.
_SAFE_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# Fail loudly at import time rather than at runtime if the two structures drift
# apart or if somebody adds a column name that is not a plain identifier.
assert set(_SETTINGS_COLUMNS) == set(DEFAULT_SETTINGS), (
    "_SETTINGS_COLUMNS and DEFAULT_SETTINGS must describe the same keys"
)
assert all(_SAFE_IDENTIFIER_RE.match(c) for c in _SETTINGS_COLUMNS.values()), (
    "settings column names must be plain lowercase SQL identifiers"
)

# Pre-rendered, allowlist-derived column list for SELECTs (see comment above).
_SETTINGS_SELECT_COLUMNS = ", ".join(_SETTINGS_COLUMNS[k] for k in DEFAULT_SETTINGS)


def _settings_column(key: str) -> str:
    """Return the validated physical column name for a settings *key*.

    Raises ``ValueError`` for any key that is not in the ``DEFAULT_SETTINGS``
    allowlist.  This is the single choke point that keeps the identifier
    interpolation in the SQL below injection-proof.
    """
    column = _SETTINGS_COLUMNS.get(key)
    if column is None or not _SAFE_IDENTIFIER_RE.match(column):
        raise ValueError(f"Unknown setting: {key}")
    return column


def _json_favorites_path(user_id: int) -> Path:
    _FAVORITES_DIR.mkdir(parents=True, exist_ok=True)
    return _FAVORITES_DIR / f"{user_id}.json"


def _json_load_favorites(user_id: int) -> list[dict]:
    path = _json_favorites_path(user_id)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def _json_save_favorites(user_id: int, favorites: list[dict]) -> None:
    path = _json_favorites_path(user_id)
    path.write_text(json.dumps(favorites, ensure_ascii=False, indent=2))


# ===================================================================
# Pool lifecycle
# ===================================================================

_NO_DATABASE_URL_WARNING = (
    "\n"
    "==============================================================================\n"
    " DATABASE_URL is NOT set - falling back to JSON files under %s\n"
    "\n"
    " *** THIS STORAGE IS NOT PERSISTENT ON RAILWAY / HEROKU / PLAIN DOCKER ***\n"
    " Container filesystems are ephemeral: every redeploy, restart or crash WIPES\n"
    " all user favorites, settings and commuter profiles.\n"
    "\n"
    " To keep user data, add a PostgreSQL database and set DATABASE_URL, e.g.\n"
    "   DATABASE_URL=postgresql://user:password@host:5432/dbname\n"
    " On Railway: New -> Database -> Add PostgreSQL, then reference its\n"
    " DATABASE_URL variable from the bot service.\n"
    " If you must stay on JSON storage, mount a persistent volume at %s.\n"
    " See README.md ('Persistencia de dados') for the full instructions.\n"
    "=============================================================================="
)


def _warn_no_database_url() -> None:
    """Log a loud (but non-fatal) warning about ephemeral JSON storage."""
    logger.warning(_NO_DATABASE_URL_WARNING, DATA_DIR, DATA_DIR)


async def init_db() -> None:
    """Create the connection pool and ensure schema exists.

    If DATABASE_URL is not set the function falls back to JSON files and logs a
    prominent warning, because that storage is lost on every container restart.
    """
    global _pool, _use_db

    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        _warn_no_database_url()
        _use_db = False
        return

    try:
        import asyncpg
        _pool = await asyncpg.create_pool(dsn=database_url, min_size=2, max_size=10)
        async with _pool.acquire() as conn:
            await conn.execute(_SCHEMA_SQL)
            # Run migrations for existing tables
            for migration in _MIGRATIONS_SQL:
                try:
                    await conn.execute(migration)
                except Exception:
                    pass  # Column already exists or table doesn't exist yet
        _use_db = True
        logger.info("PostgreSQL database initialised (pool ready)")
    except Exception:
        logger.exception("Failed to connect to PostgreSQL - falling back to JSON")
        _pool = None
        _use_db = False


async def close_db() -> None:
    """Close the connection pool gracefully."""
    global _pool, _use_db
    if _pool is not None:
        await _pool.close()
        _pool = None
        _use_db = False
        logger.info("PostgreSQL connection pool closed")


# ===================================================================
# User helpers
# ===================================================================

def _json_user_path(user_id: int) -> Path:
    _USERS_DIR.mkdir(parents=True, exist_ok=True)
    return _USERS_DIR / f"{user_id}.json"


def _json_load_user(user_id: int) -> Optional[dict]:
    path = _json_user_path(user_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _json_save_user(user_id: int, data: dict) -> None:
    path = _json_user_path(user_id)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2))


async def get_or_create_user(user_id: int, language: str = "pt"):
    """Return the user row, creating it if it does not exist."""
    if not _use_db:
        stored = _json_load_user(user_id) or {}
        return {
            "id": user_id,
            "language": stored.get("language", language),
            "onboarded": bool(stored.get("onboarded", False)),
        }

    async with _pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
        if row is not None:
            return row
        await conn.execute(
            "INSERT INTO users (id, language) VALUES ($1, $2) ON CONFLICT (id) DO NOTHING",
            user_id, language,
        )
        return await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)


async def set_user_onboarded(user_id: int) -> None:
    """Mark the user as having completed onboarding."""
    if not _use_db:
        # Persist in the JSON fallback too, otherwise onboarding state is lost on
        # every process start and returning users are onboarded over and over.
        stored = _json_load_user(user_id) or {"id": user_id}
        stored["onboarded"] = True
        try:
            _json_save_user(user_id, stored)
        except OSError:
            logger.warning("Could not persist onboarding state for user %s", user_id)
        return

    async with _pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET onboarded = TRUE, updated_at = now() WHERE id = $1",
            user_id,
        )


async def is_user_onboarded(user_id: int) -> bool:
    """Check whether a user has completed onboarding."""
    if not _use_db:
        stored = _json_load_user(user_id) or {}
        return bool(stored.get("onboarded", False))

    async with _pool.acquire() as conn:
        row = await conn.fetchval(
            "SELECT onboarded FROM users WHERE id = $1", user_id,
        )
        return bool(row)


async def get_user(user_id: int):
    """Return user row or None (None when the user has never been stored)."""
    if not _use_db:
        stored = _json_load_user(user_id)
        if stored is None:
            return None
        return {
            "id": user_id,
            "language": stored.get("language", "pt"),
            "onboarded": bool(stored.get("onboarded", False)),
        }

    async with _pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)


# ===================================================================
# Favorites
# ===================================================================

async def add_favorite(user_id: int, fav_type: str, stop_id: str, name: str) -> bool:
    """Add a favorite. Returns True if added, False if duplicate."""
    if not _use_db:
        favs = _json_load_favorites(user_id)
        if any(f["type"] == fav_type and f["id"] == stop_id for f in favs):
            return False
        favs.append({"type": fav_type, "id": stop_id, "name": name})
        _json_save_favorites(user_id, favs)
        return True

    await get_or_create_user(user_id)

    async with _pool.acquire() as conn:
        try:
            await conn.execute(
                "INSERT INTO favorites (user_id, type, stop_id, name) "
                "VALUES ($1, $2, $3, $4)",
                user_id, fav_type, stop_id, name,
            )
            return True
        except Exception as exc:
            if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                return False
            raise


async def remove_favorite(user_id: int, fav_type: str, stop_id: str) -> bool:
    """Remove a favorite. Returns True if something was deleted."""
    if not _use_db:
        favs = _json_load_favorites(user_id)
        new_favs = [f for f in favs if not (f["type"] == fav_type and f["id"] == stop_id)]
        if len(new_favs) == len(favs):
            return False
        _json_save_favorites(user_id, new_favs)
        return True

    async with _pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM favorites WHERE user_id = $1 AND type = $2 AND stop_id = $3",
            user_id, fav_type, stop_id,
        )
        return result.split()[-1] != "0"


async def get_favorites(user_id: int) -> list[dict]:
    """Return all favorites for a user as a list of dicts."""
    if not _use_db:
        return _json_load_favorites(user_id)

    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT type, stop_id, name FROM favorites "
            "WHERE user_id = $1 ORDER BY created_at",
            user_id,
        )
        return [{"type": r["type"], "id": r["stop_id"], "name": r["name"]} for r in rows]


async def get_favorite_count(user_id: int) -> int:
    """Return the number of favorites for a user."""
    if not _use_db:
        return len(_json_load_favorites(user_id))

    async with _pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM favorites WHERE user_id = $1", user_id,
        )


async def is_favorite(user_id: int, fav_type: str, stop_id: str) -> bool:
    """Check whether a specific stop is already a favorite."""
    if not _use_db:
        favs = _json_load_favorites(user_id)
        return any(f["type"] == fav_type and f["id"] == stop_id for f in favs)

    async with _pool.acquire() as conn:
        row = await conn.fetchval(
            "SELECT 1 FROM favorites WHERE user_id = $1 AND type = $2 AND stop_id = $3",
            user_id, fav_type, stop_id,
        )
        return row is not None


# ===================================================================
# User settings
# ===================================================================

def _json_settings_path(user_id: int) -> Path:
    _SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    return _SETTINGS_DIR / f"{user_id}.json"


def _json_load_settings(user_id: int) -> dict:
    path = _json_settings_path(user_id)
    if not path.exists():
        return dict(DEFAULT_SETTINGS)
    try:
        saved = json.loads(path.read_text())
        # Merge with defaults so new keys are always present
        return {**DEFAULT_SETTINGS, **saved}
    except (json.JSONDecodeError, OSError):
        return dict(DEFAULT_SETTINGS)


def _json_save_settings(user_id: int, settings: dict) -> None:
    path = _json_settings_path(user_id)
    path.write_text(json.dumps(settings, ensure_ascii=False, indent=2))


async def get_user_settings(user_id: int) -> dict:
    """Return the user's settings dict."""
    if not _use_db:
        return _json_load_settings(user_id)

    await get_or_create_user(user_id)
    async with _pool.acquire() as conn:
        # The column list is built from the _SETTINGS_COLUMNS allowlist, never
        # from caller input - see the comment next to _SETTINGS_COLUMNS.
        row = await conn.fetchrow(
            f"SELECT {_SETTINGS_SELECT_COLUMNS} FROM user_settings WHERE user_id = $1",
            user_id,
        )
        if row is None:
            return dict(DEFAULT_SETTINGS)
        # Start from the defaults so the returned dict always has exactly the same
        # keys as the JSON fallback path (parity), even for NULL/missing columns.
        result = dict(DEFAULT_SETTINGS)
        for key, column in _SETTINGS_COLUMNS.items():
            value = row[column]
            if value is not None:
                result[key] = value
        return result


async def update_user_setting(user_id: int, key: str, value) -> None:
    """Update a single setting for a user."""
    # Validate + translate the key into a physical column name.  Raises
    # ValueError for unknown keys, which is what keeps the identifier
    # interpolation below safe from SQL injection.
    column = _settings_column(key)

    if not _use_db:
        settings = _json_load_settings(user_id)
        settings[key] = value
        _json_save_settings(user_id, settings)
        return

    await get_or_create_user(user_id)
    async with _pool.acquire() as conn:
        # Upsert the settings row.  Only `column` is interpolated and it can only
        # ever be one of the hard-coded _SETTINGS_COLUMNS values; `value` is
        # always passed as a bound parameter.
        await conn.execute(
            f"""
            INSERT INTO user_settings (user_id, {column})
            VALUES ($1, $2)
            ON CONFLICT (user_id)
            DO UPDATE SET {column} = $2
            """,
            user_id, value,
        )


# ===================================================================
# Commuter profiles
# ===================================================================

_COMMUTER_DIR = DATA_DIR / "commuter"

DEFAULT_COMMUTER_PROFILE = {
    "home_name": "",
    "home_lat": 0.0,
    "home_lon": 0.0,
    "work_name": "",
    "work_lat": 0.0,
    "work_lon": 0.0,
    "preferred_mode": "any",
    "usual_departure_time": "08:00",
    "usual_return_time": "18:00",
}


def _json_commuter_path(user_id: int) -> Path:
    _COMMUTER_DIR.mkdir(parents=True, exist_ok=True)
    return _COMMUTER_DIR / f"{user_id}.json"


def _json_load_commuter(user_id: int) -> Optional[dict]:
    path = _json_commuter_path(user_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _json_save_commuter(user_id: int, profile: dict) -> None:
    path = _json_commuter_path(user_id)
    path.write_text(json.dumps(profile, ensure_ascii=False, indent=2))


def _json_delete_commuter(user_id: int) -> bool:
    path = _json_commuter_path(user_id)
    if path.exists():
        path.unlink()
        return True
    return False


async def save_commuter_profile(user_id: int, profile: dict) -> None:
    """Save a commuter profile for the user."""
    # Merge with defaults so all keys are present
    full = {**DEFAULT_COMMUTER_PROFILE, **profile}
    if not _use_db:
        _json_save_commuter(user_id, full)
        return

    await get_or_create_user(user_id)
    async with _pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO commuter_profiles (user_id, profile_data)
            VALUES ($1, $2::jsonb)
            ON CONFLICT (user_id)
            DO UPDATE SET profile_data = $2::jsonb, updated_at = now()
            """,
            user_id, json.dumps(full, ensure_ascii=False),
        )


async def get_commuter_profile(user_id: int) -> Optional[dict]:
    """Return the commuter profile for a user, or None."""
    if not _use_db:
        return _json_load_commuter(user_id)

    async with _pool.acquire() as conn:
        row = await conn.fetchval(
            "SELECT profile_data FROM commuter_profiles WHERE user_id = $1",
            user_id,
        )
        if row is None:
            return None
        if isinstance(row, str):
            return json.loads(row)
        return dict(row)


async def delete_commuter_profile(user_id: int) -> bool:
    """Delete a commuter profile. Returns True if something was deleted."""
    if not _use_db:
        return _json_delete_commuter(user_id)

    async with _pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM commuter_profiles WHERE user_id = $1", user_id,
        )
        return result.split()[-1] != "0"


# ===================================================================
# Migration helper
# ===================================================================

async def migrate_from_json(data_dir: Optional[str] = None) -> None:
    """Migrate existing JSON favorites into the database.

    Reads every ``<user_id>.json`` file in *data_dir*/favorites and inserts
    the entries into the ``favorites`` table.  Duplicates are silently
    skipped.
    """
    if not _use_db:
        logger.warning("migrate_from_json called but database is not active")
        return

    fav_dir = Path(data_dir) / "favorites" if data_dir else _FAVORITES_DIR
    if not fav_dir.exists():
        logger.info("No JSON favorites directory found at %s - nothing to migrate", fav_dir)
        return

    migrated = 0
    skipped = 0
    for json_file in fav_dir.glob("*.json"):
        try:
            user_id = int(json_file.stem)
        except ValueError:
            continue

        try:
            favs = json.loads(json_file.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning("Could not read %s - skipping", json_file)
            continue

        await get_or_create_user(user_id)

        for fav in favs:
            fav_type = fav.get("type", "")
            stop_id = fav.get("id", "")
            name = fav.get("name", stop_id)
            if not fav_type or not stop_id:
                continue
            added = await add_favorite(user_id, fav_type, stop_id, name)
            if added:
                migrated += 1
            else:
                skipped += 1

    logger.info(
        "JSON migration complete: %d favorites migrated, %d duplicates skipped",
        migrated, skipped,
    )
