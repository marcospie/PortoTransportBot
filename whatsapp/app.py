"""WhatsApp bot for Porto Transport using Meta Cloud API.

Setup:
1. Create a Meta Business account and WhatsApp Business app
2. Get your WHATSAPP_TOKEN and WHATSAPP_PHONE_ID from Meta Dashboard
3. Set WHATSAPP_VERIFY_TOKEN for webhook verification
4. Set these in .env file
5. Run: python -m whatsapp.app

Webhook URL: https://your-domain/webhook
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, request, jsonify
import requests

# Add parent dir to path so we can import bot services
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

from bot.services import stcp
from bot.services.metro import search_stations, get_next_departures, METRO_LINES

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID", "")
WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "porto-transport-bot")
GRAPH_API_URL = f"https://graph.facebook.com/v21.0/{WHATSAPP_PHONE_ID}/messages"

# Simple in-memory session state
_sessions: dict[str, dict] = {}


@app.route("/webhook", methods=["GET"])
def verify_webhook():
    """Handle webhook verification from Meta."""
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == WHATSAPP_VERIFY_TOKEN:
        logger.info("Webhook verified")
        return challenge, 200
    return "Forbidden", 403


@app.route("/webhook", methods=["POST"])
def handle_webhook():
    """Handle incoming WhatsApp messages."""
    data = request.get_json()

    if not data:
        return "OK", 200

    try:
        entries = data.get("entry", [])
        for entry in entries:
            changes = entry.get("changes", [])
            for change in changes:
                value = change.get("value", {})
                messages = value.get("messages", [])
                for msg in messages:
                    _process_message(msg)
    except Exception:
        logger.exception("Error processing webhook")

    return "OK", 200


def _process_message(msg: dict) -> None:
    """Process a single incoming message."""
    msg_type = msg.get("type", "")
    sender = msg.get("from", "")

    if not sender:
        return

    if msg_type == "text":
        text = msg.get("text", {}).get("body", "").strip()
        asyncio.run(_handle_text_message(sender, text))
    elif msg_type == "interactive":
        interactive = msg.get("interactive", {})
        if interactive.get("type") == "button_reply":
            button_id = interactive.get("button_reply", {}).get("id", "")
            asyncio.run(_handle_button_reply(sender, button_id))
        elif interactive.get("type") == "list_reply":
            row_id = interactive.get("list_reply", {}).get("id", "")
            asyncio.run(_handle_list_reply(sender, row_id))
    elif msg_type == "location":
        location = msg.get("location", {})
        lat = location.get("latitude")
        lon = location.get("longitude")
        if lat and lon:
            asyncio.run(_handle_location(sender, lat, lon))


async def _handle_text_message(sender: str, text: str) -> None:
    """Handle a text message from WhatsApp."""
    text_lower = text.lower()

    # Commands
    if text_lower in ("ola", "olá", "oi", "hi", "hello", "menu", "início", "inicio"):
        _send_main_menu(sender)
        return

    if text_lower == "ajuda" or text_lower == "help":
        _send_help(sender)
        return

    # Check if it looks like a stop code
    if len(text) <= 6 and any(c.isdigit() for c in text):
        stop_id = text.upper()
        data = await stcp.get_stop_real_time(stop_id)
        if data["arrivals"] or data["stop_name"] != stop_id:
            _send_bus_arrivals(sender, stop_id, data)
            return

    # Try metro station search
    stations = search_stations(text)
    if stations:
        if len(stations) == 1:
            _send_metro_departures(sender, stations[0])
        else:
            _send_station_list(sender, text, stations[:10])
        return

    # Try bus stop search
    stops = await stcp.search_stops(text)
    if stops:
        _send_stop_list(sender, text, stops[:10])
        return

    # Nothing found
    _send_text(sender,
        f"\U0001f914 Não encontrei resultados para \"{text}\".\n\n"
        "Tenta:\n"
        "\u2022 Nome de paragem STCP (ex: Bolhão)\n"
        "\u2022 Código de paragem (ex: BCM2)\n"
        "\u2022 Nome de estação de metro (ex: Trindade)\n\n"
        "Envia *menu* para ver opções.")


async def _handle_button_reply(sender: str, button_id: str) -> None:
    """Handle interactive button reply."""
    if button_id == "menu":
        _send_main_menu(sender)
    elif button_id == "bus_search":
        _send_text(sender, "\U0001f50d Envia o nome ou código da paragem.\n\nExemplo: Bolhão, BCM2")
    elif button_id == "metro_search":
        _send_text(sender, "\U0001f50d Envia o nome da estação de metro.\n\nExemplo: Trindade, Bolhão")
    elif button_id.startswith("stop_"):
        stop_id = button_id[5:]
        data = await stcp.get_stop_real_time(stop_id)
        _send_bus_arrivals(sender, stop_id, data)
    elif button_id.startswith("station_"):
        station_name = button_id[8:]
        stations = search_stations(station_name)
        if stations:
            _send_metro_departures(sender, stations[0])


async def _handle_list_reply(sender: str, row_id: str) -> None:
    """Handle interactive list reply."""
    if row_id.startswith("stop_"):
        stop_id = row_id[5:]
        data = await stcp.get_stop_real_time(stop_id)
        _send_bus_arrivals(sender, stop_id, data)
    elif row_id.startswith("station_"):
        station_name = row_id[8:]
        stations = search_stations(station_name)
        if stations:
            _send_metro_departures(sender, stations[0])


async def _handle_location(sender: str, lat: float, lon: float) -> None:
    """Handle location message - find nearby stops and stations."""
    from bot.services.metro import get_nearby_stations

    # Search nearby
    nearby_stations = get_nearby_stations(lat, lon, radius_km=0.75)
    nearby_stops = await stcp.search_nearby_stops(lat, lon, radius_km=0.4)

    lines = ["\U0001f4cd *Transportes perto de ti:*\n"]

    if nearby_stations:
        lines.append("\U0001f687 *Metro:*")
        for s in nearby_stations[:3]:
            emojis = " ".join(l["emoji"] for l in s.get("lines", []))
            lines.append(f"  \u2022 {s['name']} ({s['distance_m']}m) {emojis}")
        lines.append("")

    if nearby_stops:
        lines.append("\U0001f68c *Autocarros:*")
        for s in nearby_stops[:3]:
            lines.append(f"  \u2022 {s['name']} ({s['distance_m']}m)")
        lines.append("")

    if not nearby_stations and not nearby_stops:
        lines.append("Nenhum transporte encontrado perto de ti.")

    _send_text(sender, "\n".join(lines))


# --- Message sending helpers ---

def _send_text(to: str, text: str) -> None:
    """Send a plain text message."""
    _api_call({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text},
    })


def _send_main_menu(to: str) -> None:
    """Send main menu with interactive buttons."""
    _api_call({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": (
                    "\U0001f68d *Porto Transport Bot*\n\n"
                    "Bem-vindo! Escolhe uma opção ou envia "
                    "diretamente o nome/código de uma paragem."
                ),
            },
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "bus_search", "title": "\U0001f68c Autocarros"}},
                    {"type": "reply", "reply": {"id": "metro_search", "title": "\U0001f687 Metro"}},
                    {"type": "reply", "reply": {"id": "help", "title": "\u2139\ufe0f Ajuda"}},
                ],
            },
        },
    })


def _send_help(to: str) -> None:
    """Send help message."""
    _send_text(to,
        "\u2139\ufe0f *Como usar o Porto Transport Bot*\n\n"
        "Envia uma destas opções:\n\n"
        "\U0001f50d *Nome de paragem* \u2192 pesquisa paragens STCP\n"
        "   Exemplo: Bolhão, Casa da Música\n\n"
        "\U0001f522 *Código de paragem* \u2192 horários em tempo real\n"
        "   Exemplo: BCM2, TRD1\n\n"
        "\U0001f687 *Nome de estação* \u2192 horários do metro\n"
        "   Exemplo: Trindade, Aliados\n\n"
        "\U0001f4cd *Localização* \u2192 transportes perto de ti\n"
        "   Partilha a tua localização\n\n"
        "\U0001f4dd *menu* \u2192 ver menu principal\n\n"
        "\U0001f4a1 Dica: Basta escrever o nome da paragem ou "
        "estação para ver os horários!"
    )


def _send_bus_arrivals(to: str, stop_id: str, data: dict) -> None:
    """Send bus arrival information."""
    stop_name = data.get("stop_name", stop_id)
    arrivals = data.get("arrivals", [])

    lines = [f"\U0001f68f *{stop_name}* ({stop_id})\n"]

    if not arrivals:
        lines.append("Sem autocarros previstos na próxima hora.")
    else:
        for a in arrivals[:8]:
            line_num = a.get("line", "?")
            dest = a.get("destination", "?")
            time_str = a.get("time", "?")
            lines.append(f"\U0001f68c *{line_num}* \u2192 {dest}")
            lines.append(f"     \u23f1 {time_str}")

        from datetime import datetime
        lines.append(f"\n_Atualizado às {datetime.now().strftime('%H:%M')}_")

    _send_text(to, "\n".join(lines))


def _send_metro_departures(to: str, station: dict) -> None:
    """Send metro departure information."""
    name = station["name"]
    line_emojis = " ".join(l["emoji"] for l in station.get("lines", []))

    departures = get_next_departures(name, count=5)

    lines = [f"\U0001f687 *{name}*", f"{line_emojis}\n"]

    if not departures:
        lines.append("Sem informação de horários.")
    elif departures[0].get("direction") == "Serviço encerrado":
        lines.append("\U0001f319 Serviço encerrado.")
        lines.append(f"Funcionamento: {departures[0].get('time', '06:00 - 01:00')}")
    else:
        for dep in departures:
            direction = dep.get("direction", "?")
            time_str = dep.get("time", "?")
            lines.append(f"*{direction}* \u2014 {time_str}")

        if any(d.get("estimated") for d in departures):
            lines.append("\n\u26a0\ufe0f _Tempos estimados com base nas frequências_")

        from datetime import datetime
        lines.append(f"\n_Atualizado às {datetime.now().strftime('%H:%M')}_")

    _send_text(to, "\n".join(lines))


def _send_stop_list(to: str, query: str, stops: list[dict]) -> None:
    """Send a list of bus stops as interactive list."""
    rows = []
    for stop in stops[:10]:
        stop_id = stop.get("code", stop.get("stop_id", ""))
        name = stop.get("name", "")
        rows.append({
            "id": f"stop_{stop_id}",
            "title": f"\U0001f68c {name}"[:24],
            "description": f"Paragem {stop_id}",
        })

    _api_call({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": f"\U0001f50d Resultados para \"{query}\":"},
            "action": {
                "button": "Ver paragens",
                "sections": [
                    {
                        "title": "Paragens encontradas",
                        "rows": rows,
                    },
                ],
            },
        },
    })


def _send_station_list(to: str, query: str, stations: list[dict]) -> None:
    """Send a list of metro stations as interactive list."""
    rows = []
    for station in stations[:10]:
        name = station["name"]
        line_emojis = " ".join(l["emoji"] for l in station.get("lines", []))
        rows.append({
            "id": f"station_{name}",
            "title": f"\U0001f687 {name}"[:24],
            "description": line_emojis,
        })

    _api_call({
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": f"\U0001f50d Resultados para \"{query}\":"},
            "action": {
                "button": "Ver estações",
                "sections": [
                    {
                        "title": "Estações encontradas",
                        "rows": rows,
                    },
                ],
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


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok", "service": "porto-transport-whatsapp"})


if __name__ == "__main__":
    port = int(os.getenv("WHATSAPP_PORT", "8080"))
    logger.info("Starting WhatsApp bot on port %d", port)
    app.run(host="0.0.0.0", port=port)
