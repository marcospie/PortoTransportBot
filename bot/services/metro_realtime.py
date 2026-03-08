"""Real-time Metro do Porto departures via the official trip planner.

The Metro do Porto website (metrodoporto.pt/pages/285) uses Google Maps
Directions API (JavaScript) to show real-time departure times.  By querying
trips from a station to its neighbours in opposite directions we can extract
the actual next departure time for each direction.

This module uses Playwright (headless Chromium) to render the page and parse
the results.  It falls back gracefully when Playwright is not installed.

Station IDs for the trip planner form are discovered automatically on first
run by reading the <select> options from the rendered page.
"""

import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

from bot.utils.cache import TTLCache

logger = logging.getLogger(__name__)

_cache = TTLCache(default_ttl=90)  # 90-second cache for real-time data

# Trip planner base URL
_TRIP_PLANNER_URL = "https://www.metrodoporto.pt/pages/285"

# Station ID mapping: station_name -> trip_planner_id
# Populated on first call via _discover_station_ids()
_station_ids: dict[str, int] = {}
_station_ids_loaded = False

# Playwright browser instance (reused)
_browser = None
_browser_lock = asyncio.Lock()

# Whether Playwright is available
_playwright_available: Optional[bool] = None


def _check_playwright() -> bool:
    """Check if Playwright is installed and the Chromium binary exists."""
    global _playwright_available
    if _playwright_available is not None:
        return _playwright_available
    try:
        import subprocess
        result = subprocess.run(
            ["python3", "-c",
             "from playwright.sync_api import sync_playwright; "
             "pw = sync_playwright().start(); "
             "import os; p = pw.chromium.executable_path; pw.stop(); "
             "exit(0 if os.path.exists(p) else 1)"],
            capture_output=True, timeout=10,
        )
        if result.returncode != 0:
            logger.warning("Chromium binary not found. Run: playwright install chromium")
            _playwright_available = False
        else:
            _playwright_available = True
    except ImportError:
        logger.warning("Playwright not installed — real-time metro data unavailable.")
        _playwright_available = False
    except Exception:
        logger.warning("Playwright check failed — disabling real-time data", exc_info=True)
        _playwright_available = False
    return _playwright_available


_pw_context = None  # Keep reference to prevent GC


async def _get_browser():
    """Get or create a shared Playwright browser instance."""
    global _browser, _pw_context
    async with _browser_lock:
        if _browser and _browser.is_connected():
            return _browser
        from playwright.async_api import async_playwright
        _pw_context = await async_playwright().start()
        _browser = await _pw_context.chromium.launch(headless=True)
        return _browser


async def _discover_station_ids() -> dict[str, int]:
    """Load the trip planner page and extract station IDs from the select."""
    global _station_ids, _station_ids_loaded

    if _station_ids_loaded and _station_ids:
        return _station_ids

    if not _check_playwright():
        return {}

    try:
        browser = await _get_browser()
        page = await browser.new_page()
        try:
            await page.goto(_TRIP_PLANNER_URL, wait_until="networkidle",
                            timeout=30000)
            # Wait for drawStations() to populate the select
            await page.wait_for_function(
                "document.querySelector('#Start') && "
                "document.querySelector('#Start').options.length > 1",
                timeout=15000,
            )

            options = await page.evaluate("""
                () => {
                    const sel = document.querySelector('#Start');
                    if (!sel) return [];
                    return Array.from(sel.options)
                        .filter(o => o.value)
                        .map(o => ({id: parseInt(o.value), name: o.text.trim()}));
                }
            """)

            _station_ids = {}
            for opt in options:
                if opt["id"] and opt["name"]:
                    _station_ids[opt["name"]] = opt["id"]

            _station_ids_loaded = True
            logger.info("Discovered %d station IDs from trip planner", len(_station_ids))
            return _station_ids
        finally:
            await page.close()
    except Exception:
        logger.exception("Failed to discover station IDs")
        return {}


def _match_station_id(station_name: str) -> Optional[int]:
    """Find the trip planner station ID for a station name using fuzzy matching."""
    if not _station_ids:
        return None

    # Exact match first
    if station_name in _station_ids:
        return _station_ids[station_name]

    # Case-insensitive match
    name_lower = station_name.lower()
    for name, sid in _station_ids.items():
        if name.lower() == name_lower:
            return sid

    # Partial match
    for name, sid in _station_ids.items():
        if name_lower in name.lower() or name.lower() in name_lower:
            return sid

    # Fuzzy: try removing accents, punctuation
    import unicodedata
    def _normalize(s):
        s = unicodedata.normalize("NFD", s)
        s = "".join(c for c in s if unicodedata.category(c) != "Mn")
        return s.lower().strip()

    norm_query = _normalize(station_name)
    for name, sid in _station_ids.items():
        if _normalize(name) == norm_query:
            return sid

    return None


def _get_neighbour_stations(station_name: str) -> list[str]:
    """Get neighbouring stations in opposite directions for a given station.

    Returns a list of up to 2 station names: one in each direction along
    the lines serving this station.
    """
    from bot.services.metro import STATIONS, get_line_stations

    station_data = STATIONS.get(station_name)
    if not station_data:
        return []

    neighbours = set()
    for line_code in station_data["lines"]:
        line_stations = get_line_stations(line_code)
        if station_name not in line_stations:
            continue
        idx = line_stations.index(station_name)
        if idx > 0:
            neighbours.add(line_stations[idx - 1])
        if idx < len(line_stations) - 1:
            neighbours.add(line_stations[idx + 1])

    # Return at most 2 neighbours (one per direction)
    return list(neighbours)[:2]


async def _scrape_trip(start_id: int, end_id: int,
                       day: str, time_str: str) -> Optional[dict]:
    """Scrape a single trip from the trip planner.

    Returns parsed trip data or None on failure.
    """
    if not _check_playwright():
        return None

    url = (f"{_TRIP_PLANNER_URL}?Start={start_id}&End={end_id}"
           f"&Type=1&Day={day}&Time={time_str}")

    try:
        browser = await _get_browser()
        page = await browser.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)

            # Wait for the directions panel to have content
            await page.wait_for_function(
                "document.querySelector('#metro-directions-panel') && "
                "document.querySelector('#metro-directions-panel').innerText.trim().length > 0",
                timeout=20000,
            )

            # Extract trip data from the rendered panel
            data = await page.evaluate("""
                () => {
                    const panel = document.querySelector('#metro-directions-panel');
                    if (!panel) return null;
                    const text = panel.innerText;
                    const html = panel.innerHTML;
                    return {text, html};
                }
            """)

            if not data or not data.get("text"):
                return None

            return _parse_trip_result(data["text"], data.get("html", ""))
        finally:
            await page.close()
    except Exception:
        logger.exception("Failed to scrape trip %d -> %d", start_id, end_id)
        return None


def _parse_trip_result(text: str, html: str = "") -> Optional[dict]:
    """Parse the trip planner result text to extract departure info.

    The rendered text typically looks like:
        Percurso
        10 minutos
        D. João II
        Metro em direção a Hospital São João
        13:45–13:55  (10 minutos, 5 paragens)
        São Bento
        ...
    """
    result = {}

    # Extract total duration
    dur_match = re.search(r'(\d+)\s*min', text)
    if dur_match:
        result["duration_min"] = int(dur_match.group(1))

    # Extract metro direction (headsign)
    dir_match = re.search(r'Metro em dire[çc][ãa]o a (.+)', text)
    if dir_match:
        result["direction"] = dir_match.group(1).strip()

    # Extract departure and arrival times (HH:MM–HH:MM pattern)
    time_match = re.search(r'(\d{1,2}:\d{2})\s*[–-]\s*(\d{1,2}:\d{2})', text)
    if time_match:
        result["departure_time"] = time_match.group(1)
        result["arrival_time"] = time_match.group(2)

    # Extract number of stops
    stops_match = re.search(r'(\d+)\s*parage[nm]', text)
    if stops_match:
        result["stops"] = int(stops_match.group(1))

    # Extract line color/letter from HTML (e.g., line D is yellow)
    line_match = re.search(
        r'background-color:\s*(?:rgb\((\d+),\s*(\d+),\s*(\d+)\)|#([0-9a-fA-F]{6}))',
        html,
    )
    if line_match:
        result["line_color"] = line_match.group(0)

    if not result.get("departure_time"):
        return None

    return result


async def get_realtime_departures(station_name: str,
                                   count: int = 4) -> list[dict]:
    """Get real-time departure estimates for a station.

    Strategy: query the trip planner for trips to neighbouring stations
    in opposite directions.  The departure time shown is real-time.

    Returns a list of departure dicts compatible with metro.get_next_departures().
    """
    cache_key = f"rt:{station_name}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    if not _check_playwright():
        return []

    # Ensure station IDs are loaded
    if not _station_ids:
        await _discover_station_ids()

    station_id = _match_station_id(station_name)
    if station_id is None:
        logger.warning("No trip planner ID for station: %s", station_name)
        return []

    # Get neighbours to query
    neighbours = _get_neighbour_stations(station_name)
    if not neighbours:
        return []

    now = datetime.now()
    day = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")

    # Query trips to each neighbour in parallel
    tasks = []
    for neighbour in neighbours:
        nid = _match_station_id(neighbour)
        if nid is None:
            continue
        tasks.append(_scrape_trip(station_id, nid, day, time_str))

    if not tasks:
        return []

    results = await asyncio.gather(*tasks, return_exceptions=True)

    departures = []
    from bot.config import METRO_LINES

    for trip in results:
        if isinstance(trip, Exception) or trip is None:
            continue

        dep_time_str = trip.get("departure_time")
        if not dep_time_str:
            continue

        # Calculate minutes until departure
        try:
            parts = dep_time_str.split(":")
            dep_dt = now.replace(hour=int(parts[0]), minute=int(parts[1]),
                                 second=0, microsecond=0)
            if dep_dt < now:
                dep_dt += timedelta(days=1)
            minutes_until = (dep_dt - now).total_seconds() / 60
        except (ValueError, IndexError):
            continue

        if minutes_until < 0:
            continue

        if minutes_until < 1:
            time_display = "< 1 min"
        elif minutes_until < 60:
            time_display = f"{int(minutes_until)} min"
        else:
            time_display = dep_time_str

        direction = trip.get("direction", "")

        # Try to identify the line from the direction/headsign
        line_code = ""
        line_display = "🚇 Metro"
        for code, data in METRO_LINES.items():
            route = data.get("route", "")
            endpoints = route.split(" ↔ ")
            for ep in endpoints:
                if direction and ep.lower() in direction.lower():
                    line_code = code
                    line_display = f"{data['emoji']} {data['name']}"
                    break
            if line_code:
                break

        departures.append({
            "direction": direction,
            "time": time_display,
            "line": line_display,
            "line_code": line_code,
            "minutes": int(minutes_until),
            "estimated": False,
            "realtime": True,
        })

    departures.sort(key=lambda x: x.get("minutes", 999))
    departures = departures[:count]

    _cache.set(cache_key, departures)
    return departures


async def close():
    """Close the shared browser instance."""
    global _browser
    if _browser:
        try:
            await _browser.close()
        except Exception:
            pass
        _browser = None
