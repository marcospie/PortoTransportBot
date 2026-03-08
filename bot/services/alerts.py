"""Service for fetching and managing service alerts for Porto transport."""

import logging
from datetime import datetime, timedelta

import aiohttp

from bot.utils.cache import TTLCache

logger = logging.getLogger(__name__)

_cache = TTLCache(default_ttl=300)  # 5-minute TTL

ALERTS_CACHE_KEY = "alerts:active"

# Alert severity levels
SEVERITY_HIGH = "high"
SEVERITY_MEDIUM = "medium"
SEVERITY_LOW = "low"

# Alert types
TYPE_DELAY = "delay"
TYPE_DISRUPTION = "disruption"
TYPE_INFO = "info"
TYPE_ENGINEERING = "engineering"

# Severity sort order (high first)
_SEVERITY_ORDER = {SEVERITY_HIGH: 0, SEVERITY_MEDIUM: 1, SEVERITY_LOW: 2}

# Fallback alerts for known common situations
_FALLBACK_ALERTS: list[dict] = [
    {
        "id": "fallback_1",
        "type": TYPE_INFO,
        "title": "Horário reduzido ao fim-de-semana",
        "description": "Frequências reduzidas nos autocarros STCP ao sábado e domingo.",
        "affected_lines": [],
        "affected_stops": [],
        "start_time": None,
        "end_time": None,
        "severity": SEVERITY_LOW,
        "source": "fallback",
    },
    {
        "id": "fallback_2",
        "type": TYPE_ENGINEERING,
        "title": "Manutenção programada - Metro Linha Amarela",
        "description": "Trabalhos de manutenção na Linha D (Amarela) podem causar atrasos pontuais.",
        "affected_lines": ["D"],
        "affected_stops": [],
        "start_time": None,
        "end_time": None,
        "severity": SEVERITY_MEDIUM,
        "source": "fallback",
    },
]

STCP_ALERTS_URL = "https://stcp.pt/api/alerts"
METRO_ALERTS_URL = "https://www.metrodoporto.pt/api/alerts"


def _make_alert(
    alert_id: str,
    alert_type: str,
    title: str,
    description: str,
    affected_lines: list[str] | None = None,
    affected_stops: list[str] | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    severity: str = SEVERITY_LOW,
    source: str = "api",
) -> dict:
    """Create a standardised alert dict."""
    return {
        "id": alert_id,
        "type": alert_type,
        "title": title,
        "description": description,
        "affected_lines": affected_lines or [],
        "affected_stops": affected_stops or [],
        "start_time": start_time,
        "end_time": end_time,
        "severity": severity,
        "source": source,
    }


async def _fetch_stcp_alerts() -> list[dict]:
    """Try to fetch alerts from STCP API. Returns empty list on failure."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(STCP_ALERTS_URL, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                alerts = []
                for item in data if isinstance(data, list) else data.get("alerts", []):
                    alerts.append(_make_alert(
                        alert_id=f"stcp_{item.get('id', '')}",
                        alert_type=item.get("type", TYPE_INFO),
                        title=item.get("title", "Alerta STCP"),
                        description=item.get("description", ""),
                        affected_lines=item.get("affected_lines", []),
                        affected_stops=item.get("affected_stops", []),
                        start_time=item.get("start_time"),
                        end_time=item.get("end_time"),
                        severity=item.get("severity", SEVERITY_LOW),
                        source="stcp",
                    ))
                return alerts
    except Exception:
        logger.debug("Could not fetch STCP alerts - using fallback")
        return []


async def _fetch_metro_alerts() -> list[dict]:
    """Try to fetch alerts from Metro do Porto. Returns empty list on failure."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(METRO_ALERTS_URL, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                alerts = []
                for item in data if isinstance(data, list) else data.get("alerts", []):
                    alerts.append(_make_alert(
                        alert_id=f"metro_{item.get('id', '')}",
                        alert_type=item.get("type", TYPE_INFO),
                        title=item.get("title", "Alerta Metro"),
                        description=item.get("description", ""),
                        affected_lines=item.get("affected_lines", []),
                        affected_stops=item.get("affected_stops", []),
                        start_time=item.get("start_time"),
                        end_time=item.get("end_time"),
                        severity=item.get("severity", SEVERITY_LOW),
                        source="metro",
                    ))
                return alerts
    except Exception:
        logger.debug("Could not fetch Metro alerts - using fallback")
        return []


def _sort_alerts(alerts: list[dict]) -> list[dict]:
    """Sort alerts by severity (high first), then by type."""
    return sorted(alerts, key=lambda a: (
        _SEVERITY_ORDER.get(a.get("severity", SEVERITY_LOW), 99),
        a.get("type", ""),
    ))


async def get_active_alerts() -> list[dict]:
    """Return all currently active alerts, sorted by severity.

    Uses a 5-minute TTL cache. Falls back to known common alerts when
    the live APIs are unreachable.
    """
    cached = _cache.get(ALERTS_CACHE_KEY)
    if cached is not None:
        return cached

    alerts: list[dict] = []

    stcp_alerts = await _fetch_stcp_alerts()
    metro_alerts = await _fetch_metro_alerts()

    alerts.extend(stcp_alerts)
    alerts.extend(metro_alerts)

    # If we got nothing from the APIs, use fallback alerts
    if not alerts:
        alerts = list(_FALLBACK_ALERTS)

    # Filter out expired alerts
    now = datetime.now()
    active: list[dict] = []
    for alert in alerts:
        end = alert.get("end_time")
        if end:
            try:
                end_dt = datetime.fromisoformat(end)
                if end_dt < now:
                    continue
            except (ValueError, TypeError):
                pass
        active.append(alert)

    result = _sort_alerts(active)
    _cache.set(ALERTS_CACHE_KEY, result, ttl=300)
    return result


async def get_alerts_for_line(line: str) -> list[dict]:
    """Return active alerts that affect a specific line."""
    all_alerts = await get_active_alerts()
    line_upper = line.upper()
    return [
        a for a in all_alerts
        if line_upper in [l.upper() for l in a.get("affected_lines", [])]
        or not a.get("affected_lines")  # alerts with no specific line affect all
    ]


async def get_alerts_for_stop(stop_id: str) -> list[dict]:
    """Return active alerts that affect a specific stop."""
    all_alerts = await get_active_alerts()
    stop_upper = stop_id.upper()
    return [
        a for a in all_alerts
        if stop_upper in [s.upper() for s in a.get("affected_stops", [])]
        or (not a.get("affected_stops") and not a.get("affected_lines"))
    ]


def has_alerts_for_line(alerts: list[dict], line: str) -> bool:
    """Check if any alert affects a given line (synchronous, for use with pre-fetched alerts)."""
    line_upper = line.upper()
    return any(
        line_upper in [l.upper() for l in a.get("affected_lines", [])]
        for a in alerts
    )


def has_alerts_for_stop(alerts: list[dict], stop_id: str) -> bool:
    """Check if any alert affects a given stop (synchronous, for use with pre-fetched alerts)."""
    stop_upper = stop_id.upper()
    return any(
        stop_upper in [s.upper() for s in a.get("affected_stops", [])]
        for a in alerts
    )
