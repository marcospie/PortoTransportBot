"""Service alerts (disruptions, engineering works, notices) for Porto transport.

Honesty rules this module enforces:

* It never invents alerts.  There used to be a ``_FALLBACK_ALERTS`` list that
  was served whenever the (non-existent) upstream APIs failed, which meant every
  user permanently saw a fabricated "Manutenção programada - Metro Linha
  Amarela" notice.  That list is gone.
* When no source can be consulted, the result is an **empty** list flagged with
  ``source_available=False`` so the caller can say "não foi possível verificar
  alertas" instead of either inventing alerts or claiming "tudo normal".
* An empty ``affected_lines`` means *network-wide*, and that is handled
  explicitly (``scope`` field + ``include_network_wide`` arguments) rather than
  accidentally matching every line query.

Upstream status, verified with live requests on 2026-07-26:

* ``https://stcp.pt/pt/alteracoes-de-servico`` -> **200**, HTML, 59 current
  service-change cards, each with a date, a title naming the cause and an
  explicit list of affected line numbers.  This is the source used for buses.
* ``https://www.metrodoporto.pt/pages/862.rss`` -> **200**, valid RSS 2.0 with
  30 items.  Corporate/PR news with occasional operational items (e.g. the
  summer-timetable switch), so it is keyword-filtered and date-limited.
* ``https://stcp.pt/api/alerts`` -> **404** (no JSON alerts route exists; the
  whole ``/api/{alerts,notices,news,avisos,disruptions,...}`` family 404s).
* ``https://www.metrodoporto.pt/api/alerts`` -> **404**.  No ``/wp-json``, no
  ``/feed``, no sitemap.
* MOTIS (``europe.motis-project.de``) exposes **no** alerts endpoint and its
  Porto feeds are static GTFS only (``realTime: false`` on every stop time), so
  there is no GTFS-RT ServiceAlert feed for Porto to consume.
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from xml.etree import ElementTree

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

# Alert scope: does the alert name specific lines/stops or the whole network?
SCOPE_LINE = "line"
SCOPE_STOP = "stop"
SCOPE_NETWORK = "network"

# Severity sort order (high first)
_SEVERITY_ORDER = {SEVERITY_HIGH: 0, SEVERITY_MEDIUM: 1, SEVERITY_LOW: 2}

# There is deliberately NO fallback alert list. See the module docstring.

REQUEST_TIMEOUT = 8
# Negative caching: while every source is failing, do not retry on every
# request — a down source must not cost each user a full timeout.
FAILURE_TTL = 120
_FAILURE_KEY = "alerts:sources-down"

# STCP's public "Alterações de Serviço" page: the only real Porto disruption
# listing.  Server-rendered HTML, no JSON equivalent exists.
STCP_SERVICE_CHANGES_URL = "https://stcp.pt/pt/alteracoes-de-servico"
STCP_DETAIL_BASE = "https://stcp.pt"

# Metro do Porto news RSS.  The page id is scoped per year (770=2023, 813=2024,
# 833=2025, 862=2026) and is not derivable from the year, so unknown years fall
# back to the newest known feed — whose items are then filtered out by the
# recency window below, yielding nothing rather than something wrong.
METRO_NEWS_RSS_BY_YEAR = {
    2023: "https://www.metrodoporto.pt/pages/770.rss",
    2024: "https://www.metrodoporto.pt/pages/813.rss",
    2025: "https://www.metrodoporto.pt/pages/833.rss",
    2026: "https://www.metrodoporto.pt/pages/862.rss",
}
# Metro news is corporate/PR, so only recent, disruption-shaped items count.
METRO_NEWS_MAX_AGE_DAYS = 21

# The service-change list is long (59 entries on 2026-07-26) and a Telegram
# message caps at ~4096 chars, so get_active_alerts() returns the most relevant
# slice and reports the true total via AlertsResult.total_available.
DEFAULT_MAX_ALERTS = 15

# Keywords that mark a site notice as service-affecting rather than marketing.
_DISRUPTION_KEYWORDS = (
    "supress", "suprimid", "interrup", "constrangimento", "encerrad",
    "encerramento", "desvio", "condicionad", "greve", "avaria", "atras",
    "obras", "manutenção", "manutencao", "substitui", "sem serviço",
    "sem servico", "alteração", "alteracao",
)
_HIGH_SEVERITY_KEYWORDS = ("greve", "interrup", "supress", "encerrad", "avaria")
_ENGINEERING_KEYWORDS = ("obras", "manutenção", "manutencao", "intervenção")

# "Linha D" -> D.  The line letter must be UPPERCASE: a case-insensitive match
# happily read the Portuguese conjunction in "linha e outros" as Line E.
_LINE_PATTERN = re.compile(r"\b[Ll]inhas?\s+([A-F])\b")
# Metro lines are usually named by colour rather than by letter.
_LINE_COLOURS = {
    "azul": "A", "vermelha": "B", "verde": "C",
    "amarela": "D", "violeta": "E", "laranja": "F",
}
_LINE_COLOUR_PATTERN = re.compile(
    r"\b[Ll]inhas?\s+(" + "|".join(_LINE_COLOURS) + r")\b", re.IGNORECASE)


class AlertsResult(list):
    """A list of alerts that also reports whether any source was reachable.

    Subclasses :class:`list` so existing callers (``for a in alerts``,
    ``if not alerts``) keep working unchanged, while newer callers can inspect
    :attr:`source_available` to tell "no disruptions reported" apart from
    "we could not check".
    """

    def __init__(self, items=(), *, source_available: bool = False,
                 sources_ok: list[str] | None = None,
                 sources_failed: list[str] | None = None,
                 checked_at: str | None = None,
                 total_available: int | None = None):
        super().__init__(items)
        self.source_available = source_available
        self.sources_ok = sources_ok or []
        self.sources_failed = sources_failed or []
        self.checked_at = checked_at
        #: How many alerts the sources actually reported, before any capping.
        self.total_available = (len(self) if total_available is None
                                else total_available)

    @property
    def truncated(self) -> bool:
        """True when more alerts exist upstream than are included here."""
        return self.total_available > len(self)


def _as_result(value) -> AlertsResult:
    """Coerce a plain list (e.g. a pre-seeded cache entry) into AlertsResult."""
    if isinstance(value, AlertsResult):
        return value
    return AlertsResult(value or [], source_available=True,
                        sources_ok=["cache"])


def _derive(source: AlertsResult, items: list[dict]) -> AlertsResult:
    """Build a filtered result that keeps the original source metadata."""
    return AlertsResult(
        items,
        source_available=getattr(source, "source_available", True),
        sources_ok=list(getattr(source, "sources_ok", [])),
        sources_failed=list(getattr(source, "sources_failed", [])),
        checked_at=getattr(source, "checked_at", None),
        total_available=len(items),
    )


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
    url: str | None = None,
) -> dict:
    """Create a standardised alert dict.

    An alert with neither ``affected_lines`` nor ``affected_stops`` gets
    ``scope == SCOPE_NETWORK``: it applies to the whole network, which is not
    the same thing as applying to every individual line query.
    """
    lines = list(affected_lines or [])
    stops = list(affected_stops or [])
    if lines:
        scope = SCOPE_LINE
    elif stops:
        scope = SCOPE_STOP
    else:
        scope = SCOPE_NETWORK
    return {
        "id": alert_id,
        "type": alert_type,
        "title": title,
        "description": description,
        "affected_lines": lines,
        "affected_stops": stops,
        "start_time": start_time,
        "end_time": end_time,
        "severity": severity,
        "source": source,
        "scope": scope,
        "url": url,
    }


def is_network_wide(alert: dict) -> bool:
    """True when an alert names no specific line or stop."""
    if alert.get("scope"):
        return alert["scope"] == SCOPE_NETWORK
    return not alert.get("affected_lines") and not alert.get("affected_stops")


# ---------------------------------------------------------------------------
# Upstream sources
# ---------------------------------------------------------------------------

def _strip_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _looks_like_disruption(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in _DISRUPTION_KEYWORDS)


def _classify(text: str) -> tuple[str, str]:
    """Guess (type, severity) from a notice's wording."""
    lowered = text.lower()
    if any(k in lowered for k in _ENGINEERING_KEYWORDS):
        alert_type = TYPE_ENGINEERING
    elif any(k in lowered for k in ("supress", "interrup", "encerrad", "greve")):
        alert_type = TYPE_DISRUPTION
    elif "atras" in lowered:
        alert_type = TYPE_DELAY
    else:
        alert_type = TYPE_INFO

    if any(k in lowered for k in _HIGH_SEVERITY_KEYWORDS):
        severity = SEVERITY_HIGH
    elif alert_type in (TYPE_ENGINEERING, TYPE_DELAY):
        severity = SEVERITY_MEDIUM
    else:
        severity = SEVERITY_LOW
    return alert_type, severity


def _extract_lines(text: str) -> list[str]:
    """Extract metro line codes explicitly named in a notice.

    Matches both "Linha D" and "Linha Amarela". Only explicit mentions count —
    an alert that names no line stays network-wide rather than being guessed
    onto a line.
    """
    found: list[str] = []
    for match in _LINE_PATTERN.finditer(text or ""):
        code = match.group(1).upper()
        if code not in found:
            found.append(code)
    for match in _LINE_COLOUR_PATTERN.finditer(text or ""):
        code = _LINE_COLOURS[match.group(1).lower()]
        if code not in found:
            found.append(code)
    return found


async def _fetch_text(url: str) -> str:
    async with aiohttp.ClientSession() as session:
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            headers={"User-Agent": "PortoTransportBot/1.0"},
        ) as resp:
            if resp.status != 200:
                raise RuntimeError(f"HTTP {resp.status}")
            return await resp.text()


# --- STCP service changes (HTML) -------------------------------------------

_CARD_RE = re.compile(
    r'<div class="card regular-shadow">(.*?)'
    r'<a href="([^"]*)" class="view-details"', re.S)
_DATE_RE = re.compile(r'<div class="date">(.*?)</div>', re.S)
_TITLE_RE = re.compile(r'<span class="list-change-title">(.*?)</span>', re.S)
_LINE_DIV_RE = re.compile(r'<div class="line[^"]*"\s*>(.*?)</div>', re.S)
_RESUME_RE = re.compile(r'<div class="resume">(.*?)</div>', re.S)

_PT_MONTHS = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8, "setembro": 9,
    "outubro": 10, "novembro": 11, "dezembro": 12,
}
# Closed single day ("DIA 27 JULHO 2026") or range ("ENTRE DIA 27 E 29 JULHO 2026")
_CLOSED_DATE_RE = re.compile(
    r"(?:ENTRE\s+DIA\s+(\d{1,2})\s+E\s+|DIA\s+)(\d{1,2})\s+"
    r"([A-ZÇÃÂÉÊÍÓÔÚa-zçãâéêíóôú]+)\s+(\d{4})", re.IGNORECASE)


def _parse_closed_end_date(date_text: str) -> str | None:
    """Return an ISO end timestamp when the notice names a closed date range.

    Open-ended wordings ("A PARTIR ...", "DESDE ...") return None so nothing is
    ever expired on a guess.
    """
    match = _CLOSED_DATE_RE.search(date_text or "")
    if not match:
        return None
    _first, day, month_name, year = match.groups()
    month = _PT_MONTHS.get(month_name.lower())
    if not month:
        return None
    try:
        # End of the last named day.
        return datetime(int(year), month, int(day), 23, 59).isoformat()
    except ValueError:
        return None


def _parse_stcp_service_changes(html_text: str) -> list[dict]:
    """Parse the STCP "Alterações de Serviço" listing into alert dicts."""
    alerts: list[dict] = []
    for index, match in enumerate(_CARD_RE.finditer(html_text)):
        block, href = match.group(1), match.group(2)
        title_match = _TITLE_RE.search(block)
        if not title_match:
            continue
        title = _strip_html(title_match.group(1))
        if not title:
            continue

        date_match = _DATE_RE.search(block)
        date_text = _strip_html(date_match.group(1)) if date_match else ""
        resume_match = _RESUME_RE.search(block)
        resume = _strip_html(resume_match.group(1)) if resume_match else ""

        lines = [_strip_html(l) for l in _LINE_DIV_RE.findall(block)]
        lines = [l for l in lines if l]

        alert_type, severity = _classify(f"{title} {resume}")
        description = " · ".join(p for p in (date_text, resume) if p)
        slug = href.rstrip("/").rsplit("/", 1)[-1] or str(index)

        alerts.append(_make_alert(
            alert_id=f"stcp_{slug}",
            alert_type=alert_type,
            title=title.title() if title.isupper() else title,
            description=description,
            affected_lines=lines,
            end_time=_parse_closed_end_date(date_text),
            severity=severity,
            source="stcp",
            url=f"{STCP_DETAIL_BASE}{href}" if href.startswith("/") else href,
        ))
    return alerts


async def _fetch_stcp_alerts() -> list[dict]:
    """Fetch current STCP service changes.

    Raises when the source cannot be consulted, so the caller records the source
    as unavailable rather than as "nothing to report".
    """
    html_text = await _fetch_text(STCP_SERVICE_CHANGES_URL)
    alerts = _parse_stcp_service_changes(html_text)
    if not alerts and "list-change" not in html_text:
        # The page shape changed — do not silently report "no disruptions".
        raise RuntimeError("STCP service-changes page could not be parsed")
    return alerts


# --- Metro do Porto news (RSS) --------------------------------------------

def _metro_rss_url(year: int | None = None) -> str:
    year = year or datetime.now().year
    if year in METRO_NEWS_RSS_BY_YEAR:
        return METRO_NEWS_RSS_BY_YEAR[year]
    newest_year = max(METRO_NEWS_RSS_BY_YEAR)
    logger.warning(
        "No Metro do Porto news feed id known for %d; falling back to the %d "
        "feed (its items will be too old to count as current alerts)",
        year, newest_year)
    return METRO_NEWS_RSS_BY_YEAR[newest_year]


def _parse_metro_rss(xml_text: str) -> list[dict]:
    """Parse Metro do Porto's news RSS, keeping only recent service notices."""
    root = ElementTree.fromstring(xml_text)
    cutoff = datetime.now(timezone.utc) - timedelta(days=METRO_NEWS_MAX_AGE_DAYS)

    alerts: list[dict] = []
    for item in root.findall("./channel/item"):
        title = _strip_html(item.findtext("title") or "")
        body = _strip_html(item.findtext("description") or "")
        if not title:
            continue

        published = None
        raw_date = item.findtext("pubDate")
        if raw_date:
            try:
                published = parsedate_to_datetime(raw_date)
                if published.tzinfo is None:
                    published = published.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                published = None
        # PR news dominates this feed; only recent, disruption-shaped items
        # may be surfaced as alerts.
        if published is None or published < cutoff:
            continue
        # Match on the title only: this feed is mostly corporate/PR news whose
        # bodies happen to contain words like "manutenção", which turned press
        # releases into fake service alerts.
        if not _looks_like_disruption(title):
            continue

        combined = f"{title} {body}"
        alert_type, severity = _classify(combined)
        alerts.append(_make_alert(
            alert_id=f"metro_{item.findtext('guid') or title[:40]}",
            alert_type=alert_type,
            title=title,
            description=body[:400],
            affected_lines=_extract_lines(combined),
            start_time=published.isoformat(),
            severity=severity,
            source="metro",
            url=item.findtext("link"),
        ))
    return alerts


async def _fetch_metro_alerts() -> list[dict]:
    """Fetch Metro do Porto service notices from its news RSS feed.

    Raises when the feed cannot be consulted or parsed.
    """
    xml_text = await _fetch_text(_metro_rss_url())
    return _parse_metro_rss(xml_text)


# Sources queried, in order.
_SOURCE_NAMES = ("metro", "stcp")


async def _fetch_source(name: str) -> list[dict]:
    """Dispatch to a source fetcher by name.

    The indirection matters: resolving ``_fetch_*`` at call time (rather than
    holding function objects in a tuple built at import) is what lets callers
    and tests patch ``bot.services.alerts._fetch_stcp_alerts`` and actually
    affect this module.
    """
    if name == "stcp":
        return await _fetch_stcp_alerts()
    if name == "metro":
        return await _fetch_metro_alerts()
    raise ValueError(f"unknown alert source: {name}")


def _sort_alerts(alerts: list[dict]) -> list[dict]:
    """Sort alerts by severity (high first), then by type."""
    return sorted(alerts, key=lambda a: (
        _SEVERITY_ORDER.get(a.get("severity", SEVERITY_LOW), 99),
        a.get("type", ""),
    ))


def _drop_expired(alerts: list[dict]) -> list[dict]:
    now = datetime.now()
    active: list[dict] = []
    for alert in alerts:
        end = alert.get("end_time")
        if end:
            try:
                end_dt = datetime.fromisoformat(end)
                if end_dt.tzinfo is not None:
                    end_dt = end_dt.astimezone().replace(tzinfo=None)
                if end_dt < now:
                    continue
            except (ValueError, TypeError):
                pass
        active.append(alert)
    return active


def reset_cache() -> None:
    """Clear cached alerts and failure back-off (tests, manual refresh)."""
    _cache.clear()


async def get_active_alerts(limit: int | None = DEFAULT_MAX_ALERTS) -> AlertsResult:
    """Return currently active alerts, sorted by severity.

    The return value is an :class:`AlertsResult` — a plain list of alert dicts
    that additionally exposes ``source_available``, ``total_available`` and
    ``truncated``.  An empty result with ``source_available is False`` means *we
    could not check*, which callers must not present as "everything is running
    normally".

    Args:
        limit: Maximum number of alerts to include (``None`` for all).  STCP
            routinely lists ~60 service changes, which does not fit in one
            Telegram message; ``total_available`` reports the real count.

    Never returns invented alerts.
    """
    cached = _cache.get(ALERTS_CACHE_KEY)
    if cached is not None:
        return _limit(_as_result(cached), limit)

    down = _cache.get(_FAILURE_KEY)
    if down is not None:
        return AlertsResult(source_available=False, sources_failed=list(down))

    alerts: list[dict] = []
    sources_ok: list[str] = []
    sources_failed: list[str] = []

    for name in _SOURCE_NAMES:
        try:
            fetched = await _fetch_source(name)
        except Exception as exc:
            logger.warning("Alert source %r unavailable: %s", name, exc)
            sources_failed.append(name)
            continue
        sources_ok.append(name)
        alerts.extend(fetched)

    active = _sort_alerts(_drop_expired(alerts))
    result = AlertsResult(
        active,
        source_available=bool(sources_ok),
        sources_ok=sources_ok,
        sources_failed=sources_failed,
        checked_at=datetime.now(timezone.utc).isoformat(),
        total_available=len(active),
    )

    if sources_ok:
        _cache.set(ALERTS_CACHE_KEY, result, ttl=300)
    else:
        # Nothing reachable: remember that briefly so a down source is not
        # retried (with a full timeout) on every single user request.
        logger.warning("No alert source could be reached (%s) — reporting "
                       "'unable to check' rather than 'no alerts'",
                       ", ".join(sources_failed) or "none configured")
        _cache.set(_FAILURE_KEY, sources_failed, ttl=FAILURE_TTL)
    return _limit(result, limit)


def _limit(result: AlertsResult, limit: int | None) -> AlertsResult:
    """Cap a result's length while preserving its true ``total_available``."""
    if limit is None or len(result) <= limit:
        return result
    return AlertsResult(
        list(result)[:limit],
        source_available=result.source_available,
        sources_ok=list(result.sources_ok),
        sources_failed=list(result.sources_failed),
        checked_at=result.checked_at,
        total_available=result.total_available,
    )


async def get_alerts_status() -> dict:
    """Alerts plus an explicit description of the data-source situation.

    Returns a dict with ``alerts``, ``source_available``, ``sources_ok``,
    ``sources_failed`` and bilingual ``message_pt``/``message_en`` fields
    describing the state ("no alerts" vs. "could not check").
    """
    alerts = await get_active_alerts(limit=None)
    if not alerts.source_available:
        message_pt = ("Não foi possível verificar alertas de serviço. "
                      "Consulta metrodoporto.pt ou stcp.pt.")
        message_en = ("Service alerts could not be checked. "
                      "See metrodoporto.pt or stcp.pt.")
    elif not alerts:
        message_pt = "Sem alertas de serviço comunicados."
        message_en = "No service alerts reported."
    else:
        message_pt = f"{len(alerts)} alerta(s) de serviço."
        message_en = f"{len(alerts)} service alert(s)."
    return {
        "alerts": list(alerts),
        "source_available": alerts.source_available,
        "sources_ok": list(alerts.sources_ok),
        "sources_failed": list(alerts.sources_failed),
        "checked_at": alerts.checked_at,
        "message_pt": message_pt,
        "message_en": message_en,
    }


async def get_alerts_for_line(line: str,
                              include_network_wide: bool = True) -> AlertsResult:
    """Return active alerts affecting a specific line.

    Args:
        line: Line code, e.g. ``"D"`` (case-insensitive).
        include_network_wide: Whether alerts with an empty ``affected_lines``
            (i.e. network-wide notices) should be included.  They are included
            by default because they really do affect this line, but they are
            matched *explicitly* — an alert that names no line is network-wide,
            not "a match for every line".
    """
    all_alerts = _as_result(await get_active_alerts(limit=None))
    line_upper = line.upper()
    matched = [
        a for a in all_alerts
        if line_upper in [l.upper() for l in a.get("affected_lines", [])]
        or (include_network_wide and is_network_wide(a))
    ]
    return _derive(all_alerts, matched)


async def get_alerts_for_stop(stop_id: str,
                              include_network_wide: bool = True) -> AlertsResult:
    """Return active alerts affecting a specific stop.

    ``include_network_wide`` controls whether network-wide alerts (no stop and
    no line named) are included.
    """
    all_alerts = _as_result(await get_active_alerts(limit=None))
    stop_upper = stop_id.upper()
    matched = [
        a for a in all_alerts
        if stop_upper in [s.upper() for s in a.get("affected_stops", [])]
        or (include_network_wide and is_network_wide(a))
    ]
    return _derive(all_alerts, matched)


def has_alerts_for_line(alerts: list[dict], line: str,
                        include_network_wide: bool = False) -> bool:
    """Check whether any alert names this line (for pre-fetched alerts).

    Used for per-line badges, so network-wide alerts are excluded by default:
    badging every line because of one generic notice is exactly the bug this
    replaces.  Pass ``include_network_wide=True`` to opt in.
    """
    line_upper = line.upper()
    return any(
        line_upper in [l.upper() for l in a.get("affected_lines", [])]
        or (include_network_wide and is_network_wide(a))
        for a in alerts
    )


def has_alerts_for_stop(alerts: list[dict], stop_id: str,
                        include_network_wide: bool = False) -> bool:
    """Check whether any alert names this stop (for pre-fetched alerts)."""
    stop_upper = stop_id.upper()
    return any(
        stop_upper in [s.upper() for s in a.get("affected_stops", [])]
        or (include_network_wide and is_network_wide(a))
        for a in alerts
    )
