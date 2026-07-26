"""WhatsApp bot for Porto Transport using the Meta Cloud API.

Environment variables
---------------------
``WHATSAPP_TOKEN``
    Permanent access token from the Meta dashboard (outbound Graph API calls).
``WHATSAPP_PHONE_ID``
    Phone number id from the Meta dashboard.
``WHATSAPP_VERIFY_TOKEN``
    Shared secret echoed during the ``GET /webhook`` subscription handshake.
``WHATSAPP_APP_SECRET``  **(required in production - security critical)**
    The Meta *App Secret*.  Every ``POST /webhook`` body is authenticated with
    an HMAC-SHA256 over the **raw** request body, compared in constant time
    against Meta's ``X-Hub-Signature-256`` header.  Without it anybody who
    guesses the webhook URL can inject fake inbound messages and make the bot
    send WhatsApp messages to arbitrary phone numbers.  If this variable is
    unset the webhook **fails closed** (403 for every POST).
``WHATSAPP_ALLOW_UNSIGNED_WEBHOOKS``
    Local-development escape hatch (``true``/``1``/``yes``/``on``).  Only has an
    effect when ``WHATSAPP_APP_SECRET`` is empty, and makes the app accept
    unsigned POSTs so you can curl the webhook.  Loudly logged on every
    request.  **Never set this in production.**
``WHATSAPP_PORT``
    Port for the local development server (default 8080).

Running
-------
Production (never the Flask dev server - it is single-threaded and would make
Meta retry, producing duplicate replies)::

    gunicorn whatsapp.app:app --bind 0.0.0.0:8080 --workers 2 --timeout 30

Local development::

    python -m whatsapp.app

Webhook URL: ``https://your-domain/webhook``
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import sys
import threading
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request
import requests

# Add parent dir to path so we can import bot services
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

from bot.services import stcp
from bot.services.metro import get_next_departures, search_stations

from whatsapp import storage
from whatsapp.formatting import truncate
from whatsapp.strings import lang_from_phone, normalise_lang, wt
from whatsapp.worker import BackgroundWorker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "")
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "porto-transport-bot")
GRAPH_API_URL = f"https://graph.facebook.com/v21.0/{WHATSAPP_PHONE_ID}/messages"

ENV_APP_SECRET = "WHATSAPP_APP_SECRET"
ENV_ALLOW_UNSIGNED = "WHATSAPP_ALLOW_UNSIGNED_WEBHOOKS"

#: Processes inbound messages off the request path (see whatsapp/worker.py).
worker = BackgroundWorker()

# --- WhatsApp Cloud API payload limits ------------------------------------
MAX_TEXT_LEN = 4096
MAX_BODY_LEN = 1024
MAX_BUTTON_TITLE_LEN = 20
MAX_BUTTONS = 3
MAX_ROW_TITLE_LEN = 24
MAX_ROW_DESC_LEN = 72
MAX_ROWS = 10


# ===========================================================================
# Action ids
#
# Every id the app puts on a button or list row is declared here, and every id
# is wired into _EXACT_HANDLERS / _PREFIX_HANDLERS at the bottom of the module.
# tests/test_whatsapp.py drives the app through every screen, collects the ids
# it actually sends and asserts that all of them are handled - which is how the
# previously dead "Ajuda" (help) button is now prevented from coming back.
# ===========================================================================

ACTION_MENU = "menu"
ACTION_HELP = "help"
ACTION_BUS_SEARCH = "bus_search"
ACTION_METRO_SEARCH = "metro_search"
ACTION_FAVORITES = "favorites"
ACTION_TRIP = "trip"
ACTION_LANGUAGE = "language"
ACTION_LANG_PT = "lang_pt"
ACTION_LANG_EN = "lang_en"

PREFIX_STOP = "stop_"
PREFIX_STATION = "station_"
PREFIX_FAV_ADD_STOP = "fav_add_stop_"
PREFIX_FAV_ADD_STATION = "fav_add_station_"
PREFIX_FAV_DEL_STOP = "fav_del_stop_"
PREFIX_FAV_DEL_STATION = "fav_del_station_"

# Favorite type vocabulary shared with the Telegram bot
# (bot/handlers/favorites.py: FAV_TYPES = ("bus", "metro", "metrobus", "train")),
# so both channels write compatible rows into the same store.
FAV_TYPE_STOP = "bus"
FAV_TYPE_STATION = "metro"

# Free-text synonyms per intent (accent-free variants included).
_MENU_WORDS = {"ola", "olá", "oi", "hi", "hello", "menu", "inicio", "início", "start"}
_HELP_WORDS = {"ajuda", "help", "?"}
_FAV_WORDS = {"favoritos", "favorites", "favs", "fav", "estrela"}
_TRIP_WORDS = {"viagem", "trajeto", "trip", "route", "rota", "planear"}
_LANG_WORDS = {"idioma", "language", "lang", "lingua", "língua"}
_CANCEL_WORDS = {"cancelar", "cancel", "sair", "stop"}

_MODE_EMOJI = {
    "walk": "🚶", "metro": "🚇", "bus": "🚌", "train": "🚆", "metrobus": "🚍",
}


# ===========================================================================
# Webhook signature validation (security critical)
# ===========================================================================

def _app_secret() -> str:
    """Meta app secret, read per request so tests/rotations take effect."""
    return os.getenv(ENV_APP_SECRET, "").strip()


def _unsigned_allowed() -> bool:
    """True when the local-dev escape hatch is explicitly enabled."""
    return os.getenv(ENV_ALLOW_UNSIGNED, "").strip().lower() in {"1", "true", "yes", "on"}


def signature_mode() -> str:
    """Return the active webhook auth mode: enforced / dev-unsigned / fail-closed."""
    if _app_secret():
        return "enforced"
    return "dev-unsigned" if _unsigned_allowed() else "fail-closed"


def sign_payload(raw_body: bytes, secret: str) -> str:
    """Build the ``X-Hub-Signature-256`` header value for *raw_body*.

    Mirrors what Meta does; used by the test suite and for manual curl testing.
    """
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _verify_signature(raw_body: bytes, header: str | None) -> bool:
    """Verify Meta's HMAC-SHA256 signature over the RAW request body.

    Fails closed: with no app secret configured the only way through is the
    explicit ``WHATSAPP_ALLOW_UNSIGNED_WEBHOOKS`` development flag.
    """
    secret = _app_secret()
    if not secret:
        if _unsigned_allowed():
            logger.warning(
                "%s is not set and %s is enabled: accepting an UNSIGNED webhook. "
                "This is for local development only - never run it in production.",
                ENV_APP_SECRET, ENV_ALLOW_UNSIGNED,
            )
            return True
        logger.error(
            "%s is not set: rejecting webhook (fail closed). Set %s to the Meta "
            "app secret, or %s=true for local development only.",
            ENV_APP_SECRET, ENV_APP_SECRET, ENV_ALLOW_UNSIGNED,
        )
        return False

    if not header:
        return False
    algorithm, _, provided = header.partition("=")
    if algorithm.strip().lower() != "sha256" or not provided.strip():
        return False
    try:
        provided_digest = bytes.fromhex(provided.strip())
    except ValueError:
        return False

    expected_digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    return hmac.compare_digest(provided_digest, expected_digest)


# ===========================================================================
# Inbound de-duplication (idempotency)
#
# Meta retries a delivery it considers unacknowledged, and redeliveries carry
# the SAME message id. Without this, a retry sends the user a second reply.
# ===========================================================================

_MAX_SEEN_IDS = 5000
_seen_message_ids: "OrderedDict[str, float]" = OrderedDict()
_seen_lock = threading.Lock()


def _already_processed(message_id: str) -> bool:
    """Record *message_id* and report whether it had been seen before."""
    if not message_id:
        return False
    with _seen_lock:
        if message_id in _seen_message_ids:
            return True
        _seen_message_ids[message_id] = datetime.now().timestamp()
        while len(_seen_message_ids) > _MAX_SEEN_IDS:
            _seen_message_ids.popitem(last=False)
        return False


def reset_state() -> None:
    """Clear de-duplication and session state (used by tests)."""
    with _seen_lock:
        _seen_message_ids.clear()
    with _sessions_lock:
        _sessions.clear()


# ===========================================================================
# Session state
# ===========================================================================

_MAX_SESSIONS = 2000
_sessions: "OrderedDict[str, dict]" = OrderedDict()
_sessions_lock = threading.Lock()


def _session(sender: str) -> dict:
    """Return (creating if needed) the LRU session dict for *sender*."""
    with _sessions_lock:
        session = _sessions.get(sender)
        if session is None:
            session = {"names": {}}
            _sessions[sender] = session
        _sessions.move_to_end(sender)
        while len(_sessions) > _MAX_SESSIONS:
            _sessions.popitem(last=False)
        return session


def _set_state(sender: str, state: str, **extra) -> None:
    """Arm a one-shot conversation state for the next inbound text."""
    session = _session(sender)
    session["state"] = state
    session.update(extra)


def _take_state(sender: str) -> str | None:
    """Consume the pending conversation state, if any."""
    return _session(sender).pop("state", None)


def _remember_name(sender: str, kind: str, key: str, name: str) -> None:
    """Cache a stop/station display name so favoriting it needs no extra call."""
    names = _session(sender).setdefault("names", {})
    names[f"{kind}:{key}"] = name
    while len(names) > 50:
        names.pop(next(iter(names)))


def _recall_name(sender: str, kind: str, key: str) -> str:
    """Return the cached display name, falling back to the raw key."""
    return _session(sender).get("names", {}).get(f"{kind}:{key}", key)


def _mask(phone: str) -> str:
    """Mask a phone number for logging - never log the full number."""
    digits = "".join(c for c in (phone or "") if c.isdigit())
    if len(digits) <= 4:
        return "***"
    return f"***{digits[-3:]}"


# ===========================================================================
# HTTP endpoints
# ===========================================================================

@app.route("/webhook", methods=["GET"])
def verify_webhook():
    """Handle webhook verification from Meta."""
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token") or ""
    challenge = request.args.get("hub.challenge", "")

    expected = WHATSAPP_VERIFY_TOKEN or ""
    if mode == "subscribe" and expected and hmac.compare_digest(token, expected):
        logger.info("Webhook verified")
        return challenge, 200
    return "Forbidden", 403


@app.route("/webhook", methods=["POST"])
def handle_webhook():
    """Authenticate, de-duplicate and acknowledge an inbound webhook.

    The handler never does I/O: it verifies the signature over the raw body,
    filters out redeliveries by message id, hands each new message to the
    background worker and returns 200 straight away.  Anything slower makes
    Meta retry and users receive duplicate replies.
    """
    raw_body = request.get_data()

    if not _verify_signature(raw_body, request.headers.get("X-Hub-Signature-256")):
        logger.warning("Rejected webhook POST: missing or invalid signature")
        return "Forbidden", 403

    try:
        data = json.loads(raw_body) if raw_body else None
    except ValueError:
        logger.warning("Webhook body was not valid JSON")
        return "OK", 200

    if not isinstance(data, dict):
        return "OK", 200

    try:
        for msg, payload_lang in _extract_messages(data):
            worker.submit(_process_message, msg, payload_lang)
    except Exception:
        logger.exception("Error scheduling webhook payload")

    return "OK", 200


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "ok",
        "service": "porto-transport-whatsapp",
        "webhook_signature": signature_mode(),
    })


def _extract_messages(data: dict) -> list[tuple[dict, str | None]]:
    """Pull new (non-duplicate) messages out of a webhook payload.

    Returns ``[(message, payload_language_or_None), ...]``.  Status callbacks
    (``value["statuses"]``) and redeliveries are dropped here.
    """
    jobs: list[tuple[dict, str | None]] = []
    for entry in data.get("entry") or []:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes") or []:
            if not isinstance(change, dict):
                continue
            value = change.get("value") or {}
            if not isinstance(value, dict):
                continue
            payload_lang = _payload_language(value)
            for msg in value.get("messages") or []:
                if not isinstance(msg, dict):
                    continue
                message_id = str(msg.get("id") or "")
                if _already_processed(message_id):
                    logger.info(
                        "Ignoring duplicate delivery of message %s from %s",
                        message_id, _mask(msg.get("from", "")),
                    )
                    continue
                jobs.append((msg, payload_lang))
    return jobs


def _payload_language(value: dict) -> str | None:
    """Best-effort locale extraction from the inbound payload.

    Meta's ``messages`` webhook does not currently include a locale, so this
    stays defensive: if a ``locale``/``language`` field ever shows up on the
    contact profile or the metadata, it is used; otherwise the caller falls
    back to the stored preference and then the phone's country code.
    """
    for contact in value.get("contacts") or []:
        if not isinstance(contact, dict):
            continue
        profile = contact.get("profile") or {}
        for key in ("locale", "language"):
            candidate = contact.get(key) or (
                profile.get(key) if isinstance(profile, dict) else None
            )
            if candidate:
                return str(candidate)
    metadata = value.get("metadata") or {}
    if isinstance(metadata, dict) and metadata.get("locale"):
        return str(metadata["locale"])
    return None


# ===========================================================================
# Message processing (runs on the worker loop, never in the request thread)
# ===========================================================================

async def _process_message(msg: dict, payload_lang: str | None = None) -> None:
    """Process a single incoming message."""
    sender = msg.get("from") or ""
    if not sender:
        return

    lang = await _resolve_lang(sender, payload_lang)
    msg_type = msg.get("type", "")

    if msg_type == "text":
        text = ((msg.get("text") or {}).get("body") or "").strip()
        await _handle_text_message(sender, text, lang)
        return

    if msg_type == "interactive":
        interactive = msg.get("interactive") or {}
        kind = interactive.get("type")
        if kind == "button_reply":
            action_id = ((interactive.get("button_reply") or {}).get("id") or "")
        elif kind == "list_reply":
            action_id = ((interactive.get("list_reply") or {}).get("id") or "")
        else:
            logger.info("Unsupported interactive reply type %r", kind)
            return
        await _handle_action(sender, action_id, lang)
        return

    if msg_type == "button":
        # Quick-reply button on a template message.
        await _handle_action(sender, (msg.get("button") or {}).get("payload") or "", lang)
        return

    if msg_type == "location":
        location = msg.get("location") or {}
        lat = location.get("latitude")
        lon = location.get("longitude")
        # `is not None`, not truthiness: latitude/longitude 0.0 are valid
        # coordinates and must not be silently dropped.
        if lat is not None and lon is not None:
            try:
                await _handle_location(sender, float(lat), float(lon), lang)
            except (TypeError, ValueError):
                logger.warning("Ignoring location with non-numeric coordinates")
        return

    logger.info("Unsupported message type %r from %s", msg_type, _mask(sender))


async def _resolve_lang(sender: str, payload_lang: str | None = None) -> str:
    """Resolve the user's language: session > stored > payload locale > phone."""
    session = _session(sender)
    cached = session.get("lang")
    if cached:
        return cached

    stored = await storage.get_language(sender)
    if stored:
        lang = normalise_lang(stored)
    elif payload_lang:
        lang = normalise_lang(payload_lang)
    else:
        lang = lang_from_phone(sender)

    session["lang"] = lang
    return lang


async def _set_lang(sender: str, lang: str) -> None:
    """Change and persist the user's language, then confirm in that language."""
    lang = normalise_lang(lang)
    _session(sender)["lang"] = lang
    await storage.set_language(sender, lang)
    _send_text(sender, wt("wa_lang_set", lang))
    await _send_main_menu(sender, lang)


# ===========================================================================
# Text routing
# ===========================================================================

async def _handle_text_message(sender: str, text: str, lang: str) -> None:
    """Handle a text message from WhatsApp."""
    if not text:
        await _send_main_menu(sender, lang)
        return

    text_lower = text.lower()
    state = _take_state(sender)

    # Global commands always win, even mid-flow, so a user can never get stuck.
    if text_lower in _MENU_WORDS:
        await _send_main_menu(sender, lang)
        return
    if text_lower in _HELP_WORDS:
        _send_help(sender, lang)
        return
    if text_lower in _FAV_WORDS:
        await _send_favorites(sender, lang)
        return
    if text_lower in _TRIP_WORDS:
        _prompt_trip_origin(sender, lang)
        return
    if text_lower in _CANCEL_WORDS:
        _send_text(sender, wt("wa_cancelled", lang))
        await _send_main_menu(sender, lang)
        return
    if text_lower in _LANG_WORDS:
        _send_language_picker(sender, lang)
        return

    requested_lang = _parse_language_command(text_lower)
    if requested_lang:
        await _set_lang(sender, requested_lang)
        return

    # Conversation states armed by the menu buttons.
    if state == "await_bus":
        await _search_bus(sender, text, lang)
        return
    if state == "await_metro":
        await _search_metro(sender, text, lang)
        return
    if state == "await_trip_origin":
        await _handle_trip_origin(sender, text, lang)
        return
    if state == "await_trip_dest":
        origin = _session(sender).get("trip_origin", "")
        await _handle_trip_dest(sender, origin, text, lang)
        return

    await _search_anything(sender, text, lang)


def _parse_language_command(text_lower: str) -> str | None:
    """Recognise ``idioma en`` / ``lang pt`` / ``language english``."""
    parts = text_lower.split()
    if len(parts) != 2 or parts[0] not in _LANG_WORDS:
        return None
    value = parts[1]
    if value in {"pt", "português", "portugues", "portuguese"}:
        return "pt"
    if value in {"en", "english", "inglês", "ingles"}:
        return "en"
    return None


async def _search_bus(sender: str, text: str, lang: str) -> None:
    """Bus-only search (armed by the 'Autocarros' menu entry)."""
    if await _try_stop_code(sender, text, lang):
        return
    stops = await stcp.search_stops(text)
    if stops:
        _send_stop_list(sender, text, stops[:MAX_ROWS], lang)
        return
    _send_buttons(sender, wt("no_stops_found", lang, query=text),
                  [(ACTION_BUS_SEARCH, wt("kb_search_stop", lang)),
                   (ACTION_MENU, wt("kb_back_menu", lang))])


async def _search_metro(sender: str, text: str, lang: str) -> None:
    """Metro-only search (armed by the 'Metro' menu entry)."""
    stations = search_stations(text)
    if len(stations) == 1:
        await _send_metro_departures(sender, stations[0], lang)
        return
    if stations:
        _send_station_list(sender, text, stations[:MAX_ROWS], lang)
        return
    _send_buttons(sender, wt("no_stations_found", lang, query=text),
                  [(ACTION_METRO_SEARCH, wt("kb_search_station", lang)),
                   (ACTION_MENU, wt("kb_back_menu", lang))])


async def _try_stop_code(sender: str, text: str, lang: str) -> bool:
    """Treat *text* as an STCP stop code if it looks like one."""
    if len(text) > 6 or not any(c.isdigit() for c in text):
        return False
    stop_id = text.upper()
    data = await stcp.get_stop_real_time(stop_id)
    if data["arrivals"] or data["stop_name"] != stop_id:
        await _send_bus_arrivals(sender, stop_id, data, lang)
        return True
    return False


async def _search_anything(sender: str, text: str, lang: str) -> None:
    """Free-text search: stop code, then metro station, then bus stop."""
    if await _try_stop_code(sender, text, lang):
        return

    stations = search_stations(text)
    if stations:
        if len(stations) == 1:
            await _send_metro_departures(sender, stations[0], lang)
        else:
            _send_station_list(sender, text, stations[:MAX_ROWS], lang)
        return

    stops = await stcp.search_stops(text)
    if stops:
        _send_stop_list(sender, text, stops[:MAX_ROWS], lang)
        return

    _send_buttons(sender, wt("no_results", lang, query=text), [
        (ACTION_BUS_SEARCH, wt("kb_buses", lang)),
        (ACTION_METRO_SEARCH, wt("kb_metro", lang)),
        (ACTION_HELP, wt("kb_help", lang)),
    ])


# ===========================================================================
# Action (button / list reply) routing
# ===========================================================================

async def _handle_action(sender: str, action_id: str, lang: str) -> None:
    """Dispatch a button or list-row id to its handler."""
    if not action_id:
        return

    handler = _EXACT_HANDLERS.get(action_id)
    if handler is not None:
        await handler(sender, lang)
        return

    for prefix, prefix_handler in _PREFIX_HANDLERS:
        if action_id.startswith(prefix) and len(action_id) > len(prefix):
            await prefix_handler(sender, action_id[len(prefix):], lang)
            return

    # Should be impossible: tests assert every id the app sends is handled.
    logger.warning("Unhandled WhatsApp action id %r", action_id)


def handled_action_ids() -> set[str]:
    """Exact action ids the app accepts (used by the button-id audit test)."""
    return set(_EXACT_HANDLERS)


def handled_action_prefixes() -> set[str]:
    """Action id prefixes the app accepts (used by the button-id audit test)."""
    return {prefix for prefix, _ in _PREFIX_HANDLERS}


def handles_action_id(action_id: str) -> bool:
    """True if *action_id* would reach a handler."""
    if action_id in _EXACT_HANDLERS:
        return True
    return any(
        action_id.startswith(prefix) and len(action_id) > len(prefix)
        for prefix, _ in _PREFIX_HANDLERS
    )


# --- individual actions ----------------------------------------------------

async def _action_menu(sender: str, lang: str) -> None:
    await _send_main_menu(sender, lang)


async def _action_help(sender: str, lang: str) -> None:
    _send_help(sender, lang)


async def _action_bus_search(sender: str, lang: str) -> None:
    _set_state(sender, "await_bus")
    _send_text(sender, wt("wa_prompt_bus", lang))


async def _action_metro_search(sender: str, lang: str) -> None:
    _set_state(sender, "await_metro")
    _send_text(sender, wt("wa_prompt_metro", lang))


async def _action_favorites(sender: str, lang: str) -> None:
    await _send_favorites(sender, lang)


async def _action_trip(sender: str, lang: str) -> None:
    _prompt_trip_origin(sender, lang)


async def _action_language(sender: str, lang: str) -> None:
    _send_language_picker(sender, lang)


async def _action_lang_pt(sender: str, lang: str) -> None:
    await _set_lang(sender, "pt")


async def _action_lang_en(sender: str, lang: str) -> None:
    await _set_lang(sender, "en")


async def _action_open_stop(sender: str, stop_id: str, lang: str) -> None:
    data = await stcp.get_stop_real_time(stop_id)
    await _send_bus_arrivals(sender, stop_id, data, lang)


async def _action_open_station(sender: str, station_name: str, lang: str) -> None:
    stations = search_stations(station_name)
    if stations:
        await _send_metro_departures(sender, stations[0], lang)
        return
    _send_buttons(sender, wt("station_not_found", lang, name=station_name),
                  [(ACTION_METRO_SEARCH, wt("kb_search_station", lang)),
                   (ACTION_MENU, wt("kb_back_menu", lang))])


async def _action_fav_add_stop(sender: str, stop_id: str, lang: str) -> None:
    name = _recall_name(sender, FAV_TYPE_STOP, stop_id)
    added = await storage.add_favorite(sender, FAV_TYPE_STOP, stop_id, name)
    _send_text(sender, wt("fav_added", lang, name=name) if added
               else wt("fav_already", lang))


async def _action_fav_add_station(sender: str, station: str, lang: str) -> None:
    added = await storage.add_favorite(sender, FAV_TYPE_STATION, station, station)
    _send_text(sender, wt("fav_added", lang, name=station) if added
               else wt("fav_already", lang))


async def _action_fav_del_stop(sender: str, stop_id: str, lang: str) -> None:
    removed = await storage.remove_favorite(sender, FAV_TYPE_STOP, stop_id)
    _send_text(sender, wt("fav_removed", lang) if removed
               else wt("fav_remove_error", lang))


async def _action_fav_del_station(sender: str, station: str, lang: str) -> None:
    removed = await storage.remove_favorite(sender, FAV_TYPE_STATION, station)
    _send_text(sender, wt("fav_removed", lang) if removed
               else wt("fav_remove_error", lang))


# ===========================================================================
# Location
# ===========================================================================

async def _handle_location(sender: str, lat: float, lon: float, lang: str) -> None:
    """Handle location message - find nearby stops and stations."""
    from bot.services.metro import get_nearby_stations

    radius_stations_km = 0.75
    radius_stops_km = 0.4
    nearby_stations = get_nearby_stations(lat, lon, radius_km=radius_stations_km)
    nearby_stops = await stcp.search_nearby_stops(lat, lon, radius_km=radius_stops_km)

    if not nearby_stations and not nearby_stops:
        _send_buttons(
            sender,
            wt("nearby_empty", lang, radius=int(radius_stations_km * 1000)),
            [(ACTION_MENU, wt("kb_back_menu", lang))],
        )
        return

    lines = [wt("nearby_title", lang, radius=int(radius_stations_km * 1000)), ""]

    if nearby_stations:
        lines.append(wt("wa_nearby_metro", lang))
        for station in nearby_stations[:3]:
            emojis = " ".join(l["emoji"] for l in station.get("lines", []))
            lines.append(f"  • {station['name']} ({station['distance_m']}m) {emojis}".rstrip())
        lines.append("")

    if nearby_stops:
        lines.append(wt("wa_nearby_bus", lang))
        for stop in nearby_stops[:3]:
            lines.append(f"  • {stop['name']} ({stop['distance_m']}m)")
        lines.append("")

    _send_text(sender, "\n".join(lines).rstrip())


# ===========================================================================
# Trip planning
# ===========================================================================

def _prompt_trip_origin(sender: str, lang: str) -> None:
    _set_state(sender, "await_trip_origin")
    _send_text(sender, wt("wa_trip_prompt_origin", lang))


async def _handle_trip_origin(sender: str, text: str, lang: str) -> None:
    """Resolve the trip origin and ask for the destination."""
    try:
        from bot.services.trip_planner import resolve_location
    except Exception:
        logger.exception("Trip planner unavailable")
        _send_text(sender, wt("error_generic", lang))
        return

    node = resolve_location(text)
    if not node:
        _set_state(sender, "await_trip_origin")
        _send_text(sender, wt("trip_not_found", lang, query=text))
        return

    _set_state(sender, "await_trip_dest", trip_origin=node["name"])
    emoji = _MODE_EMOJI.get(node.get("type", ""), "📍")
    _send_text(sender, "\n\n".join([
        wt("trip_origin_set", lang, emoji=emoji, name=node["name"]),
        wt("wa_trip_prompt_dest", lang),
    ]))


async def _handle_trip_dest(sender: str, origin: str, text: str, lang: str) -> None:
    """Plan the trip once both ends are known."""
    if not origin:
        _prompt_trip_origin(sender, lang)
        return

    try:
        from bot.services.trip_planner import plan_trip
        options = plan_trip(origin, text)
    except Exception:
        logger.exception("Trip planning failed")
        _send_text(sender, wt("error_generic", lang))
        return

    if not options:
        _send_buttons(sender, wt("trip_no_routes", lang),
                      [(ACTION_TRIP, wt("trip_new", lang)),
                       (ACTION_MENU, wt("kb_back_menu", lang))])
        return

    lines = [wt("trip_results_title", lang),
             wt("trip_from_to", lang, origin=origin, dest=text), ""]
    for n, option in enumerate(options[:3], start=1):
        lines.append(_format_trip_option(option, n, lang))
        lines.append("")

    _send_buttons(sender, "\n".join(lines).rstrip(),
                  [(ACTION_TRIP, wt("trip_new", lang)),
                   (ACTION_MENU, wt("kb_back_menu", lang))])


def _format_trip_option(option, n: int, lang: str) -> str:
    """Render one TripOption using the shared i18n strings."""
    header = wt("trip_option_header", lang, n=n, time=option.total_time_min)
    if option.transfers:
        header += wt("trip_option_transfers", lang, transfers=option.transfers)
    lines = [header]

    for step in option.steps:
        if step.mode == "walk":
            if step.to_name:
                lines.append(wt("trip_step_walk", lang,
                                min=step.duration_min, to=step.to_name))
            else:
                lines.append(wt("trip_step_walk_from", lang,
                                min=step.duration_min, from_name=step.from_name))
            continue
        key = f"trip_step_{step.mode}"
        lines.append(wt(key, lang, line=step.line or "?", min=step.duration_min,
                        **{"from": step.from_name, "to": step.to_name}))

    if option.zones:
        lines.append(wt("trip_zones", lang, zones=", ".join(option.zones)))
    return "\n".join(lines)


# ===========================================================================
# Screens
# ===========================================================================

async def _send_main_menu(sender: str, lang: str) -> None:
    """Send the main menu.

    A list (not three reply buttons) because WhatsApp caps reply buttons at 3 -
    which is what pushed 'Ajuda' into a corner in the first place.
    """
    _take_state(sender)
    rows = [
        {"id": ACTION_BUS_SEARCH, "title": wt("kb_buses", lang)},
        {"id": ACTION_METRO_SEARCH, "title": wt("kb_metro", lang)},
        {"id": ACTION_FAVORITES, "title": wt("kb_favorites", lang)},
        {"id": ACTION_TRIP, "title": wt("kb_plan_route", lang)},
        {"id": ACTION_LANGUAGE, "title": wt("wa_kb_language", lang)},
        {"id": ACTION_HELP, "title": wt("kb_help", lang)},
    ]
    _send_list(sender, wt("wa_menu_body", lang), wt("wa_menu_button", lang),
               wt("wa_menu_section", lang), rows)


def _send_help(sender: str, lang: str) -> None:
    """Send the help text."""
    _send_buttons(sender, wt("wa_help", lang),
                  [(ACTION_MENU, wt("kb_back_menu", lang))])


def _send_language_picker(sender: str, lang: str) -> None:
    """Offer the supported languages."""
    _send_buttons(sender, wt("wa_lang_picker", lang), [
        (ACTION_LANG_PT, "🇵🇹 Português"),
        (ACTION_LANG_EN, "🇬🇧 English"),
        (ACTION_MENU, wt("kb_back_menu", lang)),
    ])


async def _send_favorites(sender: str, lang: str) -> None:
    """List the user's favorites as a tappable list."""
    favs = await storage.get_favorites(sender)

    rows = []
    for fav in favs:
        fav_type = fav.get("type")
        fav_id = str(fav.get("id") or "")
        name = str(fav.get("name") or fav_id)
        if not fav_id:
            continue
        if fav_type in (FAV_TYPE_STOP, "stop"):
            rows.append({"id": PREFIX_STOP + fav_id, "title": f"🚌 {name}",
                         "description": wt("wa_fav_desc_stop", lang, id=fav_id)})
            _remember_name(sender, FAV_TYPE_STOP, fav_id, name)
        elif fav_type in (FAV_TYPE_STATION, "station"):
            rows.append({"id": PREFIX_STATION + fav_id, "title": f"🚇 {name}",
                         "description": wt("wa_fav_desc_station", lang)})
        else:
            # e.g. a train/metrobus favorite saved from Telegram - the WhatsApp
            # bot has no screen for those yet, so it does not offer a dead row.
            logger.debug("Skipping favorite of unsupported type %r", fav_type)
        if len(rows) >= MAX_ROWS:
            break

    if not rows:
        _send_buttons(sender, wt("favs_empty_short", lang),
                      [(ACTION_BUS_SEARCH, wt("kb_buses", lang)),
                       (ACTION_METRO_SEARCH, wt("kb_metro", lang)),
                       (ACTION_MENU, wt("kb_back_menu", lang))])
        return

    _send_list(sender, wt("favs_count", lang, count=len(rows)),
               wt("wa_favs_list_button", lang), wt("wa_favs_section", lang), rows)


async def _send_bus_arrivals(sender: str, stop_id: str, data: dict, lang: str) -> None:
    """Send bus arrival information plus a favorite toggle."""
    stop_name = data.get("stop_name", stop_id)
    arrivals = data.get("arrivals", [])
    _remember_name(sender, FAV_TYPE_STOP, stop_id, stop_name)

    lines = [f"🚏 *{stop_name}* ({stop_id})", ""]

    if not arrivals:
        lines.append(wt("wa_bus_no_arrivals", lang))
    else:
        for arrival in arrivals[:8]:
            lines.append(f"🚌 *{arrival.get('line', '?')}* → {arrival.get('destination', '?')}")
            lines.append(f"     ⏱ {arrival.get('time', '?')}")
        lines.append("")
        lines.append(wt("wa_updated_at", lang, time=datetime.now().strftime("%H:%M")))

    _send_buttons(sender, "\n".join(lines),
                  [await _fav_button(sender, FAV_TYPE_STOP, stop_id, lang),
                   (ACTION_MENU, wt("kb_back_menu", lang))])


async def _send_metro_departures(sender: str, station: dict, lang: str) -> None:
    """Send metro departure information plus a favorite toggle."""
    name = station["name"]
    line_emojis = " ".join(l["emoji"] for l in station.get("lines", []))
    departures = get_next_departures(name, count=5)

    lines = [f"🚇 *{name}*"]
    if line_emojis:
        lines.append(line_emojis)
    lines.append("")

    if not departures:
        lines.append(wt("wa_metro_no_info", lang))
    elif departures[0].get("direction") == "Serviço encerrado":
        lines.append(wt("wa_metro_closed", lang))
        lines.append(wt("wa_metro_hours", lang,
                        hours=departures[0].get("time", "06:00 - 01:00")))
    else:
        for departure in departures:
            lines.append(f"*{departure.get('direction', '?')}* — {departure.get('time', '?')}")
        if any(d.get("estimated") for d in departures):
            lines.append("")
            lines.append(wt("metro_estimated_warning", lang))
        lines.append("")
        lines.append(wt("wa_updated_at", lang, time=datetime.now().strftime("%H:%M")))

    _send_buttons(sender, "\n".join(lines),
                  [await _fav_button(sender, FAV_TYPE_STATION, name, lang),
                   (ACTION_MENU, wt("kb_back_menu", lang))])


async def _fav_button(sender: str, fav_type: str, item_id: str, lang: str) -> tuple[str, str]:
    """Return the add-or-remove favorite button for this item."""
    saved = await storage.is_favorite(sender, fav_type, item_id)
    if fav_type == FAV_TYPE_STOP:
        prefix = PREFIX_FAV_DEL_STOP if saved else PREFIX_FAV_ADD_STOP
    else:
        prefix = PREFIX_FAV_DEL_STATION if saved else PREFIX_FAV_ADD_STATION
    label = wt("kb_unfavorite", lang) if saved else wt("kb_favorite", lang)
    return prefix + item_id, label


def _send_stop_list(sender: str, query: str, stops: list[dict], lang: str) -> None:
    """Send a list of bus stops as an interactive list."""
    rows = []
    for stop in stops[:MAX_ROWS]:
        stop_id = str(stop.get("code") or stop.get("stop_id") or "")
        if not stop_id:
            continue
        name = str(stop.get("name") or stop_id)
        _remember_name(sender, FAV_TYPE_STOP, stop_id, name)
        rows.append({
            "id": PREFIX_STOP + stop_id,
            "title": f"🚌 {name}",
            "description": wt("wa_stop_desc", lang, id=stop_id),
        })

    if not rows:
        _send_buttons(sender, wt("no_stops_found", lang, query=query),
                      [(ACTION_MENU, wt("kb_back_menu", lang))])
        return

    _send_list(sender, wt("results_for", lang, query=query),
               wt("wa_stop_list_button", lang), wt("wa_stop_section", lang), rows)


def _send_station_list(sender: str, query: str, stations: list[dict], lang: str) -> None:
    """Send a list of metro stations as an interactive list."""
    rows = []
    for station in stations[:MAX_ROWS]:
        name = station["name"]
        rows.append({
            "id": PREFIX_STATION + name,
            "title": f"🚇 {name}",
            "description": " ".join(l["emoji"] for l in station.get("lines", [])),
        })

    if not rows:
        _send_buttons(sender, wt("no_stations_found", lang, query=query),
                      [(ACTION_MENU, wt("kb_back_menu", lang))])
        return

    _send_list(sender, wt("metro_results_for", lang, query=query),
               wt("wa_station_list_button", lang), wt("wa_station_section", lang), rows)


# ===========================================================================
# Message sending helpers
# ===========================================================================

def _send_text(to: str, text: str) -> None:
    """Send a plain text message."""
    _api_call({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": truncate(text, MAX_TEXT_LEN), "preview_url": False},
    })


def _send_buttons(to: str, body: str, buttons: list[tuple[str, str]]) -> None:
    """Send an interactive message with up to three reply buttons."""
    payload_buttons = [
        {"type": "reply", "reply": {
            "id": action_id,
            "title": truncate(title, MAX_BUTTON_TITLE_LEN),
        }}
        for action_id, title in buttons[:MAX_BUTTONS] if action_id
    ]
    if not payload_buttons:
        _send_text(to, body)
        return

    _api_call({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": truncate(body, MAX_BODY_LEN)},
            "action": {"buttons": payload_buttons},
        },
    })


def _send_list(to: str, body: str, button_label: str, section_title: str,
               rows: list[dict]) -> None:
    """Send an interactive list message (up to ten rows)."""
    payload_rows = []
    for row in rows[:MAX_ROWS]:
        entry = {
            "id": row["id"],
            "title": truncate(row.get("title", ""), MAX_ROW_TITLE_LEN),
        }
        description = row.get("description")
        if description:
            entry["description"] = truncate(description, MAX_ROW_DESC_LEN)
        payload_rows.append(entry)

    if not payload_rows:
        _send_text(to, body)
        return

    _api_call({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": truncate(body, MAX_BODY_LEN)},
            "action": {
                "button": truncate(button_label, MAX_BUTTON_TITLE_LEN),
                "sections": [{
                    "title": truncate(section_title, MAX_ROW_TITLE_LEN),
                    "rows": payload_rows,
                }],
            },
        },
    })


def _api_call(payload: dict) -> None:
    """Make a call to the WhatsApp Cloud API."""
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_ID:
        logger.warning("WhatsApp credentials not configured")
        return

    try:
        resp = requests.post(
            GRAPH_API_URL,
            json=payload,
            headers={
                "Authorization": f"Bearer {WHATSAPP_TOKEN}",
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        if resp.status_code != 200:
            logger.error("WhatsApp API error %d: %s", resp.status_code, resp.text)
    except Exception:
        logger.exception("Error calling WhatsApp API")


# ===========================================================================
# Action registry (see the "Action ids" section above)
# ===========================================================================

_EXACT_HANDLERS = {
    ACTION_MENU: _action_menu,
    ACTION_HELP: _action_help,
    ACTION_BUS_SEARCH: _action_bus_search,
    ACTION_METRO_SEARCH: _action_metro_search,
    ACTION_FAVORITES: _action_favorites,
    ACTION_TRIP: _action_trip,
    ACTION_LANGUAGE: _action_language,
    ACTION_LANG_PT: _action_lang_pt,
    ACTION_LANG_EN: _action_lang_en,
}

# Longest prefix first so that e.g. `fav_add_stop_` is never shadowed.
_PREFIX_HANDLERS = tuple(sorted(
    (
        (PREFIX_FAV_ADD_STOP, _action_fav_add_stop),
        (PREFIX_FAV_ADD_STATION, _action_fav_add_station),
        (PREFIX_FAV_DEL_STOP, _action_fav_del_stop),
        (PREFIX_FAV_DEL_STATION, _action_fav_del_station),
        (PREFIX_STOP, _action_open_stop),
        (PREFIX_STATION, _action_open_station),
    ),
    key=lambda item: len(item[0]),
    reverse=True,
))


if __name__ == "__main__":
    # Local development only. In production run gunicorn (see module docstring):
    # the dev server is single-threaded, and a blocked webhook makes Meta retry.
    port = int(os.getenv("WHATSAPP_PORT", "8080"))
    logger.info(
        "Starting WhatsApp bot on port %d (webhook signature mode: %s)",
        port, signature_mode(),
    )
    app.run(host="0.0.0.0", port=port)
