"""Weather service for Porto - real-time data from Open-Meteo API."""

import logging
from datetime import datetime

import aiohttp

logger = logging.getLogger(__name__)

# Porto coordinates
_PORTO_LAT = 41.15
_PORTO_LON = -8.61

# Open-Meteo API (free, no API key required)
_API_URL = (
    "https://api.open-meteo.com/v1/forecast"
    f"?latitude={_PORTO_LAT}&longitude={_PORTO_LON}"
    "&current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m"
    "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset"
    "&timezone=Europe/Lisbon&forecast_days=1"
)

# WMO weather codes → description
_WMO_CODES = {
    0: ("Céu limpo", "Clear sky"),
    1: ("Quase limpo", "Mainly clear"),
    2: ("Parcialmente nublado", "Partly cloudy"),
    3: ("Nublado", "Overcast"),
    45: ("Nevoeiro", "Fog"),
    48: ("Nevoeiro gelado", "Depositing rime fog"),
    51: ("Chuvisco fraco", "Light drizzle"),
    53: ("Chuvisco", "Drizzle"),
    55: ("Chuvisco forte", "Dense drizzle"),
    61: ("Chuva fraca", "Slight rain"),
    63: ("Chuva moderada", "Moderate rain"),
    65: ("Chuva forte", "Heavy rain"),
    71: ("Neve fraca", "Slight snow"),
    73: ("Neve moderada", "Moderate snow"),
    75: ("Neve forte", "Heavy snow"),
    80: ("Aguaceiros fracos", "Slight showers"),
    81: ("Aguaceiros", "Moderate showers"),
    82: ("Aguaceiros fortes", "Violent showers"),
    95: ("Trovoada", "Thunderstorm"),
    96: ("Trovoada com granizo", "Thunderstorm with hail"),
    99: ("Trovoada forte com granizo", "Thunderstorm with heavy hail"),
}

# Cache to avoid hammering the API
_cached_weather: dict | None = None
_cache_time: datetime | None = None
_CACHE_TTL_SECONDS = 1800  # 30 minutes


async def get_weather_info() -> dict:
    """Get current weather data for Porto from Open-Meteo."""
    global _cached_weather, _cache_time

    now = datetime.now()
    if _cached_weather and _cache_time and (now - _cache_time).total_seconds() < _CACHE_TTL_SECONDS:
        return _cached_weather

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(_API_URL, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    logger.warning("Open-Meteo API returned %d", resp.status)
                    return _fallback_weather()
                data = await resp.json()
    except Exception:
        logger.exception("Failed to fetch weather from Open-Meteo")
        return _fallback_weather()

    try:
        current = data["current"]
        daily = data["daily"]

        weather_code = current.get("weather_code", 0)
        desc_pt, desc_en = _WMO_CODES.get(weather_code, ("Desconhecido", "Unknown"))

        temp_now = current.get("temperature_2m", 0)
        humidity = current.get("relative_humidity_2m", 0)
        wind = current.get("wind_speed_10m", 0)
        temp_min = daily["temperature_2m_min"][0]
        temp_max = daily["temperature_2m_max"][0]
        rain_prob = daily["precipitation_probability_max"][0]

        sunrise_raw = daily["sunrise"][0]  # "2026-03-08T07:05"
        sunset_raw = daily["sunset"][0]
        sunrise = sunrise_raw.split("T")[1] if "T" in sunrise_raw else sunrise_raw
        sunset = sunset_raw.split("T")[1] if "T" in sunset_raw else sunset_raw

        result = {
            "temp_now": round(temp_now),
            "temp_min": round(temp_min),
            "temp_max": round(temp_max),
            "rain_prob": rain_prob,
            "humidity": humidity,
            "wind": round(wind),
            "weather_code": weather_code,
            "description_pt": desc_pt,
            "description_en": desc_en,
            "sunrise": sunrise,
            "sunset": sunset,
            "emoji": _weather_emoji(weather_code),
        }

        _cached_weather = result
        _cache_time = now
        return result

    except (KeyError, IndexError, TypeError):
        logger.exception("Failed to parse Open-Meteo response")
        return _fallback_weather()


def get_transport_tip(lang: str = "pt") -> str:
    """Get weather-based transport advice (uses cached data or fallback)."""
    from bot.utils.i18n import t

    if _cached_weather:
        rain = _cached_weather.get("rain_prob", 0)
        temp_max = _cached_weather.get("temp_max", 20)
        temp_min = _cached_weather.get("temp_min", 10)
    else:
        month = datetime.now().month
        rain = 50 if month in (11, 12, 1, 2, 3) else 20
        temp_max = 20
        temp_min = 10

    if rain >= 50:
        return t("weather_tip_rain", lang)
    if temp_max >= 30:
        return t("weather_tip_hot", lang)
    if temp_min <= 3:
        return t("weather_tip_cold", lang)
    return t("weather_tip_nice", lang)


def _weather_emoji(code: int) -> str:
    """Return emoji for WMO weather code."""
    if code <= 1:
        return "\u2600\ufe0f"       # sun
    if code <= 3:
        return "\u26c5"             # sun behind cloud
    if code in (45, 48):
        return "\U0001f32b\ufe0f"   # fog
    if code in (51, 53, 55):
        return "\U0001f326\ufe0f"   # sun behind rain cloud
    if code in (61, 63, 65, 80, 81, 82):
        return "\U0001f327\ufe0f"   # cloud with rain
    if code in (71, 73, 75):
        return "\u2744\ufe0f"       # snowflake
    if code in (95, 96, 99):
        return "\u26a1"             # lightning
    return "\U0001f324\ufe0f"       # sun behind small cloud


def _fallback_weather() -> dict:
    """Fallback weather data based on monthly averages when API fails."""
    month = datetime.now().month
    _climate = {
        1: (5, 14, 65), 2: (5, 15, 60), 3: (7, 17, 50), 4: (9, 18, 50),
        5: (11, 20, 40), 6: (14, 24, 20), 7: (16, 27, 10), 8: (16, 27, 15),
        9: (14, 25, 30), 10: (11, 21, 50), 11: (8, 16, 60), 12: (5, 14, 65),
    }
    t_min, t_max, rain = _climate.get(month, (10, 20, 40))
    return {
        "temp_now": (t_min + t_max) // 2,
        "temp_min": t_min,
        "temp_max": t_max,
        "rain_prob": rain,
        "humidity": 70,
        "wind": 10,
        "weather_code": 2,
        "description_pt": "Dados indisponíveis (média mensal)",
        "description_en": "Data unavailable (monthly average)",
        "sunrise": "07:00",
        "sunset": "19:00",
        "emoji": "\U0001f324\ufe0f",
    }
