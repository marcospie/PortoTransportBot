# Porto Transport Bot

Telegram (and WhatsApp) bot for real-time Porto public transport information.

> Versao portuguesa: [README.md](README.md)

## Features

- **STCP buses** - real-time arrivals for every stop
- **Porto Metro** - schedules per station and per line (GTFS + known frequencies)
- **MetroBus (BRT)** - lines, stops and frequencies
- **CP trains** - suburban stations and lines
- **Trip planner** - route suggestions between two points (`/route`)
- **Stops near me** - share your location and see what passes nearby
- **Favorites** - save your most used stops and stations
- **Commuter profile** - store home/work and check your usual trip in one tap
- **Andante zone calculator** - how many zones you need between two points
- **Service alerts** - disruptions and operator notices
- **Accessibility** - lifts, ramps and maintenance status per station
- **Weather** - Porto forecast, handy before heading out
- **Events in Porto** - what's on and how to get there by public transport
- **Tourist guide** - points of interest and recommended tickets
- **Inline mode** - type `@YourBotName stop` in any chat
- **Bilingual** - Portuguese and English, picked up from the Telegram client language
- **Settings** - search radii, result count, language and notifications

## Bot commands

Complete list of the commands registered in `bot/main.py`:

| Command | Description |
|---------|-------------|
| `/start` | Main menu |
| `/help` | Help |
| `/bus` | STCP bus menu |
| `/metro` | Porto Metro menu |
| `/stop BCM2` | Real-time arrivals for an STCP stop by code |
| `/station Trindade` | Metro station schedules |
| `/route` | Plan a route |
| `/favorites` | Manage favorites |
| `/fav` | Quick favorite |
| `/settings` | Settings (radii, results, language, notifications) |
| `/metrobus` | MetroBus (BRT) |
| `/comboios` | CP trains |
| `/estacao Campanha` | CP train station |
| `/zonas` | Andante zone calculator |
| `/tourist` | Tourist guide |
| `/commuter` | Commuter profile (home/work) |
| `/alertas` | Service alerts |
| `/acessibilidade` | Station accessibility |
| `/meteo` | Porto weather |
| `/eventos` | Events in Porto |

You can also send free text - the bot tries to match stops or stations - or share your
location to see nearby transport.

## Getting started

1. Talk to [@BotFather](https://t.me/BotFather) on Telegram, send `/newbot`, copy the token
2. `cp .env.example .env` and paste your token
3. Run it:

```bash
pip install -r requirements.txt
python run.py
```

Or with Docker:

```bash
sudo chown -R 10001:10001 ./data    # the container runs as UID 10001
docker compose up -d bot
```

## Environment variables

Complete list of every variable the code reads.

### Telegram bot

| Variable | Required | Default | Read in | Purpose |
|----------|----------|---------|---------|---------|
| `TELEGRAM_BOT_TOKEN` | **Yes** | *(empty)* | `bot/config.py` | @BotFather token. Without it `run.py` prints an error and exits. |
| `DATABASE_URL` | No, but **strongly recommended** | *(empty)* | `bot/database.py` | PostgreSQL DSN (`postgresql://user:pass@host:5432/db`). **Without it user data is stored in JSON files and is LOST on every restart** - see [Data persistence](#data-persistence). |

### WhatsApp service (optional)

| Variable | Required | Default | Read in | Purpose |
|----------|----------|---------|---------|---------|
| `WHATSAPP_TOKEN` | Yes (for WhatsApp) | *(empty)* | `whatsapp/app.py` | Meta permanent access token for outbound Graph API calls. |
| `WHATSAPP_PHONE_ID` | Yes (for WhatsApp) | *(empty)* | `whatsapp/app.py` | Meta phone number ID. |
| `WHATSAPP_VERIFY_TOKEN` | Yes (for WhatsApp) | `porto-transport-bot` | `whatsapp/app.py` | Shared secret echoed during the `GET /webhook` handshake. |
| `WHATSAPP_APP_SECRET` | **Yes in production** | *(empty)* | `whatsapp/app.py` | Meta App Secret. Authenticates every `POST /webhook` with HMAC-SHA256 over the raw body against `X-Hub-Signature-256`. **If empty the webhook returns 403 for all POSTs** (fail-closed): without it, anyone who finds the URL can inject fake messages. |
| `WHATSAPP_ALLOW_UNSIGNED_WEBHOOKS` | No | *(unset)* | `whatsapp/app.py` | **Development-only** escape hatch (`true`/`1`/`yes`/`on`). Only has an effect when `WHATSAPP_APP_SECRET` is empty. **Never set this in production.** |
| `WHATSAPP_PORT` | No | `8080` | `whatsapp/app.py` | Development server port; also used by `docker-compose.yml`. |

### Provided by the platform

| Variable | Set by | Purpose |
|----------|--------|---------|
| `PORT` | Heroku / Procfile platforms | Port the `web:` process (gunicorn) must listen on. Already used in the `Procfile`. |

> This repository's `.env.example` does not yet include `WHATSAPP_APP_SECRET` or
> `WHATSAPP_ALLOW_UNSIGNED_WEBHOOKS`. Use the table above as the reference.

## Data persistence

**Read this before deploying.**

`bot/database.py` works in two modes:

1. **With `DATABASE_URL`** - uses PostgreSQL (via `asyncpg`), creates its own schema
   (`users`, `favorites`, `user_settings`, `commuter_profiles`) and data survives restarts
   and redeploys.
2. **Without `DATABASE_URL`** - falls back to JSON files under `data/`
   (`data/favorites/`, `data/settings/`, `data/commuter/`, `data/users/`).

The JSON fallback is convenient locally, but **Railway, Heroku and Docker containers
without a volume have an ephemeral filesystem**: every redeploy, restart or crash wipes
everything under `data/`. That means losing **every user's favorites, settings and
commuter profiles**.

When it starts without `DATABASE_URL` the bot logs a prominent `WARNING` saying exactly this.

### Recommended: PostgreSQL

1. Create a PostgreSQL database (Railway, Neon, Supabase, Heroku Postgres, ...)
2. Set `DATABASE_URL` on the bot service
3. Restart the bot

No manual migrations needed: `init_db()` runs `CREATE TABLE IF NOT EXISTS` plus
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` migrations at startup.

### Verifying persistence works

1. Startup logs must **not** contain `DATABASE_URL is NOT set`. They should contain
   `PostgreSQL database initialised (pool ready)`.
2. In Telegram, add a favorite via `/favorites` (or the star button).
3. Redeploy/restart the service.
4. Send `/favorites` again - the favorite must still be there.
5. Optionally check the database:
   ```sql
   SELECT count(*) FROM favorites;
   SELECT count(*) FROM user_settings;
   SELECT count(*) FROM commuter_profiles;
   ```

### Migrating existing JSON favorites

```python
import asyncio
from bot.database import init_db, migrate_from_json, close_db

async def main():
    await init_db()             # requires DATABASE_URL
    await migrate_from_json()   # reads data/favorites/*.json
    await close_db()

asyncio.run(main())
```

## Deployment

### Railway

1. Create a project on [Railway](https://railway.app) and link your GitHub repo
2. **Add PostgreSQL**: `New` -> `Database` -> `Add PostgreSQL`
3. In the bot service `Variables` set:
   - `TELEGRAM_BOT_TOKEN` = your @BotFather token
   - `DATABASE_URL` = `${{Postgres.DATABASE_URL}}`
4. Automatic deploy on every commit (CD is on by default)
5. Confirm the logs show `PostgreSQL database initialised (pool ready)`

`railway.toml` uses `restartPolicyType = "ALWAYS"`. This matters: with the previous
`on_failure` + `restartPolicyMaxRetries = 10`, the bot stayed **permanently down** after
10 crashes (for example during a long Telegram API outage) until someone redeployed by hand.

**If you still prefer JSON mode**, you need a persistent volume. Volumes **cannot** be
declared in `railway.toml` (the config-as-code schema only covers build/deploy settings),
so attach one in the dashboard: service -> `Settings` -> `Volumes` -> `Add Volume`, mount
path `/app/data`. PostgreSQL is still the safer option.

### Heroku and other Procfile platforms

The `Procfile` declares two processes:

```
worker: python run.py                       # Telegram bot (long polling)
web:    gunicorn ... whatsapp.app:app       # WhatsApp service
```

```bash
heroku create
heroku addons:create heroku-postgresql:essential-0   # sets DATABASE_URL automatically
heroku config:set TELEGRAM_BOT_TOKEN=xxxxx
git push heroku main
heroku ps:scale worker=1        # Telegram bot
# heroku ps:scale web=1         # only if you also want WhatsApp
```

The `heroku-postgresql` addon sets `DATABASE_URL` for you - without it the dyno filesystem
is ephemeral and data disappears on every restart (which on Heroku happens at least daily).

### Docker / docker-compose

```bash
sudo chown -R 10001:10001 ./data    # the container runs as UID 10001
docker compose up -d                # bot + whatsapp
docker compose up -d bot            # Telegram bot only
docker compose ps                   # shows healthcheck status
```

Image notes:

- Runs as a **non-root** user (`appuser`, UID/GID 10001)
- `.dockerignore` keeps `.git/`, `tests/` and the local `data/` out of the image
- A `HEALTHCHECK` verifies the package imports and that `/app/data` is writable by
  `appuser` (catches a volume mounted with the wrong owner, which would silently break
  JSON storage)
- The `whatsapp` service has its own HTTP healthcheck against `/health`
- Both services use `restart: unless-stopped`

## WhatsApp service

WhatsApp variant served by the Flask app in `whatsapp/app.py`
(see also [whatsapp/README.md](whatsapp/README.md)).

### 1. Meta credentials

1. Create a [Meta Business Account](https://business.facebook.com/)
2. Create a WhatsApp Business app in the [Meta Developer Portal](https://developers.facebook.com/)
3. In the WhatsApp section copy the **permanent access token** and the **Phone number ID**
4. In `App Settings` -> `Basic` copy the **App Secret**

### 2. Environment variables

```bash
WHATSAPP_TOKEN=<permanent access token>
WHATSAPP_PHONE_ID=<phone number id>
WHATSAPP_VERIFY_TOKEN=<any random string you choose>
WHATSAPP_APP_SECRET=<Meta app secret>   # required: without it the webhook returns 403
```

`WHATSAPP_APP_SECRET` is not optional in production. Every `POST /webhook` is
authenticated with HMAC-SHA256 over the raw request body against Meta's
`X-Hub-Signature-256` header. If the variable is empty the service **fails closed** (403
on all POSTs), because without that check anyone who discovers the webhook URL can inject
fake messages and make the bot send WhatsApp messages to arbitrary numbers.

### 3. Running in production

Always use a real WSGI server - Flask's development server is single-threaded and would
make Meta retry the webhooks, producing duplicate replies:

```bash
gunicorn --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120 whatsapp.app:app
```

That is exactly what the `Procfile` `web:` process and the `whatsapp` service in
`docker-compose.yml` run. Locally, for quick tests:

```bash
python -m whatsapp.app
```

### 4. Webhook setup

1. The service must be reachable over HTTPS on a public domain
   (Meta accepts neither HTTP nor `localhost`; locally use `ngrok http 8080`)
2. In the Meta Developer Portal: `WhatsApp` -> `Configuration` -> `Webhook` -> `Edit`
   - **Callback URL**: `https://your-domain/webhook`
   - **Verify token**: the same value as `WHATSAPP_VERIFY_TOKEN`
3. Click `Verify and save` (Meta performs a `GET /webhook` with `hub.challenge`)
4. Subscribe to the `messages` event

### 5. Endpoints

| Method | Route | Description |
|--------|-------|-------------|
| `GET` | `/webhook` | Meta verification handshake (`hub.challenge`) |
| `POST` | `/webhook` | Inbound messages; requires a valid `X-Hub-Signature-256` |
| `GET` | `/health` | Health check. Returns `{"status": "ok", ...}` and the signature verification mode |

On platforms with HTTP health checks (Railway, Heroku, Kubernetes) point the health check
at `/health`.

## Data sources

- **STCP**: unofficial [stcp.pt](https://stcp.pt) API for real-time arrivals + static GTFS
- **Porto Metro**: GTFS from [opendata.porto.digital](https://opendata.porto.digital)
  (resolved dynamically via CKAN) + known frequencies
- **CP**: public suburban station and line data
- **Weather / events**: public APIs (see `bot/services/`)

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

## Project layout

See the [Portuguese README](README.md#estrutura-do-projeto) for the annotated tree.
