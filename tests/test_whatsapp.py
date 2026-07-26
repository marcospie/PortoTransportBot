"""Tests for the WhatsApp Cloud API bot (whatsapp/).

Covers the four things that had shipped broken:

* webhook signature validation (valid / invalid / missing secret),
* every button id the app sends having a handler (the dead "Ajuda" button),
* inbound message-id de-duplication (Meta retries -> duplicate replies),
* WhatsApp formatting (no MarkdownV2 backslashes leaking to users).

All network I/O is mocked - no test ever contacts Meta, STCP or Metro do
Porto, and no message is ever sent to a real phone number.
"""

import asyncio
import hashlib
import hmac
import importlib
import json
import threading

import pytest

from whatsapp import app as wa
from whatsapp import storage as wa_storage
from whatsapp.formatting import (
    from_markdown_v2,
    has_markdown_v2_escapes,
    truncate,
)
from whatsapp.strings import WA_STRINGS, lang_from_phone, normalise_lang, wt
from whatsapp.worker import BackgroundWorker, InlineWorker

APP_SECRET = "test-app-secret"
PHONE = "351912345678"


# ===========================================================================
# Test doubles
# ===========================================================================

class FakeStorage:
    """In-memory stand-in for whatsapp.storage (no DB, no filesystem)."""

    def __init__(self):
        self.favorites: dict[str, list[dict]] = {}
        self.languages: dict[str, str] = {}

    async def get_favorites(self, phone):
        return list(self.favorites.get(phone, []))

    async def add_favorite(self, phone, fav_type, item_id, name):
        favs = self.favorites.setdefault(phone, [])
        if any(f["type"] == fav_type and f["id"] == item_id for f in favs):
            return False
        favs.append({"type": fav_type, "id": item_id, "name": name})
        return True

    async def remove_favorite(self, phone, fav_type, item_id):
        favs = self.favorites.setdefault(phone, [])
        kept = [f for f in favs if not (f["type"] == fav_type and f["id"] == item_id)]
        if len(kept) == len(favs):
            return False
        self.favorites[phone] = kept
        return True

    async def is_favorite(self, phone, fav_type, item_id):
        return any(f["type"] == fav_type and f["id"] == item_id
                   for f in self.favorites.get(phone, []))

    async def get_language(self, phone):
        return self.languages.get(phone)

    async def set_language(self, phone, lang):
        self.languages[phone] = lang


class RecordingWorker:
    """Records submissions without running them (proves work is deferred)."""

    def __init__(self):
        self.calls = []

    def submit(self, fn, *args, **kwargs):
        self.calls.append((fn, args, kwargs))

    def shutdown(self, timeout=5.0):
        return None


STATIONS = {
    "trindade": [{"name": "Trindade", "lines": [{"emoji": "🔵"}, {"emoji": "🟡"}]}],
    "bol": [
        {"name": "Bolhão", "lines": [{"emoji": "🔵"}]},
        {"name": "Bolhão Norte", "lines": [{"emoji": "🟡"}]},
    ],
}

STOPS = {
    "bolhao": [
        {"code": "BCM1", "name": "Bolhão"},
        {"code": "BCM2", "name": "Bolhão (Loureiro)"},
    ],
}

ARRIVALS = {
    "BCM2": {
        "stop_name": "Bolhão (Loureiro)",
        "arrivals": [
            {"line": "200", "destination": "Castelo do Queijo", "time": "5 min"},
            {"line": "301", "destination": "Aliados", "time": "12 min"},
        ],
    },
}


def _fake_search_stations(query):
    return list(STATIONS.get((query or "").strip().lower(), []))


async def _fake_search_stops(query):
    return list(STOPS.get((query or "").strip().lower().replace("ã", "a"), []))


async def _fake_get_stop_real_time(stop_id):
    hit = ARRIVALS.get(stop_id)
    if hit is not None:
        return dict(hit)
    return {"stop_name": stop_id, "arrivals": []}


def _fake_get_next_departures(name, count=5, **kwargs):
    return [
        {"direction": "Senhor de Matosinhos", "time": "3 min", "estimated": True},
        {"direction": "Estádio do Dragão", "time": "7 min", "estimated": True},
    ]


async def _fake_search_nearby_stops(lat, lon, radius_km=0.4):
    return [{"name": "Praça da Liberdade", "distance_m": 120}]


def _fake_get_nearby_stations(lat, lon, radius_km=0.75):
    return [{"name": "Aliados", "distance_m": 210, "lines": [{"emoji": "🔵"}]}]


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def sent(monkeypatch):
    """Capture every outbound WhatsApp API payload instead of sending it."""
    payloads: list[dict] = []
    monkeypatch.setattr(wa, "_api_call", lambda payload: payloads.append(payload))
    return payloads


@pytest.fixture
def fake_storage(monkeypatch):
    store = FakeStorage()
    monkeypatch.setattr(wa, "storage", store)
    return store


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    """Reset dedup/session state and force the app into a known env."""
    wa.reset_state()
    monkeypatch.setenv("WHATSAPP_APP_SECRET", APP_SECRET)
    monkeypatch.delenv("WHATSAPP_ALLOW_UNSIGNED_WEBHOOKS", raising=False)
    yield
    wa.reset_state()


@pytest.fixture
def services(monkeypatch):
    """Mock every transport data source the app touches."""
    monkeypatch.setattr(wa, "search_stations", _fake_search_stations)
    monkeypatch.setattr(wa, "get_next_departures", _fake_get_next_departures)
    monkeypatch.setattr(wa.stcp, "search_stops", _fake_search_stops)
    monkeypatch.setattr(wa.stcp, "get_stop_real_time", _fake_get_stop_real_time)
    monkeypatch.setattr(wa.stcp, "search_nearby_stops", _fake_search_nearby_stops)
    from bot.services import metro as metro_service
    monkeypatch.setattr(metro_service, "get_nearby_stations", _fake_get_nearby_stations)


@pytest.fixture
def client(monkeypatch):
    """Flask test client with the worker running inline (deterministic)."""
    monkeypatch.setattr(wa, "worker", InlineWorker())
    wa.app.config["TESTING"] = True
    with wa.app.test_client() as test_client:
        yield test_client


# ===========================================================================
# Payload helpers
# ===========================================================================

_counter = {"n": 0}


def _next_id():
    _counter["n"] += 1
    return f"wamid.TEST{_counter['n']}"


def text_message(body, message_id=None, sender=PHONE):
    return {"id": message_id or _next_id(), "from": sender, "type": "text",
            "timestamp": "1700000000", "text": {"body": body}}


def button_message(action_id, message_id=None, sender=PHONE):
    return {"id": message_id or _next_id(), "from": sender, "type": "interactive",
            "timestamp": "1700000000",
            "interactive": {"type": "button_reply",
                            "button_reply": {"id": action_id, "title": "x"}}}


def list_message(action_id, message_id=None, sender=PHONE):
    return {"id": message_id or _next_id(), "from": sender, "type": "interactive",
            "timestamp": "1700000000",
            "interactive": {"type": "list_reply",
                            "list_reply": {"id": action_id, "title": "x"}}}


def location_message(lat, lon, message_id=None, sender=PHONE):
    return {"id": message_id or _next_id(), "from": sender, "type": "location",
            "timestamp": "1700000000",
            "location": {"latitude": lat, "longitude": lon}}


def webhook_payload(*messages, contacts=None):
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "0",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "metadata": {"display_phone_number": "1", "phone_number_id": "2"},
                    "contacts": contacts if contacts is not None else [],
                    "messages": list(messages),
                },
            }],
        }],
    }


def post(client, payload, *, secret=APP_SECRET, signature=None, raw=None):
    body = raw if raw is not None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if signature is None and secret is not None:
        signature = wa.sign_payload(body, secret)
    if signature:
        headers["X-Hub-Signature-256"] = signature
    return client.post("/webhook", data=body, headers=headers)


def texts(payloads):
    """All user-visible text out of captured payloads."""
    out = []
    for payload in payloads:
        if payload.get("type") == "text":
            out.append(payload["text"]["body"])
        elif payload.get("type") == "interactive":
            out.append(payload["interactive"]["body"]["text"])
    return out


def action_ids(payloads):
    """Every button/list-row id present in captured payloads."""
    ids = set()
    for payload in payloads:
        interactive = payload.get("interactive") or {}
        action = interactive.get("action") or {}
        for button in action.get("buttons") or []:
            ids.add(button["reply"]["id"])
        for section in action.get("sections") or []:
            for row in section.get("rows") or []:
                ids.add(row["id"])
    return ids


# ===========================================================================
# 1. Webhook signature validation (SECURITY)
# ===========================================================================

class TestWebhookSignature:

    def test_valid_signature_is_accepted_and_processed(self, client, sent, services,
                                                       fake_storage):
        resp = post(client, webhook_payload(text_message("menu")))
        assert resp.status_code == 200
        assert sent, "a valid signed webhook must be processed"

    def test_invalid_signature_is_rejected_with_403(self, client, sent, services,
                                                    fake_storage):
        resp = post(client, webhook_payload(text_message("menu")),
                    signature="sha256=" + "00" * 32)
        assert resp.status_code == 403
        assert sent == [], "an unauthenticated webhook must never trigger a reply"

    def test_signature_from_wrong_secret_is_rejected(self, client, sent, services,
                                                     fake_storage):
        resp = post(client, webhook_payload(text_message("menu")), secret="not-the-secret")
        assert resp.status_code == 403
        assert sent == []

    def test_missing_signature_header_is_rejected(self, client, sent, services,
                                                  fake_storage):
        resp = post(client, webhook_payload(text_message("menu")), secret=None)
        assert resp.status_code == 403
        assert sent == []

    @pytest.mark.parametrize("header", [
        "",
        "sha1=abcdef",
        "sha256=",
        "sha256=nothex!!",
        "sha256=abc",            # odd length
        "deadbeef",              # no algorithm prefix
        "sha256=" + "00" * 31,   # right shape, wrong length
    ])
    def test_malformed_signature_headers_are_rejected(self, client, sent, services,
                                                      fake_storage, header):
        resp = post(client, webhook_payload(text_message("menu")), signature=header)
        assert resp.status_code == 403
        assert sent == []

    def test_signature_is_verified_over_the_raw_body(self, client, sent, services,
                                                     fake_storage):
        """A re-serialised body would produce a different digest.

        The raw bytes carry non-canonical spacing and a non-ASCII escape, so this
        only passes if the app hashes request.get_data() rather than
        json.dumps(request.get_json()).
        """
        raw = ('{"entry":[ {"changes":[{"value":{"messages":'
               '[{"id":"wamid.RAW","from":"351912345678","type":"text",'
               '"text":{"body":"Bolh\\u00e3o"}}]}}]} ]}').encode("utf-8")
        assert json.dumps(json.loads(raw)).encode("utf-8") != raw
        resp = post(client, None, raw=raw)
        assert resp.status_code == 200
        assert sent, "raw-body HMAC must accept a non-canonically-encoded payload"

    def test_signature_comparison_is_constant_time(self):
        """_verify_signature must compare digests with hmac.compare_digest."""
        import inspect
        source = inspect.getsource(wa._verify_signature)
        assert "hmac.compare_digest" in source, "digest compare must be constant time"

    def test_signature_differing_by_one_byte_is_rejected(self):
        body = b'{"a":1}'
        good = wa.sign_payload(body, APP_SECRET)
        digest = good.split("=", 1)[1]
        flipped = ("0" if digest[-1] != "0" else "1")
        assert wa._verify_signature(body, good)
        assert not wa._verify_signature(body, f"sha256={digest[:-1]}{flipped}")

    def test_signature_of_a_different_body_is_rejected(self):
        header = wa.sign_payload(b'{"a":1}', APP_SECRET)
        assert not wa._verify_signature(b'{"a":2}', header)

    def test_fails_closed_when_app_secret_is_missing(self, client, sent, services,
                                                     fake_storage, monkeypatch):
        monkeypatch.delenv("WHATSAPP_APP_SECRET", raising=False)
        assert wa.signature_mode() == "fail-closed"
        resp = post(client, webhook_payload(text_message("menu")), secret="anything")
        assert resp.status_code == 403
        assert sent == []

    def test_dev_flag_allows_unsigned_only_without_a_secret(self, client, sent,
                                                            services, fake_storage,
                                                            monkeypatch):
        monkeypatch.delenv("WHATSAPP_APP_SECRET", raising=False)
        monkeypatch.setenv("WHATSAPP_ALLOW_UNSIGNED_WEBHOOKS", "true")
        assert wa.signature_mode() == "dev-unsigned"
        resp = post(client, webhook_payload(text_message("menu")), secret=None)
        assert resp.status_code == 200
        assert sent, "local development must still be possible"

    def test_dev_flag_is_ignored_once_a_secret_is_configured(self, client, sent,
                                                             services, fake_storage,
                                                             monkeypatch):
        monkeypatch.setenv("WHATSAPP_ALLOW_UNSIGNED_WEBHOOKS", "true")
        assert wa.signature_mode() == "enforced"
        resp = post(client, webhook_payload(text_message("menu")), secret=None)
        assert resp.status_code == 403
        assert sent == []

    def test_sign_payload_matches_metas_algorithm(self):
        body = b'{"hello":"world"}'
        expected = hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
        assert wa.sign_payload(body, APP_SECRET) == f"sha256={expected}"

    def test_invalid_json_with_valid_signature_is_acknowledged(self, client, sent):
        resp = post(client, None, raw=b"not json")
        assert resp.status_code == 200
        assert sent == []

    def test_health_reports_the_signature_mode(self, client):
        data = client.get("/health").get_json()
        assert data["status"] == "ok"
        assert data["webhook_signature"] == "enforced"


class TestVerificationHandshake:

    def test_correct_verify_token_returns_the_challenge(self, client):
        resp = client.get("/webhook", query_string={
            "hub.mode": "subscribe",
            "hub.verify_token": wa.WHATSAPP_VERIFY_TOKEN,
            "hub.challenge": "12345",
        })
        assert resp.status_code == 200
        assert resp.data == b"12345"

    def test_wrong_verify_token_is_forbidden(self, client):
        resp = client.get("/webhook", query_string={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong",
            "hub.challenge": "12345",
        })
        assert resp.status_code == 403

    def test_missing_mode_is_forbidden(self, client):
        resp = client.get("/webhook", query_string={
            "hub.verify_token": wa.WHATSAPP_VERIFY_TOKEN,
        })
        assert resp.status_code == 403

    def test_no_parameters_is_forbidden(self, client):
        assert client.get("/webhook").status_code == 403

    def test_non_ascii_verify_token_does_not_error(self, client):
        """compare_digest raises TypeError on non-ASCII str - must not 500."""
        resp = client.get("/webhook", query_string={
            "hub.mode": "subscribe",
            "hub.verify_token": "tökén-ünicode",
            "hub.challenge": "12345",
        })
        assert resp.status_code == 403


# ===========================================================================
# 2. Button id audit - every id sent must have a handler
# ===========================================================================

def _drive_every_screen(client, fake_storage):
    """Walk the app through every screen that can emit a button or list row."""
    # Menu, help, language picker, favorites (empty), trip prompt.
    post(client, webhook_payload(text_message("menu")))
    post(client, webhook_payload(button_message(wa.ACTION_HELP)))
    post(client, webhook_payload(button_message(wa.ACTION_LANGUAGE)))
    post(client, webhook_payload(button_message(wa.ACTION_FAVORITES)))

    # Search result lists.
    post(client, webhook_payload(text_message("Bolhão")))     # stop list
    post(client, webhook_payload(text_message("Bol")))        # station list

    # Detail screens with the "add favorite" button.
    post(client, webhook_payload(text_message("BCM2")))       # bus arrivals
    post(client, webhook_payload(text_message("Trindade")))    # metro departures

    # Same detail screens once the items are favorites -> "remove" button.
    fake_storage.favorites[PHONE] = [
        {"type": wa.FAV_TYPE_STOP, "id": "BCM2", "name": "Bolhão (Loureiro)"},
        {"type": wa.FAV_TYPE_STATION, "id": "Trindade", "name": "Trindade"},
    ]
    post(client, webhook_payload(text_message("BCM2")))
    post(client, webhook_payload(text_message("Trindade")))
    post(client, webhook_payload(button_message(wa.ACTION_FAVORITES)))  # populated

    # Not-found screens.
    post(client, webhook_payload(text_message("qwertyuiop")))           # no results
    post(client, webhook_payload(button_message(wa.ACTION_BUS_SEARCH)))
    post(client, webhook_payload(text_message("qwertyuiop")))           # no stops
    post(client, webhook_payload(button_message(wa.ACTION_METRO_SEARCH)))
    post(client, webhook_payload(text_message("qwertyuiop")))           # no stations
    post(client, webhook_payload(list_message(wa.PREFIX_STATION + "Nowhere")))


class TestButtonIdAudit:

    def test_every_sent_action_id_has_a_handler(self, client, sent, services,
                                                fake_storage):
        _drive_every_screen(client, fake_storage)
        ids = action_ids(sent)
        assert ids, "the audit must actually collect ids"
        unhandled = sorted(i for i in ids if not wa.handles_action_id(i))
        assert unhandled == [], f"these button ids are dead: {unhandled}"

    def test_help_button_is_not_dead(self, client, sent, services, fake_storage):
        """Regression test: tapping 'Ajuda' used to do nothing at all."""
        assert "help" in wa.handled_action_ids()
        post(client, webhook_payload(button_message("help")))
        body = "\n".join(texts(sent))
        assert body, "the help button must produce a reply"
        assert "Porto Transport Bot" in body
        assert "Nome de paragem" in body

    def test_help_button_id_is_offered_by_the_main_menu(self, client, sent, services,
                                                        fake_storage):
        post(client, webhook_payload(text_message("menu")))
        assert wa.ACTION_HELP in action_ids(sent)

    def test_no_handler_is_orphaned(self, client, sent, services, fake_storage):
        """Every exact id the dispatcher accepts must be reachable from a screen."""
        _drive_every_screen(client, fake_storage)
        ids = action_ids(sent)
        orphaned = sorted(wa.handled_action_ids() - ids)
        assert orphaned == [], f"handlers for ids that are never sent: {orphaned}"

    def test_every_prefix_handler_is_reachable_from_a_screen(self, client, sent,
                                                             services, fake_storage):
        _drive_every_screen(client, fake_storage)
        ids = action_ids(sent)
        for prefix in wa.handled_action_prefixes():
            assert any(i.startswith(prefix) and len(i) > len(prefix) for i in ids), \
                f"no screen ever sends an id with prefix {prefix!r}"

    def test_registry_is_the_expected_shape(self):
        """Pin the id vocabulary so adding one without wiring it fails here."""
        assert wa.handled_action_ids() == {
            "menu", "help", "bus_search", "metro_search",
            "favorites", "trip", "language", "lang_pt", "lang_en",
        }
        assert wa.handled_action_prefixes() == {
            "stop_", "station_",
            "fav_add_stop_", "fav_add_station_",
            "fav_del_stop_", "fav_del_station_",
        }

    def test_prefix_handlers_are_ordered_longest_first(self):
        lengths = [len(prefix) for prefix, _ in wa._PREFIX_HANDLERS]
        assert lengths == sorted(lengths, reverse=True)

    def test_bare_prefix_without_payload_is_not_matched(self):
        assert not wa.handles_action_id("stop_")
        assert not wa.handles_action_id("station_")
        assert not wa.handles_action_id("")

    def test_unknown_action_id_is_ignored_safely(self, sent, services, fake_storage):
        asyncio.run(wa._handle_action(PHONE, "totally_unknown", "pt"))
        assert sent == []

    def test_list_and_button_replies_share_one_dispatcher(self, client, sent,
                                                          services, fake_storage):
        post(client, webhook_payload(button_message(wa.PREFIX_STOP + "BCM2")))
        from_button = texts(sent)
        sent.clear()
        post(client, webhook_payload(list_message(wa.PREFIX_STOP + "BCM2")))
        assert texts(sent) == from_button

    def test_all_button_titles_fit_whatsapp_limits(self, client, sent, services,
                                                   fake_storage):
        _drive_every_screen(client, fake_storage)
        for payload in sent:
            interactive = payload.get("interactive") or {}
            action = interactive.get("action") or {}
            buttons = action.get("buttons") or []
            assert len(buttons) <= wa.MAX_BUTTONS
            for button in buttons:
                assert len(button["reply"]["title"]) <= wa.MAX_BUTTON_TITLE_LEN
            for section in action.get("sections") or []:
                assert len(section["rows"]) <= wa.MAX_ROWS
                assert len(section["title"]) <= wa.MAX_ROW_TITLE_LEN
                for row in section["rows"]:
                    assert len(row["title"]) <= wa.MAX_ROW_TITLE_LEN
                    assert len(row.get("description", "")) <= wa.MAX_ROW_DESC_LEN
            if interactive:
                assert len(interactive["body"]["text"]) <= wa.MAX_BODY_LEN


# ===========================================================================
# 3. Non-blocking webhook + idempotency
# ===========================================================================

class TestWebhookIsNonBlocking:

    def test_work_is_deferred_off_the_request_path(self, monkeypatch, sent, services,
                                                   fake_storage):
        recorder = RecordingWorker()
        monkeypatch.setattr(wa, "worker", recorder)
        with wa.app.test_client() as client:
            resp = post(client, webhook_payload(text_message("menu")))
        assert resp.status_code == 200
        assert sent == [], "the request thread must not perform the reply"
        assert len(recorder.calls) == 1
        assert recorder.calls[0][0] is wa._process_message

    def test_background_worker_actually_processes_the_message(self, monkeypatch,
                                                              services, fake_storage):
        done = threading.Event()
        payloads = []

        def capture(payload):
            payloads.append(payload)
            done.set()

        monkeypatch.setattr(wa, "_api_call", capture)
        real_worker = BackgroundWorker(name="test-worker")
        monkeypatch.setattr(wa, "worker", real_worker)
        try:
            with wa.app.test_client() as client:
                resp = post(client, webhook_payload(text_message("menu")))
            assert resp.status_code == 200
            assert done.wait(timeout=10), "worker never processed the message"
            assert payloads
        finally:
            real_worker.shutdown()

    def test_worker_survives_a_failing_handler(self, monkeypatch, sent):
        async def boom(*args, **kwargs):
            raise RuntimeError("kaboom")

        worker = InlineWorker()
        worker.submit(boom)          # must not raise
        assert worker.calls


class TestIdempotency:

    def test_retried_delivery_does_not_send_a_second_reply(self, client, sent,
                                                           services, fake_storage):
        payload = webhook_payload(text_message("menu", message_id="wamid.RETRY"))
        first = post(client, payload)
        replies_after_first = len(sent)
        second = post(client, payload)

        assert first.status_code == 200
        assert second.status_code == 200, "a retry must still be acknowledged"
        assert replies_after_first > 0
        assert len(sent) == replies_after_first, \
            "a retried delivery must not produce a duplicate reply"

    def test_distinct_message_ids_are_both_processed(self, client, sent, services,
                                                     fake_storage):
        post(client, webhook_payload(text_message("menu", message_id="wamid.A")))
        first = len(sent)
        post(client, webhook_payload(text_message("menu", message_id="wamid.B")))
        assert len(sent) > first

    def test_duplicates_inside_a_single_payload_are_collapsed(self, client, sent,
                                                              services, fake_storage):
        post(client, webhook_payload(
            text_message("menu", message_id="wamid.SAME"),
            text_message("menu", message_id="wamid.SAME"),
        ))
        assert len(sent) == 1

    def test_dedup_cache_is_bounded(self):
        for n in range(wa._MAX_SEEN_IDS + 50):
            wa._already_processed(f"wamid.{n}")
        assert len(wa._seen_message_ids) <= wa._MAX_SEEN_IDS

    def test_status_callbacks_are_ignored(self, client, sent, services, fake_storage):
        payload = {"entry": [{"changes": [{"value": {
            "statuses": [{"id": "wamid.X", "status": "delivered"}],
        }}]}]}
        assert post(client, payload).status_code == 200
        assert sent == []

    def test_malformed_entries_do_not_crash_the_webhook(self, client, sent, services,
                                                        fake_storage):
        for payload in [
            {"entry": "nonsense"},
            {"entry": [None]},
            {"entry": [{"changes": None}]},
            {"entry": [{"changes": [{"value": {"messages": ["nope"]}}]}]},
            {},
        ]:
            assert post(client, payload).status_code == 200
        assert sent == []


# ===========================================================================
# 4. i18n and WhatsApp formatting
# ===========================================================================

class TestFormatting:

    def test_markdown_v2_escapes_are_stripped(self):
        assert from_markdown_v2("Bem\\-vindo\\!") == "Bem-vindo!"
        assert from_markdown_v2("a\\.b\\(c\\)") == "a.b(c)"

    def test_bold_and_italic_markers_survive(self):
        assert from_markdown_v2("*bold* and _italic_") == "*bold* and _italic_"

    def test_inline_code_spans_become_plain_text(self):
        assert from_markdown_v2("use `BCM2` now") == "use BCM2 now"

    def test_underline_degrades_to_italic(self):
        assert from_markdown_v2("__note__") == "_note_"

    def test_has_markdown_v2_escapes_detects_leftovers(self):
        assert has_markdown_v2_escapes("Bem\\-vindo")
        assert not has_markdown_v2_escapes("Bem-vindo")

    def test_truncate_respects_the_limit(self):
        assert truncate("abcdef", 4) == "abc…"
        assert truncate("abc", 10) == "abc"
        assert truncate("abc", 0) == ""

    def test_shared_telegram_strings_are_converted(self):
        """The shared i18n table is MarkdownV2 - users must not see backslashes."""
        for lang in ("pt", "en"):
            for key in ("welcome", "help", "trip_no_routes", "no_results",
                        "favs_empty_short", "metro_estimated_warning"):
                rendered = wt(key, lang, query="Bolhão")
                assert "\\" not in rendered, f"{key}/{lang} leaked an escape"

    def test_no_outbound_message_contains_markdown_v2_escapes(self, client, sent,
                                                              services, fake_storage):
        _drive_every_screen(client, fake_storage)
        post(client, webhook_payload(location_message(41.15, -8.61)))
        assert sent
        for payload in sent:
            for value in _iter_strings(payload):
                assert "\\" not in value, f"visible backslash in {value!r}"

    def test_every_wa_string_key_exists_in_both_languages(self):
        assert set(WA_STRINGS["pt"]) == set(WA_STRINGS["en"])

    def test_wa_strings_contain_no_markdown_v2_escaping(self):
        for lang_table in WA_STRINGS.values():
            for key, value in lang_table.items():
                assert not has_markdown_v2_escapes(value), key

    def test_missing_key_falls_back_without_raising(self):
        assert wt("definitely_not_a_key_1234", "pt") == "definitely_not_a_key_1234"

    def test_bad_format_arguments_do_not_raise(self):
        assert wt("no_results", "pt", wrong_kwarg="x")


def _iter_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_strings(item)


class TestLanguage:

    def test_portuguese_number_defaults_to_pt(self):
        assert lang_from_phone("351912345678") == "pt"

    def test_foreign_number_defaults_to_en(self):
        assert lang_from_phone("447700900123") == "en"
        assert lang_from_phone("15550101") == "en"

    def test_normalise_lang_falls_back_to_pt(self):
        assert normalise_lang("pt-PT") == "pt"
        assert normalise_lang("en-GB") == "en"
        assert normalise_lang("de") == "pt"
        assert normalise_lang(None) == "pt"

    def test_language_command_switches_the_reply_language(self, client, sent,
                                                          services, fake_storage):
        post(client, webhook_payload(text_message("idioma en")))
        assert fake_storage.languages[PHONE] == "en"
        sent.clear()
        post(client, webhook_payload(button_message(wa.ACTION_HELP)))
        assert "How to use" in "\n".join(texts(sent))

    def test_language_buttons_switch_the_reply_language(self, client, sent, services,
                                                       fake_storage):
        post(client, webhook_payload(button_message(wa.ACTION_LANG_EN)))
        assert fake_storage.languages[PHONE] == "en"
        assert "English" in "\n".join(texts(sent))

    def test_stored_preference_beats_the_phone_prefix(self, client, sent, services,
                                                      fake_storage):
        fake_storage.languages[PHONE] = "en"
        post(client, webhook_payload(button_message(wa.ACTION_HELP)))
        assert "How to use" in "\n".join(texts(sent))

    def test_payload_locale_is_used_when_present(self, client, sent, services,
                                                 fake_storage):
        payload = webhook_payload(
            button_message(wa.ACTION_HELP),
            contacts=[{"wa_id": PHONE, "profile": {"name": "A", "locale": "en_GB"}}],
        )
        post(client, payload)
        assert "How to use" in "\n".join(texts(sent))

    def test_foreign_number_gets_english_by_default(self, client, sent, services,
                                                    fake_storage):
        post(client, webhook_payload(
            button_message(wa.ACTION_HELP, sender="447700900123")))
        assert "How to use" in "\n".join(texts(sent))


# ===========================================================================
# 5. Favorites (feature parity)
# ===========================================================================

class TestFavorites:

    def test_add_list_and_remove_round_trip(self, client, sent, services,
                                            fake_storage):
        # Look the stop up, then tap "add favorite".
        post(client, webhook_payload(text_message("BCM2")))
        add_ids = [i for i in action_ids(sent) if i.startswith(wa.PREFIX_FAV_ADD_STOP)]
        assert add_ids == [wa.PREFIX_FAV_ADD_STOP + "BCM2"]

        sent.clear()
        post(client, webhook_payload(button_message(add_ids[0])))
        assert fake_storage.favorites[PHONE] == [
            {"type": wa.FAV_TYPE_STOP, "id": "BCM2", "name": "Bolhão (Loureiro)"},
        ]
        assert "Bolhão (Loureiro)" in "\n".join(texts(sent))

        # It now appears in the favorites list, as a tappable row.
        sent.clear()
        post(client, webhook_payload(text_message("favoritos")))
        assert wa.PREFIX_STOP + "BCM2" in action_ids(sent)

        # Adding twice is reported, not duplicated.
        sent.clear()
        post(client, webhook_payload(button_message(add_ids[0])))
        assert len(fake_storage.favorites[PHONE]) == 1
        assert "favorito" in "\n".join(texts(sent)).lower()

        # And it can be removed.
        sent.clear()
        post(client, webhook_payload(button_message(wa.PREFIX_FAV_DEL_STOP + "BCM2")))
        assert fake_storage.favorites[PHONE] == []

    def test_detail_screen_offers_remove_once_saved(self, client, sent, services,
                                                    fake_storage):
        fake_storage.favorites[PHONE] = [
            {"type": wa.FAV_TYPE_STOP, "id": "BCM2", "name": "Bolhão (Loureiro)"},
        ]
        post(client, webhook_payload(text_message("BCM2")))
        ids = action_ids(sent)
        assert wa.PREFIX_FAV_DEL_STOP + "BCM2" in ids
        assert wa.PREFIX_FAV_ADD_STOP + "BCM2" not in ids

    def test_station_favorites_round_trip(self, client, sent, services, fake_storage):
        post(client, webhook_payload(text_message("Trindade")))
        assert wa.PREFIX_FAV_ADD_STATION + "Trindade" in action_ids(sent)
        post(client, webhook_payload(
            button_message(wa.PREFIX_FAV_ADD_STATION + "Trindade")))
        assert fake_storage.favorites[PHONE] == [
            {"type": wa.FAV_TYPE_STATION, "id": "Trindade", "name": "Trindade"},
        ]

    def test_empty_favorites_screen_offers_a_way_out(self, client, sent, services,
                                                     fake_storage):
        post(client, webhook_payload(text_message("favoritos")))
        assert wa.ACTION_MENU in action_ids(sent)
        assert action_ids(sent), "the empty state must still be actionable"

    def test_favorite_types_match_the_telegram_vocabulary(self):
        """Both channels share one store, so the type strings must agree."""
        from bot.handlers.favorites import FAV_TYPES
        assert wa.FAV_TYPE_STOP in FAV_TYPES
        assert wa.FAV_TYPE_STATION in FAV_TYPES

    def test_unsupported_favorite_types_are_skipped_not_dead_rows(self, client, sent,
                                                                  services,
                                                                  fake_storage):
        fake_storage.favorites[PHONE] = [
            {"type": "train", "id": "Campanhã", "name": "Campanhã"},
        ]
        post(client, webhook_payload(text_message("favoritos")))
        for action_id in action_ids(sent):
            assert wa.handles_action_id(action_id)


class TestWhatsAppUserIds:

    def test_ids_are_negative_so_they_cannot_collide_with_telegram(self):
        """users.id is a BIGINT, so a 'wa:' string prefix is impossible.

        Namespacing is done by sign instead: Telegram ids are always positive.
        """
        wa_id = wa_storage.wa_user_id(PHONE)
        assert isinstance(wa_id, int)
        assert wa_id < 0
        assert wa_id == -int(PHONE)

    def test_ids_are_stable_and_ignore_formatting(self):
        assert (wa_storage.wa_user_id("+351 912 345 678")
                == wa_storage.wa_user_id("351912345678"))

    def test_ids_stay_inside_bigint_range(self):
        for phone in [PHONE, "1" * 15, "9" * 40]:
            assert -9_223_372_036_854_775_808 <= wa_storage.wa_user_id(phone) < 0

    def test_distinct_phones_get_distinct_ids(self):
        assert wa_storage.wa_user_id("351911111111") != wa_storage.wa_user_id("351922222222")

    def test_empty_sender_is_rejected(self):
        with pytest.raises(ValueError):
            wa_storage.wa_user_id("")

    def test_users_id_column_is_bigint(self):
        """Documents *why* the id must stay numeric (see whatsapp/storage.py)."""
        import bot.database as db
        schema = getattr(db, "_SCHEMA_SQL", "")
        if not schema:
            pytest.skip("bot.database no longer exposes _SCHEMA_SQL")
        assert "id          BIGINT PRIMARY KEY" in schema or "BIGINT" in schema


class TestSharedDatabaseStorage:
    """Round-trip through the real bot.database JSON fallback."""

    @pytest.fixture
    def json_store(self, monkeypatch, tmp_path):
        import bot.database as db
        if not hasattr(db, "_FAVORITES_DIR"):
            pytest.skip("bot.database no longer uses _FAVORITES_DIR")
        monkeypatch.setattr(db, "_FAVORITES_DIR", tmp_path / "favorites")
        monkeypatch.setattr(db, "_use_db", False)
        return db

    def test_favorites_round_trip_through_bot_database(self, json_store):
        async def scenario():
            assert await wa_storage.get_favorites(PHONE) == []
            assert await wa_storage.add_favorite(PHONE, "bus", "BCM2", "Bolhão")
            assert not await wa_storage.add_favorite(PHONE, "bus", "BCM2", "Bolhão")
            assert await wa_storage.is_favorite(PHONE, "bus", "BCM2")
            assert await wa_storage.get_favorites(PHONE) == [
                {"type": "bus", "id": "BCM2", "name": "Bolhão"},
            ]
            assert await wa_storage.remove_favorite(PHONE, "bus", "BCM2")
            assert await wa_storage.get_favorites(PHONE) == []

        asyncio.run(scenario())

    def test_whatsapp_favorites_do_not_leak_into_a_telegram_user(self, json_store):
        """The same digits as a Telegram id must land in a different bucket."""
        async def scenario():
            await wa_storage.add_favorite(PHONE, "bus", "BCM2", "Bolhão")
            telegram_id = int(PHONE)          # positive: a Telegram account id
            assert await json_store.get_favorites(telegram_id) == []
            assert await json_store.get_favorites(wa_storage.wa_user_id(PHONE))

        asyncio.run(scenario())

    def test_storage_degrades_instead_of_raising(self, monkeypatch):
        """bot.database is another owner's file - a break must not 500."""
        import bot.database as db

        async def explode(*args, **kwargs):
            raise RuntimeError("db down")

        monkeypatch.setattr(db, "get_favorites", explode)
        monkeypatch.setattr(db, "add_favorite", explode)
        assert asyncio.run(wa_storage.get_favorites(PHONE)) == []
        assert asyncio.run(wa_storage.add_favorite(PHONE, "bus", "X", "X")) is False

    def test_missing_database_function_degrades(self, monkeypatch):
        import bot.database as db
        monkeypatch.delattr(db, "is_favorite", raising=False)
        assert asyncio.run(wa_storage.is_favorite(PHONE, "bus", "X")) is False

    def test_bot_database_exposes_the_api_storage_relies_on(self):
        import bot.database as db
        for name in ("add_favorite", "remove_favorite", "get_favorites",
                     "is_favorite", "get_user_settings", "update_user_setting"):
            assert callable(getattr(db, name, None)), f"bot.database.{name} is missing"


# ===========================================================================
# 6. Bug fixes
# ===========================================================================

class TestLocationHandling:

    def test_zero_coordinates_are_processed(self, client, sent, services,
                                            fake_storage, monkeypatch):
        """`if lat and lon:` used to silently drop lat/lon of exactly 0.0."""
        seen = []

        def record_nearby(lat, lon, radius_km=0.75):
            seen.append((lat, lon))
            return _fake_get_nearby_stations(lat, lon, radius_km)

        from bot.services import metro as metro_service
        monkeypatch.setattr(metro_service, "get_nearby_stations", record_nearby)

        post(client, webhook_payload(location_message(0.0, 0.0)))
        assert seen == [(0.0, 0.0)], "coordinates 0.0/0.0 must not be dropped"
        assert sent

    def test_normal_coordinates_are_processed(self, client, sent, services,
                                             fake_storage):
        post(client, webhook_payload(location_message(41.1579, -8.6291)))
        body = "\n".join(texts(sent))
        assert "Aliados" in body
        assert "Praça da Liberdade" in body

    def test_missing_coordinates_are_ignored(self, client, sent, services,
                                            fake_storage):
        msg = location_message(0.0, 0.0)
        msg["location"] = {"latitude": None, "longitude": None}
        post(client, webhook_payload(msg))
        assert sent == []

    def test_non_numeric_coordinates_do_not_crash(self, client, sent, services,
                                                  fake_storage):
        msg = location_message(0.0, 0.0)
        msg["location"] = {"latitude": "abc", "longitude": "def"}
        assert post(client, webhook_payload(msg)).status_code == 200

    def test_nothing_nearby_still_replies(self, client, sent, services, fake_storage,
                                          monkeypatch):
        from bot.services import metro as metro_service
        monkeypatch.setattr(metro_service, "get_nearby_stations",
                            lambda *a, **k: [])

        async def no_stops(*args, **kwargs):
            return []

        monkeypatch.setattr(wa.stcp, "search_nearby_stops", no_stops)
        post(client, webhook_payload(location_message(41.1, -8.6)))
        assert sent, "an empty nearby search must still answer the user"


class TestSessionState:
    """The `_sessions` dict used to be declared and never read."""

    def test_bus_search_arms_a_bus_only_search(self, client, sent, services,
                                               fake_storage):
        post(client, webhook_payload(button_message(wa.ACTION_BUS_SEARCH)))
        assert wa._session(PHONE)["state"] == "await_bus"

        sent.clear()
        # "Trindade" is a metro station; in bus mode it must NOT return metro.
        post(client, webhook_payload(text_message("Trindade")))
        body = "\n".join(texts(sent))
        assert "🚇 *Trindade*" not in body
        assert wa.ACTION_BUS_SEARCH in action_ids(sent)

    def test_metro_search_arms_a_metro_only_search(self, client, sent, services,
                                                   fake_storage):
        post(client, webhook_payload(button_message(wa.ACTION_METRO_SEARCH)))
        assert wa._session(PHONE)["state"] == "await_metro"
        sent.clear()
        post(client, webhook_payload(text_message("Trindade")))
        assert "🚇 *Trindade*" in "\n".join(texts(sent))

    def test_state_is_consumed_after_one_message(self, client, sent, services,
                                                 fake_storage):
        post(client, webhook_payload(button_message(wa.ACTION_METRO_SEARCH)))
        post(client, webhook_payload(text_message("Trindade")))
        assert "state" not in wa._session(PHONE)

    def test_menu_command_clears_a_pending_state(self, client, sent, services,
                                                 fake_storage):
        post(client, webhook_payload(button_message(wa.ACTION_BUS_SEARCH)))
        post(client, webhook_payload(text_message("menu")))
        assert "state" not in wa._session(PHONE)

    def test_cancel_clears_a_pending_state(self, client, sent, services,
                                           fake_storage):
        post(client, webhook_payload(button_message(wa.ACTION_BUS_SEARCH)))
        sent.clear()
        post(client, webhook_payload(text_message("cancelar")))
        assert "state" not in wa._session(PHONE)
        assert sent

    def test_session_store_is_bounded(self):
        for n in range(wa._MAX_SESSIONS + 25):
            wa._session(f"3519{n:08d}")
        assert len(wa._sessions) <= wa._MAX_SESSIONS

    def test_name_cache_is_bounded(self):
        for n in range(120):
            wa._remember_name(PHONE, "bus", f"S{n}", f"Stop {n}")
        assert len(wa._session(PHONE)["names"]) <= 50


class TestPrivacyInLogs:

    def test_phone_numbers_are_masked(self):
        masked = wa._mask(PHONE)
        assert PHONE not in masked
        assert masked.endswith(PHONE[-3:])
        assert wa._mask("12") == "***"
        assert wa._mask("") == "***"


# ===========================================================================
# 7. Text routing
# ===========================================================================

class TestTextRouting:

    @pytest.mark.parametrize("greeting", ["ola", "olá", "oi", "hi", "menu", "start"])
    def test_greetings_open_the_main_menu(self, client, sent, services, fake_storage,
                                          greeting):
        post(client, webhook_payload(text_message(greeting)))
        assert wa.ACTION_HELP in action_ids(sent)

    def test_stop_code_returns_arrivals(self, client, sent, services, fake_storage):
        post(client, webhook_payload(text_message("bcm2")))
        body = "\n".join(texts(sent))
        assert "Bolhão (Loureiro)" in body
        assert "200" in body

    def test_stop_name_returns_a_list(self, client, sent, services, fake_storage):
        post(client, webhook_payload(text_message("Bolhão")))
        assert wa.PREFIX_STOP + "BCM1" in action_ids(sent)

    def test_ambiguous_station_returns_a_list(self, client, sent, services,
                                              fake_storage):
        post(client, webhook_payload(text_message("Bol")))
        assert wa.PREFIX_STATION + "Bolhão" in action_ids(sent)

    def test_unknown_text_offers_next_steps(self, client, sent, services,
                                            fake_storage):
        post(client, webhook_payload(text_message("qwertyuiop")))
        assert action_ids(sent) == {wa.ACTION_BUS_SEARCH, wa.ACTION_METRO_SEARCH,
                                    wa.ACTION_HELP}

    def test_empty_text_falls_back_to_the_menu(self, client, sent, services,
                                               fake_storage):
        post(client, webhook_payload(text_message("   ")))
        assert wa.ACTION_HELP in action_ids(sent)

    def test_metro_departures_include_the_estimate_warning(self, client, sent,
                                                           services, fake_storage):
        post(client, webhook_payload(text_message("Trindade")))
        body = "\n".join(texts(sent))
        assert "estimados" in body.lower()
        assert "\\" not in body


class TestTripPlanning:

    @pytest.fixture
    def planner(self, monkeypatch):
        from bot.services import trip_planner
        from bot.services.trip_planner import TripOption, TripStep

        monkeypatch.setattr(trip_planner, "resolve_location", lambda text: (
            {"name": "Trindade", "lat": 41.15, "lon": -8.6, "type": "metro"}
            if text.strip().lower() == "trindade" else None
        ))
        option = TripOption(
            steps=[
                TripStep(mode="walk", from_name="", to_name="Trindade",
                         duration_min=4),
                TripStep(mode="metro", from_name="Trindade", to_name="Bolhão",
                         line="A", duration_min=3),
            ],
            total_time_min=7, transfers=1, zones=["PRT1"],
        )
        monkeypatch.setattr(trip_planner, "plan_trip",
                            lambda origin, dest: [option])
        return trip_planner

    def test_trip_flow_asks_for_both_ends_then_answers(self, client, sent, services,
                                                        fake_storage, planner):
        post(client, webhook_payload(button_message(wa.ACTION_TRIP)))
        assert wa._session(PHONE)["state"] == "await_trip_origin"

        sent.clear()
        post(client, webhook_payload(text_message("Trindade")))
        assert wa._session(PHONE)["state"] == "await_trip_dest"
        assert wa._session(PHONE)["trip_origin"] == "Trindade"

        sent.clear()
        post(client, webhook_payload(text_message("Bolhão")))
        body = "\n".join(texts(sent))
        assert "Trindade" in body and "Bolhão" in body
        assert "7 min" in body
        assert "\\" not in body
        assert wa.ACTION_TRIP in action_ids(sent)

    def test_unresolvable_origin_reprompts(self, client, sent, services,
                                           fake_storage, planner):
        post(client, webhook_payload(button_message(wa.ACTION_TRIP)))
        sent.clear()
        post(client, webhook_payload(text_message("nowhere at all")))
        assert wa._session(PHONE)["state"] == "await_trip_origin"
        assert "nowhere at all" in "\n".join(texts(sent))

    def test_no_routes_offers_a_retry(self, client, sent, services, fake_storage,
                                      planner, monkeypatch):
        monkeypatch.setattr(planner, "plan_trip", lambda origin, dest: [])
        post(client, webhook_payload(button_message(wa.ACTION_TRIP)))
        post(client, webhook_payload(text_message("Trindade")))
        sent.clear()
        post(client, webhook_payload(text_message("Bolhão")))
        assert wa.ACTION_TRIP in action_ids(sent)

    def test_planner_failure_is_reported_not_crashed(self, client, sent, services,
                                                     fake_storage, planner,
                                                     monkeypatch):
        def explode(origin, dest):
            raise RuntimeError("planner down")

        monkeypatch.setattr(planner, "plan_trip", explode)
        post(client, webhook_payload(button_message(wa.ACTION_TRIP)))
        post(client, webhook_payload(text_message("Trindade")))
        sent.clear()
        resp = post(client, webhook_payload(text_message("Bolhão")))
        assert resp.status_code == 200
        assert texts(sent), "the user must be told something went wrong"


# ===========================================================================
# 8. Outbound API call
# ===========================================================================

class TestApiCall:

    def test_nothing_is_sent_without_credentials(self, monkeypatch):
        posts = []
        monkeypatch.setattr(wa.requests, "post", lambda *a, **k: posts.append(a))
        monkeypatch.setattr(wa, "WHATSAPP_TOKEN", "")
        monkeypatch.setattr(wa, "WHATSAPP_PHONE_ID", "")
        wa._api_call({"to": PHONE})
        assert posts == [], "must never contact Graph without credentials"

    def test_payload_is_posted_with_the_bearer_token(self, monkeypatch):
        captured = {}

        class Resp:
            status_code = 200
            text = ""

        def fake_post(url, json=None, headers=None, timeout=None):
            captured.update(url=url, json=json, headers=headers, timeout=timeout)
            return Resp()

        monkeypatch.setattr(wa.requests, "post", fake_post)
        monkeypatch.setattr(wa, "WHATSAPP_TOKEN", "tok")
        monkeypatch.setattr(wa, "WHATSAPP_PHONE_ID", "pid")
        wa._api_call({"to": PHONE, "type": "text"})
        assert captured["headers"]["Authorization"] == "Bearer tok"
        assert captured["timeout"] == 10

    def test_network_errors_are_swallowed(self, monkeypatch):
        def boom(*args, **kwargs):
            raise OSError("network down")

        monkeypatch.setattr(wa.requests, "post", boom)
        monkeypatch.setattr(wa, "WHATSAPP_TOKEN", "tok")
        monkeypatch.setattr(wa, "WHATSAPP_PHONE_ID", "pid")
        wa._api_call({"to": PHONE})   # must not raise

    def test_long_text_is_truncated_to_the_api_limit(self, sent):
        wa._send_text(PHONE, "x" * 9000)
        assert len(sent[0]["text"]["body"]) <= wa.MAX_TEXT_LEN

    def test_buttons_fall_back_to_text_when_empty(self, sent):
        wa._send_buttons(PHONE, "hello", [])
        assert sent[0]["type"] == "text"

    def test_list_falls_back_to_text_when_empty(self, sent):
        wa._send_list(PHONE, "hello", "go", "sec", [])
        assert sent[0]["type"] == "text"


# ===========================================================================
# 9. Module hygiene
# ===========================================================================

class TestModuleHygiene:

    def test_module_docstring_documents_the_secret_env_var(self):
        assert "WHATSAPP_APP_SECRET" in (wa.__doc__ or "")
        assert "WHATSAPP_ALLOW_UNSIGNED_WEBHOOKS" in (wa.__doc__ or "")

    def test_docstring_points_at_gunicorn_not_the_dev_server(self):
        assert "gunicorn" in (wa.__doc__ or "")

    def test_app_is_importable_as_a_wsgi_callable(self):
        module = importlib.import_module("whatsapp.app")
        assert callable(module.app)

    def test_no_unused_session_dict(self):
        """_sessions used to be dead; it must now be read by the app."""
        import inspect
        source = inspect.getsource(wa)
        assert source.count("_sessions") > 1
        assert "_sessions.get" in source
