"""PostgreSQL database layer with JSON file fallback.

If DATABASE_URL is set, uses asyncpg connection pool.
Otherwise, falls back to the existing JSON file storage.
"""

import json
import logging
import os
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
    digest_days     VARCHAR(50) NOT NULL DEFAULT 'weekdays'
);
"""

# Migrations for existing tables (add columns if missing)
_MIGRATIONS_SQL = [
    "ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS metro_radius_m INTEGER NOT NULL DEFAULT 500",
    "ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS bus_radius_m INTEGER NOT NULL DEFAULT 200",
    "ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS max_results INTEGER NOT NULL DEFAULT 5",
    "ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS language VARCHAR(10) NOT NULL DEFAULT 'auto'",
]

# ===================================================================
# JSON fallback helpers (mirrors the original favorites.py logic)
# ===================================================================
from bot.config import DATA_DIR  # noqa: E402

_FAVORITES_DIR = DATA_DIR / "favorites"
_SETTINGS_DIR = DATA_DIR / "settings"

# Default settings values
DEFAULT_SETTINGS = {
    "metro_radius_m": 500,
    "bus_radius_m": 200,
    "max_results": 5,
    "language": "auto",
}


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

async def init_db() -> None:
    """Create the connection pool and ensure schema exists.

    If DATABASE_URL is not set the function silently enables JSON fallback.
    """
    global _pool, _use_db

    database_url = os.getenv("DATABASE_URL", "")
    if not database_url:
        logger.info("DATABASE_URL not set - using JSON file fallback for storage")
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

async def get_or_create_user(user_id: int, language: str = "pt"):
    """Return the user row, creating it if it does not exist."""
    if not _use_db:
        return {"id": user_id, "language": language, "onboarded": False}

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
        return

    async with _pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET onboarded = TRUE, updated_at = now() WHERE id = $1",
            user_id,
        )


async def get_user(user_id: int):
    """Return user row or None."""
    if not _use_db:
        return None

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
        row = await conn.fetchrow(
            "SELECT metro_radius_m, bus_radius_m, max_results, language "
            "FROM user_settings WHERE user_id = $1",
            user_id,
        )
        if row is None:
            return dict(DEFAULT_SETTINGS)
        return {
            "metro_radius_m": row["metro_radius_m"],
            "bus_radius_m": row["bus_radius_m"],
            "max_results": row["max_results"],
            "language": row["language"],
        }


async def update_user_setting(user_id: int, key: str, value) -> None:
    """Update a single setting for a user."""
    if key not in DEFAULT_SETTINGS:
        raise ValueError(f"Unknown setting: {key}")

    if not _use_db:
        settings = _json_load_settings(user_id)
        settings[key] = value
        _json_save_settings(user_id, settings)
        return

    await get_or_create_user(user_id)
    async with _pool.acquire() as conn:
        # Upsert the settings row
        await conn.execute(
            f"""
            INSERT INTO user_settings (user_id, {key})
            VALUES ($1, $2)
            ON CONFLICT (user_id)
            DO UPDATE SET {key} = $2
            """,
            user_id, value,
        )


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
