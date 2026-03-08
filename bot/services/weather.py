"""Weather service for Porto - based on monthly climate averages."""

from datetime import datetime

# Porto monthly climate data (averages)
PORTO_CLIMATE: dict[int, dict] = {
    1: {"temp_min": 5, "temp_max": 14, "rain_prob": 65, "description_pt": "Fresco e chuvoso", "description_en": "Cool and rainy", "sunrise": "07:55", "sunset": "17:30"},
    2: {"temp_min": 5, "temp_max": 15, "rain_prob": 60, "description_pt": "Fresco e chuvoso", "description_en": "Cool and rainy", "sunrise": "07:30", "sunset": "18:05"},
    3: {"temp_min": 7, "temp_max": 17, "rain_prob": 50, "description_pt": "Ameno", "description_en": "Mild", "sunrise": "06:45", "sunset": "18:40"},
    4: {"temp_min": 9, "temp_max": 18, "rain_prob": 50, "description_pt": "Ameno e variável", "description_en": "Mild and variable", "sunrise": "06:50", "sunset": "20:15"},
    5: {"temp_min": 11, "temp_max": 20, "rain_prob": 40, "description_pt": "Agradável", "description_en": "Pleasant", "sunrise": "06:15", "sunset": "20:50"},
    6: {"temp_min": 14, "temp_max": 24, "rain_prob": 20, "description_pt": "Quente e seco", "description_en": "Warm and dry", "sunrise": "06:05", "sunset": "21:15"},
    7: {"temp_min": 16, "temp_max": 27, "rain_prob": 10, "description_pt": "Quente e seco", "description_en": "Hot and dry", "sunrise": "06:15", "sunset": "21:10"},
    8: {"temp_min": 16, "temp_max": 27, "rain_prob": 15, "description_pt": "Quente", "description_en": "Hot", "sunrise": "06:45", "sunset": "20:40"},
    9: {"temp_min": 14, "temp_max": 25, "rain_prob": 30, "description_pt": "Agradável", "description_en": "Pleasant", "sunrise": "07:15", "sunset": "19:50"},
    10: {"temp_min": 11, "temp_max": 21, "rain_prob": 50, "description_pt": "Ameno e chuvoso", "description_en": "Mild and rainy", "sunrise": "07:45", "sunset": "18:55"},
    11: {"temp_min": 8, "temp_max": 16, "rain_prob": 60, "description_pt": "Fresco e chuvoso", "description_en": "Cool and rainy", "sunrise": "07:20", "sunset": "17:25"},
    12: {"temp_min": 5, "temp_max": 14, "rain_prob": 65, "description_pt": "Frio e chuvoso", "description_en": "Cold and rainy", "sunrise": "07:50", "sunset": "17:15"},
}


def get_weather_info() -> dict:
    """Get current month's climate data plus transport tips."""
    month = datetime.now().month
    climate = PORTO_CLIMATE[month]
    return {
        "month": month,
        "temp_min": climate["temp_min"],
        "temp_max": climate["temp_max"],
        "rain_prob": climate["rain_prob"],
        "description_pt": climate["description_pt"],
        "description_en": climate["description_en"],
        "sunrise": climate["sunrise"],
        "sunset": climate["sunset"],
        "emoji": get_weather_emoji(month),
    }


def get_transport_tip(lang: str = "pt") -> str:
    """Get weather-based transport advice string."""
    month = datetime.now().month
    climate = PORTO_CLIMATE[month]
    rain_prob = climate["rain_prob"]
    temp_max = climate["temp_max"]
    temp_min = climate["temp_min"]

    if rain_prob >= 50:
        key = "weather_tip_rain"
    elif temp_max >= 27:
        key = "weather_tip_hot"
    elif temp_min <= 5:
        key = "weather_tip_cold"
    else:
        key = "weather_tip_nice"

    # Import here to avoid circular imports
    from bot.utils.i18n import t
    return t(key, lang)


def get_weather_emoji(month: int) -> str:
    """Return appropriate weather emoji for the month."""
    if month in (6, 7, 8):
        return "\u2600\ufe0f"   # sun
    if month in (12, 1, 2):
        return "\U0001f327\ufe0f"  # cloud with rain
    if month in (3, 4, 5):
        return "\U0001f324\ufe0f"  # sun behind small cloud
    # 9, 10, 11
    return "\u26c5"  # sun behind cloud
