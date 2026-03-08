import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
GTFS_DIR = DATA_DIR / "gtfs"

GTFS_METRO_URLS = [
    # Try newest first; Feb 2026 file is currently 0 bytes on the portal
    "https://opendata.porto.digital/dataset/"
    "15f22603-a216-492a-ab1c-40b1d8aa2f08/resource/"
    "a8375fac-8ded-4858-9c45-83f9be814900/download/"
    "horarios_gtfs_mdp_20_02_2026.zip",
    # Sept 2024 — latest working file (388 KB)
    "https://opendata.porto.digital/dataset/"
    "15f22603-a216-492a-ab1c-40b1d8aa2f08/resource/"
    "f592c53a-e669-4cac-9e28-ab84b87e7f6b/download/"
    "horarios_gtfs_09_09_2024.zip",
]
# Legacy single-URL alias
GTFS_METRO_URL = GTFS_METRO_URLS[0]

GTFS_STCP_URL = (
    "https://opendata.porto.digital/dataset/"
    "5275c986-592c-43f5-8f87-aabbd4e4f3a4/resource/"
    "c0a07e42-42b8-45cd-89ec-eb800334f81e/download/"
    "gtfs_static_03_03_2026.zip"
)

CACHE_TTL_SECONDS = 60
METRO_SCHEDULE_CACHE_TTL = 3600

# Metro do Porto lines
METRO_LINES = {
    "A": {"name": "Linha Azul", "emoji": "🔵", "route": "Senhor de Matosinhos ↔ Estádio do Dragão"},
    "B": {"name": "Linha Vermelha", "emoji": "🔴", "route": "Póvoa de Varzim ↔ Estádio do Dragão"},
    "C": {"name": "Linha Verde", "emoji": "🟢", "route": "ISMAI ↔ Campainha"},
    "D": {"name": "Linha Amarela", "emoji": "🟡", "route": "Sto. Ovídio ↔ Hospital de S. João"},
    "E": {"name": "Linha Violeta", "emoji": "🟣", "route": "Aeroporto ↔ Estádio do Dragão"},
    "F": {"name": "Linha Laranja", "emoji": "🟠", "route": "Fânzeres ↔ Senhora da Hora"},
}
