# WhatsApp Bot - Porto Transport

WhatsApp alternative for the Porto Transport Bot, built on the Meta WhatsApp
Cloud API.

## Setup

1. Create a [Meta Business Account](https://business.facebook.com/)
2. Create a WhatsApp Business App in [Meta Developer Portal](https://developers.facebook.com/)
3. Get your credentials from the WhatsApp section:
   - **WHATSAPP_TOKEN**: Permanent access token
   - **WHATSAPP_PHONE_ID**: Phone number ID
   - **WHATSAPP_APP_SECRET**: App Secret (Settings → Basic → App Secret)
4. Add to your `.env` file:
   ```
   WHATSAPP_TOKEN=your_token
   WHATSAPP_PHONE_ID=your_phone_id
   WHATSAPP_VERIFY_TOKEN=porto-transport-bot
   WHATSAPP_APP_SECRET=your_app_secret
   WHATSAPP_PORT=8080
   ```
5. Deploy and configure the webhook URL:
   ```
   https://your-domain/webhook
   ```
6. Subscribe to `messages` webhook events

## Environment variables

| Variable | Required | Purpose |
| --- | --- | --- |
| `WHATSAPP_TOKEN` | yes | Bearer token for outbound Graph API calls. |
| `WHATSAPP_PHONE_ID` | yes | Phone number id used to build the Graph API URL. |
| `WHATSAPP_VERIFY_TOKEN` | yes | Shared secret echoed during the `GET /webhook` subscription handshake (compared in constant time). |
| `WHATSAPP_APP_SECRET` | **yes in production** | Meta App Secret used to verify the `X-Hub-Signature-256` HMAC-SHA256 over the raw request body. **If unset, the webhook rejects every POST with 403 (fail closed).** |
| `WHATSAPP_ALLOW_UNSIGNED_WEBHOOKS` | no | Local-development escape hatch (`true`/`1`/`yes`/`on`). Only has an effect when `WHATSAPP_APP_SECRET` is empty. **Never set this in production.** |
| `WHATSAPP_PORT` | no | Port for the local dev server (default `8080`). |
| `DATABASE_URL` | no | Inherited from the Telegram bot; when set, favorites/settings go to PostgreSQL instead of JSON files. |

`GET /health` reports the active webhook auth mode: `enforced`, `dev-unsigned`
or `fail-closed`.

## Webhook security

Every `POST /webhook` is authenticated before anything else happens:

* the HMAC-SHA256 is computed over the **raw** request body (`request.get_data()`),
  not over a re-serialised copy of the parsed JSON,
* the comparison uses `hmac.compare_digest` (constant time),
* an unsigned, malformed or mismatched signature gets a `403` and no reply is
  ever sent,
* with no `WHATSAPP_APP_SECRET` configured the endpoint **fails closed**; the only
  way to accept unsigned traffic is the explicit
  `WHATSAPP_ALLOW_UNSIGNED_WEBHOOKS` dev flag, which is logged loudly on every
  request.

Without this, anyone who discovered the webhook URL could inject fake inbound
messages and make the bot send WhatsApp messages to arbitrary phone numbers.

## Reliability

* **Non-blocking webhook.** The Flask view validates, de-duplicates, hands the
  message to a background worker and returns `200` immediately. The worker
  (`whatsapp/worker.py`) owns a single persistent asyncio event loop in a daemon
  thread, so STCP/Metro/Graph round-trips never delay the acknowledgement.
* **Idempotency.** Meta retries deliveries it considers unacknowledged, and a
  retry carries the same message id. Inbound ids are remembered (bounded LRU) and
  redeliveries are dropped, so a retry cannot produce a second reply.

## Run

Production - use gunicorn, never the Flask dev server (it is single threaded, so
a slow request would stall the webhook and trigger Meta retries):

```bash
gunicorn whatsapp.app:app --bind 0.0.0.0:8080 --workers 2 --timeout 30
```

Local development:

```bash
python -m whatsapp.app
```

Or with Docker:
```bash
docker-compose up whatsapp
```

## Features

- Search bus stops by name or code
- Real-time bus arrivals
- Metro station schedules
- Location-based nearby transport
- Favorites (add / list / remove), sharing the Telegram bot's storage layer
- Trip planning (origin → destination)
- Interactive menus and lists
- PT / EN localisation (`idioma` / `language` command, or the menu entry)

## Localisation

Copy comes from the shared PT/EN table in `bot/utils/i18n.py`, plus
WhatsApp-specific strings in `whatsapp/strings.py`. The shared table is
MarkdownV2-escaped for Telegram, so every string is passed through
`whatsapp.formatting.from_markdown_v2`, which strips the escapes (WhatsApp uses
`*bold*` / `_italic_` and no backslash escaping). Language is resolved as:
explicit user preference → locale in the inbound payload (if Meta ever sends one)
→ phone country code (`+351` → PT, otherwise EN).

## Storage / user ids

Favorites and the language preference are stored through `bot/database.py`, the
same layer the Telegram bot uses. WhatsApp identifies users by phone number, but
`users.id` is a `BIGINT`, so a textual `wa:` prefix cannot be stored. Ids are
namespaced **by sign** instead: a WhatsApp user is `-int(e164_digits)`, and
Telegram user ids are always positive, so the two channels can never collide.

## Tests

```bash
python -m pytest tests/test_whatsapp.py -q
```

All network I/O is mocked; no test contacts Meta and no message is ever sent to
a real phone number.
