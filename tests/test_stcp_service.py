"""Tests for STCP bus service."""

import pytest

from bot.services.stcp import _status_emoji


class TestStatusEmoji:
    def test_on_time(self):
        assert _status_emoji("ON_TIME") == "\u2705"

    def test_delayed(self):
        assert _status_emoji("DELAYED") == "\u26a0\ufe0f"

    def test_early(self):
        assert _status_emoji("EARLY") == "\u23e9"

    def test_unknown(self):
        result = _status_emoji("SOMETHING_ELSE")
        assert result  # Should return some emoji

    def test_case_insensitive(self):
        assert _status_emoji("on_time") == "\u2705"
        assert _status_emoji("Delayed") == "\u26a0\ufe0f"


class TestCacheTTL:
    def test_cache_set_get(self):
        from bot.utils.cache import TTLCache
        cache = TTLCache(default_ttl=60)
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_cache_miss(self):
        from bot.utils.cache import TTLCache
        cache = TTLCache(default_ttl=60)
        assert cache.get("nonexistent") is None

    def test_cache_clear(self):
        from bot.utils.cache import TTLCache
        cache = TTLCache(default_ttl=60)
        cache.set("key1", "value1")
        cache.clear()
        assert cache.get("key1") is None

    def test_cache_custom_ttl(self):
        from bot.utils.cache import TTLCache
        cache = TTLCache(default_ttl=1)
        cache.set("key1", "value1", ttl=3600)
        assert cache.get("key1") == "value1"


# Integration tests (require network) - marked to skip in CI
@pytest.mark.skipif(
    True,  # Set to False to run integration tests
    reason="Integration tests require network access to stcp.pt"
)
class TestSTCPIntegration:
    @pytest.mark.asyncio
    async def test_search_stops(self):
        from bot.services.stcp import search_stops
        results = await search_stops("bolhao")
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_get_stop_real_time(self):
        from bot.services.stcp import get_stop_real_time
        data = await get_stop_real_time("BCM2")
        assert "stop_id" in data
        assert "arrivals" in data

    @pytest.mark.asyncio
    async def test_get_stop_info(self):
        from bot.services.stcp import get_stop_info
        data = await get_stop_info("BCM2")
        assert "stop_id" in data
        assert "routes" in data
