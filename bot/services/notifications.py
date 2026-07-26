"""Proactive (push) notifications — strictly opt-in.

Nothing in this module ever messages a user who has not set the ``notifications``
setting to ``'on'``.  The default in :data:`bot.database.DEFAULT_SETTINGS` is
``'off'`` and this module treats a missing key as ``'off'`` too, so a partially
migrated database can never turn pushes on by accident.

Two jobs are provided:

* :func:`alerts_job` — pushes *real* service disruptions to users whose
  favourites or commuter lines are affected.  Alerts whose ``source`` marks them
  as fabricated fallbacks or as "the upstream source was unavailable" are never
  pushed: telling somebody their line is disrupted when we simply could not ask
  is worse than saying nothing.
* :func:`commute_reminder_job` — a "your usual trip leaves in ~10 min" ping
  around the times stored in the commuter profile.

Guard rails:

* Quiet hours (:data:`QUIET_HOURS_START` … :data:`QUIET_HOURS_END`) — no pushes
  in the middle of the night, ever.
* De-duplication — the same alert is pushed to the same user at most once per
  :data:`ALERT_DEDUP_TTL_H` hours; a commute reminder at most once per side of
  the commute per day.
* ``telegram.error.Forbidden`` (user blocked or deleted the bot) is swallowed
  per-user so one blocked user cannot kill the whole job.
* All times are Europe/Lisbon via :mod:`zoneinfo`, never server-local time.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

PORTO_TZ = ZoneInfo("Europe/Lisbon")

# --- Opt-in ---------------------------------------------------------------
NOTIFICATIONS_SETTING_KEY = "notifications"
NOTIFICATIONS_ON = "on"

# --- Quiet hours (local Porto time) --------------------------------------
QUIET_HOURS_START = 22   # 22:00 …
QUIET_HOURS_END = 7      # … 07:00 — no pushes in this window

# --- Anti-spam -----------------------------------------------------------
ALERT_DEDUP_TTL_H = 12
MAX_ALERTS_PER_PUSH = 3

# How far ahead of the stored usual time the reminder fires, and how wide the
# window the job accepts (the job is expected to run every few minutes).
COMMUTE_REMINDER_LEAD_MIN = 10
COMMUTE_REMINDER_WINDOW_MIN = 5

# Alert ``source`` values that must never be pushed: invented fallbacks and
# "we could not reach the upstream feed" placeholders.
NON_PUSHABLE_ALERT_SOURCES = frozenset({
    "", "fallback", "unavailable", "source_unavailable", "unknown", "none",
    "estimate", "estimated",
})

# bot_data keys used for de-duplication state.
_SENT_ALERTS_KEY = "notif_sent_alerts"
_SENT_REMINDERS_KEY = "notif_sent_reminders"


# ===================================================================
# Time helpers
# ===================================================================

def now_porto() -> datetime:
    """Current time in Europe/Lisbon (never the server's local zone)."""
    return datetime.now(PORTO_TZ)


def in_quiet_hours(moment: datetime | None = None) -> bool:
    """True when *moment* falls inside the do-not-disturb window."""
    moment = moment or now_porto()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=PORTO_TZ)
    else:
        moment = moment.astimezone(PORTO_TZ)
    hour = moment.hour
    if QUIET_HOURS_START > QUIET_HOURS_END:  # window crosses midnight
        return hour >= QUIET_HOURS_START or hour < QUIET_HOURS_END
    return QUIET_HOURS_START <= hour < QUIET_HOURS_END


def _parse_hhmm(value: str) -> tuple[int, int] | None:
    try:
        hour_s, minute_s = str(value).split(":", 1)
        hour, minute = int(hour_s), int(minute_s)
    except (AttributeError, TypeError, ValueError):
        return None
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return hour, minute
    return None


def is_reminder_due(usual_time: str, moment: datetime | None = None,
                    lead_min: int = COMMUTE_REMINDER_LEAD_MIN,
                    window_min: int = COMMUTE_REMINDER_WINDOW_MIN) -> bool:
    """True when *now* is roughly ``lead_min`` before *usual_time*."""
    parsed = _parse_hhmm(usual_time)
    if parsed is None:
        return False
    moment = (moment or now_porto()).astimezone(PORTO_TZ)
    target = moment.replace(hour=parsed[0], minute=parsed[1],
                            second=0, microsecond=0)
    fire_at = target - timedelta(minutes=lead_min)
    delta_min = (moment - fire_at).total_seconds() / 60
    return 0 <= delta_min < window_min


# ===================================================================
# Opt-in / user enumeration
# ===================================================================

async def user_has_notifications_on(user_id: int) -> bool:
    """Read the opt-in flag through database.py's public API.

    Degrades to *off* on any problem, including the settings key not existing
    yet: silence is always the safe failure mode for proactive messaging.
    """
    from bot import database

    try:
        settings = await database.get_user_settings(user_id)
    except Exception:
        logger.debug("Could not read settings for %s", user_id, exc_info=True)
        return False

    if not isinstance(settings, dict):
        return False
    value = settings.get(NOTIFICATIONS_SETTING_KEY)
    if value is None:
        # The key has not been added to DEFAULT_SETTINGS yet.
        return False
    return str(value).strip().lower() == NOTIFICATIONS_ON


async def get_opted_in_user_ids() -> list[int]:
    """Return the user IDs that have explicitly opted in to notifications.

    ``bot/database.py`` currently exposes no "list all users" call, so this
    tries the public helpers it *might* grow (in order of preference) and, as a
    last resort, reads the on-disk JSON settings directory that the no-DATABASE_URL
    fallback storage writes.  Anything it cannot determine yields an empty list —
    i.e. no pushes — rather than a guess.
    """
    from bot import database

    for name in ("get_users_with_notifications_on", "get_notification_user_ids"):
        getter = getattr(database, name, None)
        if getter is None:
            continue
        try:
            ids = await getter()
            return [int(i) for i in ids]
        except Exception:
            logger.debug("database.%s() failed", name, exc_info=True)

    candidates: list[int] = []
    lister = getattr(database, "get_all_user_ids", None)
    if lister is not None:
        try:
            candidates = [int(i) for i in await lister()]
        except Exception:
            logger.debug("database.get_all_user_ids() failed", exc_info=True)
            candidates = []

    if not candidates:
        candidates = _user_ids_from_settings_files()

    opted_in: list[int] = []
    for user_id in candidates:
        if await user_has_notifications_on(user_id):
            opted_in.append(user_id)
    return opted_in


def _user_ids_from_settings_files() -> list[int]:
    """Best-effort enumeration from the JSON settings fallback storage."""
    try:
        from bot.config import DATA_DIR
        settings_dir = DATA_DIR / "settings"
        if not settings_dir.exists():
            return []
        ids: list[int] = []
        for path in settings_dir.glob("*.json"):
            try:
                ids.append(int(path.stem))
            except ValueError:
                continue
        return ids
    except Exception:
        logger.debug("Could not enumerate settings files", exc_info=True)
        return []


# ===================================================================
# De-duplication
# ===================================================================

def _bot_data(context) -> dict:
    data = getattr(context, "bot_data", None)
    if isinstance(data, dict):
        return data
    return {}


def already_sent_alert(context, user_id: int, alert_id: str,
                       moment: datetime | None = None) -> bool:
    """True when *alert_id* was already pushed to *user_id* recently."""
    store = _bot_data(context).setdefault(_SENT_ALERTS_KEY, {})
    key = f"{user_id}:{alert_id}"
    sent_at = store.get(key)
    if sent_at is None:
        return False
    moment = moment or now_porto()
    try:
        return (moment - sent_at) < timedelta(hours=ALERT_DEDUP_TTL_H)
    except TypeError:
        return False


def mark_alert_sent(context, user_id: int, alert_id: str,
                    moment: datetime | None = None) -> None:
    store = _bot_data(context).setdefault(_SENT_ALERTS_KEY, {})
    store[f"{user_id}:{alert_id}"] = moment or now_porto()
    _prune_alert_store(store, moment or now_porto())


def _prune_alert_store(store: dict, moment: datetime) -> None:
    cutoff = timedelta(hours=ALERT_DEDUP_TTL_H * 2)
    stale = [k for k, v in store.items()
             if not isinstance(v, datetime) or (moment - v) > cutoff]
    for key in stale:
        store.pop(key, None)


def already_sent_reminder(context, user_id: int, kind: str,
                          moment: datetime | None = None) -> bool:
    """True when today's *kind* reminder already went out to *user_id*."""
    moment = moment or now_porto()
    store = _bot_data(context).setdefault(_SENT_REMINDERS_KEY, {})
    return store.get(f"{user_id}:{kind}") == moment.date().isoformat()


def mark_reminder_sent(context, user_id: int, kind: str,
                       moment: datetime | None = None) -> None:
    moment = moment or now_porto()
    store = _bot_data(context).setdefault(_SENT_REMINDERS_KEY, {})
    store[f"{user_id}:{kind}"] = moment.date().isoformat()


# ===================================================================
# Alert filtering
# ===================================================================

def is_pushable_alert(alert: dict) -> bool:
    """Whether an alert is real enough to interrupt somebody with.

    Rejects fabricated fallback entries and "we could not reach the source"
    placeholders, and anything without a usable identifier or title.
    """
    if not isinstance(alert, dict):
        return False
    if alert.get("error") or alert.get("unavailable"):
        return False
    source = str(alert.get("source", "")).strip().lower()
    if source in NON_PUSHABLE_ALERT_SOURCES:
        return False
    if not alert.get("id"):
        return False
    if not (alert.get("title") or alert.get("description")):
        return False
    # Only genuine disruptions warrant a push; general info does not.
    if alert.get("severity") == "low" and not alert.get("affected_lines"):
        return False
    return True


def _normalise(value) -> str:
    return str(value or "").strip().upper()


async def user_alert_matches(user_id: int, alert: dict) -> bool:
    """Whether *alert* affects one of the user's favourites or commuter lines."""
    lines = {_normalise(l) for l in alert.get("affected_lines", []) if l}
    stops = {_normalise(s) for s in alert.get("affected_stops", []) if s}
    if not lines and not stops:
        # Network-wide alerts are not targeted at anybody in particular; only
        # push those when they are high severity.
        return alert.get("severity") == "high"

    from bot import database

    try:
        favorites = await database.get_favorites(user_id)
    except Exception:
        logger.debug("Could not read favourites for %s", user_id, exc_info=True)
        favorites = []

    for fav in favorites or []:
        stop_id = _normalise(fav.get("stop_id"))
        name = _normalise(fav.get("name"))
        if stop_id and (stop_id in stops or stop_id in lines):
            return True
        if name and name in stops:
            return True

    try:
        profile = await database.get_commuter_profile(user_id)
    except Exception:
        profile = None

    if profile:
        for key in ("home_name", "work_name"):
            if _normalise(profile.get(key)) in stops:
                return True

    return False


# ===================================================================
# Sending
# ===================================================================

async def send_push(context, user_id: int, text: str) -> bool:
    """Send one push, tolerating users who blocked the bot.

    Returns True when Telegram accepted the message.
    """
    try:
        from telegram.error import Forbidden, TelegramError
    except Exception:  # pragma: no cover - telegram is a hard dependency
        Forbidden = TelegramError = Exception  # type: ignore

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=text,
            parse_mode="MarkdownV2",
            disable_notification=False,
        )
        return True
    except Forbidden:
        logger.info("User %s blocked the bot; skipping push", user_id)
        return False
    except TelegramError:
        logger.warning("Telegram rejected a push to %s", user_id, exc_info=True)
        return False
    except Exception:
        logger.exception("Unexpected failure pushing to %s", user_id)
        return False


def _user_lang(settings: dict | None) -> str:
    if isinstance(settings, dict):
        value = str(settings.get("language", "auto")).lower()
        if value in ("pt", "en"):
            return value
    return "pt"


async def _lang_for(user_id: int) -> str:
    from bot import database
    try:
        return _user_lang(await database.get_user_settings(user_id))
    except Exception:
        return "pt"


def format_alert_push(alert: dict, lang: str = "pt") -> str:
    """Render one alert as a MarkdownV2 push body."""
    from bot.utils.formatting import escape_md
    from bot.utils.i18n import t

    parts = [t("notif_alert_title", lang), ""]
    title = alert.get("title") or ""
    if title:
        parts.append(f"*{escape_md(title)}*")
    description = alert.get("description") or ""
    if description:
        parts.append(escape_md(description))
    affected = [str(l) for l in alert.get("affected_lines", []) if l]
    if affected:
        parts.append("🚏 " + escape_md(", ".join(affected)))
    return "\n".join(parts)


def format_commute_push(profile: dict, kind: str, lang: str = "pt") -> str:
    """Render the commute reminder body."""
    from bot.utils.formatting import escape_md
    from bot.utils.i18n import t
    from bot.handlers.routes import tf

    usual = (profile.get("usual_departure_time") if kind == "to_work"
             else profile.get("usual_return_time")) or ""
    origin = (profile.get("home_name") if kind == "to_work"
              else profile.get("work_name")) or "?"
    dest = (profile.get("work_name") if kind == "to_work"
            else profile.get("home_name")) or "?"

    parts = [
        t("notif_commute_reminder", lang),
        "",
        tf("notif_commute_body", lang).format(time=escape_md(usual)),
        t("trip_from_to", lang).format(origin=escape_md(origin), dest=escape_md(dest)),
    ]
    return "\n".join(parts)


# ===================================================================
# Jobs
# ===================================================================

async def alerts_job(context) -> None:
    """Push real service disruptions to affected, opted-in users."""
    moment = now_porto()
    if in_quiet_hours(moment):
        logger.debug("Skipping alert push job during quiet hours")
        return

    from bot.services import alerts as alerts_service

    try:
        all_alerts = await alerts_service.get_active_alerts()
    except Exception:
        logger.exception("Could not fetch alerts for the push job")
        return

    pushable = [a for a in (all_alerts or []) if is_pushable_alert(a)]
    if not pushable:
        logger.debug("No pushable alerts (fabricated/unavailable ones are skipped)")
        return

    user_ids = await get_opted_in_user_ids()
    if not user_ids:
        return

    for user_id in user_ids:
        lang = await _lang_for(user_id)
        sent = 0
        for alert in pushable:
            if sent >= MAX_ALERTS_PER_PUSH:
                break
            alert_id = str(alert.get("id"))
            if already_sent_alert(context, user_id, alert_id, moment):
                continue
            if not await user_alert_matches(user_id, alert):
                continue
            if await send_push(context, user_id, format_alert_push(alert, lang)):
                mark_alert_sent(context, user_id, alert_id, moment)
                sent += 1


async def commute_reminder_job(context) -> None:
    """Ping opted-in users shortly before their stored usual departure times."""
    moment = now_porto()
    if in_quiet_hours(moment):
        return
    # Commuting is a weekday thing; do not wake people up on the weekend.
    if moment.weekday() >= 5:
        return

    from bot import database

    user_ids = await get_opted_in_user_ids()
    if not user_ids:
        return

    for user_id in user_ids:
        try:
            profile = await database.get_commuter_profile(user_id)
        except Exception:
            logger.debug("Could not read commuter profile for %s", user_id,
                         exc_info=True)
            continue
        if not profile:
            continue

        for kind, key in (("to_work", "usual_departure_time"),
                          ("to_home", "usual_return_time")):
            if not is_reminder_due(profile.get(key, ""), moment):
                continue
            if already_sent_reminder(context, user_id, kind, moment):
                continue
            lang = await _lang_for(user_id)
            text = format_commute_push(profile, kind, lang)
            if await send_push(context, user_id, text):
                mark_reminder_sent(context, user_id, kind, moment)


# ===================================================================
# Registration
# ===================================================================

ALERTS_JOB_NAME = "notif_alerts"
COMMUTE_JOB_NAME = "notif_commute"

ALERTS_JOB_INTERVAL_S = 15 * 60          # every 15 minutes
COMMUTE_JOB_INTERVAL_S = COMMUTE_REMINDER_WINDOW_MIN * 60


def register_jobs(application) -> bool:
    """Register the notification jobs on the application's job queue.

    Returns False (and logs) when no job queue is available, which happens when
    python-telegram-bot was installed without the ``job-queue`` extra.
    """
    job_queue = getattr(application, "job_queue", None)
    if job_queue is None:
        logger.warning(
            "No JobQueue available - proactive notifications are disabled. "
            "Install python-telegram-bot[job-queue] to enable them."
        )
        return False

    job_queue.run_repeating(
        alerts_job,
        interval=ALERTS_JOB_INTERVAL_S,
        first=60,
        name=ALERTS_JOB_NAME,
    )
    job_queue.run_repeating(
        commute_reminder_job,
        interval=COMMUTE_JOB_INTERVAL_S,
        first=30,
        name=COMMUTE_JOB_NAME,
    )
    logger.info("Notification jobs registered (opt-in only, quiet hours %02d:00-%02d:00)",
                QUIET_HOURS_START, QUIET_HOURS_END)
    return True
