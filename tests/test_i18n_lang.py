"""Tests for language resolution, the /help command list and i18n integrity.

Covers the three bugs fixed in bot/utils/i18n.py:

1. The Auto/PT/EN choice in /settings was never read back when rendering.
2. Every non-PT locale fell back to Portuguese (bad for tourists).
3. /help only listed 7 of the ~20 registered commands.
"""

import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.utils.i18n import (
    TRANSLATIONS,
    clear_lang_cache,
    get_lang,
    locale_lang,
    resolve_lang,
    set_lang_preference,
    t,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MAIN_PY = PROJECT_ROOT / "bot" / "main.py"


def _make_update(user_id=4242, lang="pt"):
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_user.language_code = lang
    return update


@pytest.fixture(autouse=True)
def _clean_lang_cache():
    """Never leak a cached preference into another test."""
    clear_lang_cache()
    yield
    clear_lang_cache()


# ===========================================================================
# 1. Stored language setting is actually honoured
# ===========================================================================

class TestStoredLanguagePreference:

    @pytest.mark.asyncio
    async def test_stored_en_overrides_portuguese_telegram_locale(self):
        update = _make_update(user_id=1001, lang="pt")
        with patch("bot.database.get_user_settings",
                   new=AsyncMock(return_value={"language": "en"})):
            assert await resolve_lang(update) == "en"

    @pytest.mark.asyncio
    async def test_stored_en_gives_english_strings(self):
        """The whole point: an English string must actually come out."""
        update = _make_update(user_id=1002, lang="pt")
        with patch("bot.database.get_user_settings",
                   new=AsyncMock(return_value={"language": "en"})):
            lang = await resolve_lang(update)
        assert t("back", lang) == TRANSLATIONS["en"]["back"]
        assert t("back", lang) != TRANSLATIONS["pt"]["back"]

    @pytest.mark.asyncio
    async def test_stored_pt_overrides_english_telegram_locale(self):
        update = _make_update(user_id=1003, lang="en-GB")
        with patch("bot.database.get_user_settings",
                   new=AsyncMock(return_value={"language": "pt"})):
            assert await resolve_lang(update) == "pt"

    @pytest.mark.asyncio
    async def test_auto_falls_back_to_telegram_locale(self):
        with patch("bot.database.get_user_settings",
                   new=AsyncMock(return_value={"language": "auto"})):
            assert await resolve_lang(_make_update(user_id=1004, lang="en")) == "en"
            assert await resolve_lang(_make_update(user_id=1005, lang="pt")) == "pt"

    @pytest.mark.asyncio
    async def test_auto_with_french_locale_falls_back_to_english(self):
        with patch("bot.database.get_user_settings",
                   new=AsyncMock(return_value={"language": "auto"})):
            assert await resolve_lang(_make_update(user_id=1006, lang="fr")) == "en"

    @pytest.mark.asyncio
    async def test_resolve_lang_caches_so_sync_get_lang_honours_it(self):
        """Once resolved, every existing sync get_lang() call site follows."""
        update = _make_update(user_id=1007, lang="pt")
        # Before resolving, the sync helper only knows the Telegram locale.
        assert get_lang(update) == "pt"
        with patch("bot.database.get_user_settings",
                   new=AsyncMock(return_value={"language": "en"})):
            await resolve_lang(update)
        assert get_lang(update) == "en"

    @pytest.mark.asyncio
    async def test_db_read_happens_only_once_per_user(self):
        update = _make_update(user_id=1008, lang="pt")
        mock = AsyncMock(return_value={"language": "en"})
        with patch("bot.database.get_user_settings", new=mock):
            await resolve_lang(update)
            await resolve_lang(update)
            await resolve_lang(update)
        assert mock.await_count == 1

    @pytest.mark.asyncio
    async def test_database_failure_degrades_to_locale(self):
        update = _make_update(user_id=1009, lang="en")
        with patch("bot.database.get_user_settings",
                   new=AsyncMock(side_effect=RuntimeError("no pool"))):
            assert await resolve_lang(update) == "en"
        # and nothing was cached, so a later successful read still works
        with patch("bot.database.get_user_settings",
                   new=AsyncMock(return_value={"language": "pt"})):
            assert await resolve_lang(update) == "pt"

    @pytest.mark.asyncio
    async def test_missing_language_key_is_treated_as_auto(self):
        update = _make_update(user_id=1010, lang="en")
        with patch("bot.database.get_user_settings", new=AsyncMock(return_value={})):
            assert await resolve_lang(update) == "en"

    @pytest.mark.asyncio
    async def test_garbage_stored_value_falls_back_to_locale(self):
        update = _make_update(user_id=1011, lang="en")
        with patch("bot.database.get_user_settings",
                   new=AsyncMock(return_value={"language": "klingon"})):
            assert await resolve_lang(update) == "en"

    @pytest.mark.asyncio
    async def test_resolve_lang_without_user_uses_locale(self):
        update = MagicMock()
        update.effective_user = None
        assert await resolve_lang(update) == "pt"

    def test_set_lang_preference_write_through(self):
        update = _make_update(user_id=1012, lang="pt")
        set_lang_preference(1012, "en")
        assert get_lang(update) == "en"
        set_lang_preference(1012, "auto")
        assert get_lang(update) == "pt"

    def test_set_lang_preference_ignores_bad_input(self):
        update = _make_update(user_id=1013, lang="pt")
        set_lang_preference(1013, "en")
        set_lang_preference(1013, "nonsense")
        assert get_lang(update) == "pt"
        set_lang_preference("not-an-id", "en")  # must not raise

    def test_clear_lang_cache_single_user(self):
        update = _make_update(user_id=1014, lang="pt")
        set_lang_preference(1014, "en")
        assert get_lang(update) == "en"
        clear_lang_cache(1014)
        assert get_lang(update) == "pt"


# ===========================================================================
# 2. Non-Portuguese speakers must not get Portuguese
# ===========================================================================

class TestLocaleFallback:

    @pytest.mark.parametrize("code", ["fr", "fr-FR", "es", "es-ES", "de", "de-AT",
                                      "it", "nl", "ja", "zh-CN", "ru", "pl"])
    def test_non_portuguese_locale_gets_english(self, code):
        assert locale_lang(_make_update(lang=code)) == "en"
        assert get_lang(_make_update(lang=code)) == "en"

    @pytest.mark.parametrize("code", ["pt", "pt-PT", "pt-BR", "PT"])
    def test_portuguese_locale_gets_portuguese(self, code):
        assert locale_lang(_make_update(lang=code)) == "pt"
        assert get_lang(_make_update(lang=code)) == "pt"

    @pytest.mark.parametrize("code", ["en", "en-US", "en-GB", "EN"])
    def test_english_locale_gets_english(self, code):
        assert locale_lang(_make_update(lang=code)) == "en"
        assert get_lang(_make_update(lang=code)) == "en"

    def test_french_user_gets_english_strings_not_portuguese(self):
        lang = get_lang(_make_update(lang="fr"))
        assert t("back", lang) == TRANSLATIONS["en"]["back"]

    # --- backward compatibility of get_lang() -------------------------------

    def test_no_user_still_defaults_to_portuguese(self):
        update = MagicMock()
        update.effective_user = None
        assert get_lang(update) == "pt"

    def test_missing_locale_defaults_to_portuguese(self):
        update = MagicMock()
        update.effective_user.language_code = None
        assert get_lang(update) == "pt"

    def test_empty_locale_defaults_to_portuguese(self):
        update = MagicMock()
        update.effective_user.language_code = ""
        assert get_lang(update) == "pt"

    def test_non_string_locale_defaults_to_portuguese(self):
        """Unconfigured MagicMocks must not silently become English."""
        update = MagicMock()  # language_code is a MagicMock, not a str
        assert get_lang(update) == "pt"

    def test_get_lang_never_raises(self):
        for update in (MagicMock(), object(), None):
            try:
                assert get_lang(update) in TRANSLATIONS
            except Exception as err:  # pragma: no cover
                pytest.fail(f"get_lang raised {err!r}")


# ===========================================================================
# 3. /help must list every registered command
# ===========================================================================

def _registered_commands() -> set[str]:
    """Read the actual command registrations out of bot/main.py."""
    source = MAIN_PY.read_text(encoding="utf-8")
    return set(re.findall(r'CommandHandler\(\s*"([a-z_]+)"', source))


class TestHelpListsEveryCommand:

    def test_registration_scrape_is_sane(self):
        commands = _registered_commands()
        assert len(commands) >= 20
        assert {"bus", "metro", "comboios", "tourist"} <= commands

    @pytest.mark.parametrize("lang", ["pt", "en"])
    def test_help_mentions_every_registered_command(self, lang):
        help_text = t("help", lang)
        missing = sorted(
            cmd for cmd in _registered_commands()
            if not re.search(rf"/{cmd}\b", help_text)
        )
        assert not missing, f"{lang} help text omits: {missing}"

    @pytest.mark.parametrize("lang", ["pt", "en"])
    def test_help_previously_missing_commands_now_present(self, lang):
        help_text = t("help", lang)
        for cmd in ("comboios", "metrobus", "tourist", "commuter", "zonas",
                    "alertas", "acessibilidade", "meteo", "eventos", "fav",
                    "estacao", "route", "settings"):
            assert f"/{cmd}" in help_text, f"{lang}: /{cmd} missing from help"

    @pytest.mark.parametrize("lang", ["pt", "en"])
    def test_help_is_grouped_into_sections(self, lang):
        help_text = t("help", lang)
        expected = {
            "pt": ["*Transporte*", "*Planeamento*", "*Informação*", "*Pessoal*"],
            "en": ["*Transport*", "*Planning*", "*Information*", "*Personal*"],
        }[lang]
        for section in expected:
            assert section in help_text

    @pytest.mark.parametrize("lang", ["pt", "en"])
    def test_help_fits_in_a_telegram_message(self, lang):
        assert len(t("help", lang)) < 4096


# ===========================================================================
# 4. MarkdownV2 escaping
# ===========================================================================

# Characters Telegram requires to be escaped in MarkdownV2 body text.
# '*' and '_' are excluded here because they are the formatting markers; they
# are checked separately for balance.
MDV2_MUST_ESCAPE = set(".!()-+=#|>[]~{}")

NEW_KEYS = [
    "help",
    "cancel",
    "back_to_menu",
    "frequencies",
    "option_not_available",
    "zones_no_station_in_zone",
    "no_alerts_of_type",
    "alerts_source_unavailable",
    "stcp_data_unavailable",
    "data_estimated",
    "settings_notifications",
    "settings_notifications_on",
    "settings_notifications_off",
    "settings_pick_notifications",
    "notif_alert_title",
    "notif_commute_reminder",
    "error_generic",
]

# Keys that are only ever used as inline-button labels or as answerCallbackQuery
# toast text -- Telegram does not parse markdown in those, so they are plain.
PLAIN_TEXT_KEYS = {
    "cancel", "back_to_menu", "frequencies",
    "settings_notifications", "settings_notifications_on",
    "settings_notifications_off",
}


def _strip_placeholders_and_code(text: str) -> str:
    text = re.sub(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}", "X", text)
    return re.sub(r"`[^`]*`", "C", text)


def _unescaped_specials(text: str) -> list[str]:
    text = _strip_placeholders_and_code(text)
    found = []
    i = 0
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] in MDV2_MUST_ESCAPE:
            found.append(f"{text[i]!r} at {i}")
        i += 1
    return found


def _unescaped_count(text: str, char: str) -> int:
    text = _strip_placeholders_and_code(text)
    count = 0
    i = 0
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == char:
            count += 1
        i += 1
    return count


class TestMarkdownV2Escaping:

    @pytest.mark.parametrize("lang", ["pt", "en"])
    @pytest.mark.parametrize("key", [k for k in NEW_KEYS if k not in PLAIN_TEXT_KEYS])
    def test_new_strings_escape_reserved_characters(self, lang, key):
        problems = _unescaped_specials(TRANSLATIONS[lang][key])
        assert not problems, f"{lang}/{key} has unescaped MarkdownV2 chars: {problems}"

    @pytest.mark.parametrize("lang", ["pt", "en"])
    @pytest.mark.parametrize("key", NEW_KEYS)
    @pytest.mark.parametrize("marker", ["*", "_", "`"])
    def test_new_strings_have_balanced_markers(self, lang, key, marker):
        text = TRANSLATIONS[lang][key]
        if marker == "`":
            count = text.count("`")
        else:
            count = _unescaped_count(text, marker)
        assert count % 2 == 0, f"{lang}/{key}: odd number of {marker!r}"

    @pytest.mark.parametrize("lang", ["pt", "en"])
    def test_regression_message_body_keys_are_escaped(self, lang):
        """These keys are sent with parse_mode=MarkdownV2 and used to fail."""
        for key in ("bus_stop_usage", "metro_station_usage", "trains_station_usage",
                    "tourist_walk", "weather_disclaimer", "weather_tip_rain",
                    "weather_tip_nice", "weather_tip_hot", "weather_tip_cold"):
            problems = _unescaped_specials(TRANSLATIONS[lang][key])
            assert not problems, f"{lang}/{key}: {problems}"


# ===========================================================================
# 5. Dictionary integrity
# ===========================================================================

class TestTranslationIntegrity:

    def test_pt_and_en_have_identical_key_sets(self):
        pt_keys = set(TRANSLATIONS["pt"])
        en_keys = set(TRANSLATIONS["en"])
        assert not pt_keys - en_keys, f"missing EN: {sorted(pt_keys - en_keys)}"
        assert not en_keys - pt_keys, f"missing PT: {sorted(en_keys - pt_keys)}"

    def test_only_pt_and_en_exist(self):
        assert set(TRANSLATIONS) == {"pt", "en"}

    @pytest.mark.parametrize("key", NEW_KEYS)
    def test_new_keys_present_and_non_empty_in_both_languages(self, key):
        for lang in ("pt", "en"):
            value = TRANSLATIONS[lang].get(key)
            assert isinstance(value, str) and value.strip(), f"{lang}/{key}"
            assert t(key, lang) == value

    def test_new_keys_are_actually_translated(self):
        """PT and EN wording must differ for the prose keys."""
        for key in ("option_not_available", "zones_no_station_in_zone",
                    "no_alerts_of_type", "alerts_source_unavailable",
                    "stcp_data_unavailable", "data_estimated",
                    "notif_alert_title", "notif_commute_reminder", "help"):
            assert TRANSLATIONS["pt"][key] != TRANSLATIONS["en"][key], key

    def test_no_alerts_of_type_differs_from_no_alerts(self):
        """'no alerts of this type' must not claim everything is running fine."""
        for lang in ("pt", "en"):
            assert TRANSLATIONS[lang]["no_alerts_of_type"] != TRANSLATIONS[lang]["no_alerts"]

    def test_placeholders_match_across_languages(self):
        pattern = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
        for key, pt_value in TRANSLATIONS["pt"].items():
            en_value = TRANSLATIONS["en"][key]
            if not isinstance(pt_value, str) or not isinstance(en_value, str):
                continue
            assert set(pattern.findall(pt_value)) == set(pattern.findall(en_value)), key

    def test_all_values_are_strings(self):
        for lang in ("pt", "en"):
            for key, value in TRANSLATIONS[lang].items():
                assert isinstance(value, str), f"{lang}/{key} is {type(value)}"


class TestTranslateFallbackChain:

    def test_requested_language_wins(self):
        assert t("back", "en") == TRANSLATIONS["en"]["back"]

    def test_unknown_language_falls_back_to_portuguese(self):
        assert t("back", "fr") == TRANSLATIONS["pt"]["back"]
        assert t("back", "de") == TRANSLATIONS["pt"]["back"]

    def test_unknown_key_returns_the_key(self):
        assert t("totally_made_up_key", "pt") == "totally_made_up_key"
        assert t("totally_made_up_key", "en") == "totally_made_up_key"

    def test_no_arguments_beyond_key(self):
        assert t("back") == TRANSLATIONS["pt"]["back"]

    @pytest.mark.parametrize("lang", [None, 123, "", "xx", object(), ["pt"]])
    def test_weird_language_never_raises(self, lang):
        assert t("back", lang) == TRANSLATIONS["pt"]["back"]

    @pytest.mark.parametrize("key", [None, 123, "", "missing"])
    def test_weird_key_never_raises(self, key):
        assert isinstance(t(key, "pt"), str)

    def test_unhashable_key_never_raises(self):
        assert isinstance(t(["a", "b"], "pt"), str)
