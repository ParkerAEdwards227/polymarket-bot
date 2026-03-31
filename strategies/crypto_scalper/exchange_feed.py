import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime

import httpx

logger = logging.getLogger("polybot.crypto_scalper.feed")


@dataclass
class Candle:
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int


@dataclass
class ExchangeSnapshot:
    symbol: str  # "BTC", "ETH", "SOL"
    spot_price: float
    candles_1m: list[Candle]
    candles_5m: list[Candle]
    timestamp: datetime


class BinanceFeed:
    """Async Binance REST client for spot prices and candle data. No API key needed."""

    SYMBOL_MAP = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT"}

    def __init__(self, base_url: str = "https://api.binance.com"):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=10.0)
        self._cache: dict[str, tuple[float, ExchangeSnapshot]] = {}
        self._cache_ttl = 5  # seconds

    async def close(self):
        await self._client.aclose()

    async def get_snapshot(self, asset: str) -> ExchangeSnapshot | None:
        """Fetch spot price + 1m/5m candles for an asset."""
        # Check cache
        cached = self._cache.get(asset)
        if cached and time.time() - cached[0] < self._cache_ttl:
            return cached[1]

        symbol = self.SYMBOL_MAP.get(asset.upper())
        if not symbol:
            return None

        try:
            # Fetch all three in parallel
            spot_coro = self._fetch_spot(symbol)
            candles_1m_coro = self._fetch_candles(symbol, "1m", 30)
            candles_5m_coro = self._fetch_candles(symbol, "5m", 30)

            spot, c1m, c5m = await asyncio.gather(
                spot_coro, candles_1m_coro, candles_5m_coro,
                return_exceptions=True,
            )

            if isinstance(spot, Exception):
                logger.error("Spot fetch failed for %s: %s", asset, spot)
                return None

            snapshot = ExchangeSnapshot(
                symbol=asset.upper(),
                spot_price=spot,
                candles_1m=c1m if not isinstance(c1m, Exception) else [],
                candles_5m=c5m if not isinstance(c5m, Exception) else [],
                timestamp=datetime.utcnow(),
            )
            self._cache[asset] = (time.time(), snapshot)
            return snapshot

        except Exception as e:
            logger.error("Snapshot fetch failed for %s: %s", asset, e)
            return None

    async def get_all_snapshots(self, assets: list[str]) -> dict[str, ExchangeSnapshot]:
        """Fetch snapshots for multiple assets in parallel."""
        results = await asyncio.gather(
            *[self.get_snapshot(a) for a in assets],
            return_exceptions=True,
        )
        snapshots = {}
        for asset, result in zip(assets, results):
            if isinstance(result, ExchangeSnapshot):
                snapshots[asset] = result
        return snapshots

    async def _fetch_spot(self, symbol: str) -> float:
        resp = await self._client.get(
            f"{self.base_url}/api/v3/ticker/price",
            params={"symbol": symbol},
        )
        resp.raise_for_status()
        return float(resp.json()["price"])

    async def _fetch_candles(self, symbol: str, interval: str, limit: int) -> list[Candle]:
        resp = await self._client.get(
            f"{self.base_url}/api/v3/klines",
            params={"symbol": symbol, "interval": interval, "limit": limit},
        )
        resp.raise_for_status()
        candles = []
        for raw in resp.json():
            candles.append(Candle(
                open_time=int(raw[0]),
                open=float(raw[1]),
                high=float(raw[2]),
                low=float(raw[3]),
                close=float(raw[4]),
                volume=float(raw[5]),
                close_time=int(raw[6]),
            ))
        return candles
