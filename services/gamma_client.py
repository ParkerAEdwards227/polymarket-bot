import logging
import time
from typing import Any

import httpx

from core.models import Market

logger = logging.getLogger("polybot.gamma")


class GammaClient:
    """Read-only client for Polymarket Gamma API (market discovery)."""

    def __init__(self, host: str = "https://gamma-api.polymarket.com", cache_ttl: int = 300):
        self.host = host.rstrip("/")
        self.cache_ttl = cache_ttl
        self._cache: dict[str, tuple[float, Any]] = {}
        self._client = httpx.AsyncClient(timeout=30.0)

    async def close(self):
        await self._client.aclose()

    def _cache_get(self, key: str) -> Any | None:
        if key in self._cache:
            ts, data = self._cache[key]
            if time.time() - ts < self.cache_ttl:
                return data
            del self._cache[key]
        return None

    def _cache_set(self, key: str, data: Any):
        self._cache[key] = (time.time(), data)

    async def _get(self, path: str, params: dict | None = None) -> Any:
        url = f"{self.host}{path}"
        resp = await self._client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    async def get_markets(
        self,
        active: bool = True,
        closed: bool = False,
        limit: int = 100,
        offset: int = 0,
        order: str = "volume24hr",
        ascending: bool = False,
    ) -> list[dict]:
        params = {
            "active": str(active).lower(),
            "closed": str(closed).lower(),
            "limit": limit,
            "offset": offset,
            "order": order,
            "ascending": str(ascending).lower(),
        }
        return await self._get("/markets", params)

    async def get_all_active_markets(self, max_pages: int = 10) -> list[dict]:
        cache_key = "all_active"
        cached = self._cache_get(cache_key)
        if cached:
            return cached

        all_markets = []
        offset = 0
        limit = 100
        for _ in range(max_pages):
            batch = await self.get_markets(active=True, limit=limit, offset=offset)
            if not batch:
                break
            all_markets.extend(batch)
            if len(batch) < limit:
                break
            offset += limit

        self._cache_set(cache_key, all_markets)
        logger.info("Fetched %d active markets from Gamma", len(all_markets))
        return all_markets

    async def get_events(self, active: bool = True, limit: int = 100) -> list[dict]:
        params = {"active": str(active).lower(), "limit": limit}
        return await self._get("/events", params)

    async def get_market_by_condition_id(self, condition_id: str) -> dict | None:
        markets = await self._get("/markets", {"condition_id": condition_id})
        return markets[0] if markets else None

    def parse_market(self, raw: dict) -> Market:
        """Convert raw Gamma API response to Market model."""
        tokens = raw.get("tokens", [])
        prices = raw.get("outcomePrices", "")

        if isinstance(prices, str) and prices:
            try:
                import json
                price_list = json.loads(prices)
                outcome_prices = (float(price_list[0]), float(price_list[1]))
            except (json.JSONDecodeError, IndexError, ValueError):
                outcome_prices = (0.5, 0.5)
        elif isinstance(prices, list) and len(prices) >= 2:
            outcome_prices = (float(prices[0]), float(prices[1]))
        else:
            outcome_prices = (0.5, 0.5)

        token_list = []
        for t in tokens:
            token_list.append({
                "token_id": t.get("token_id", ""),
                "outcome": t.get("outcome", ""),
            })

        return Market(
            condition_id=raw.get("condition_id", ""),
            question=raw.get("question", ""),
            slug=raw.get("slug", ""),
            tokens=token_list,
            end_date=raw.get("end_date_iso", ""),
            active=raw.get("active", False),
            volume_24h=float(raw.get("volume24hr", 0) or 0),
            liquidity=float(raw.get("liquidity", 0) or 0),
            category=raw.get("category", ""),
            outcome_prices=outcome_prices,
        )
