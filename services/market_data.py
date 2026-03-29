import logging
from typing import Any

from core.models import Market
from services.gamma_client import GammaClient
from services.clob_client import PolymarketCLOB

logger = logging.getLogger("polybot.market_data")


class MarketDataService:
    """Aggregates data from Gamma (discovery) and CLOB (orderbooks/prices)."""

    def __init__(self, gamma: GammaClient, clob: PolymarketCLOB):
        self.gamma = gamma
        self.clob = clob
        self._markets: list[Market] = []

    async def refresh_markets(self) -> list[Market]:
        raw_markets = await self.gamma.get_all_active_markets()
        self._markets = [self.gamma.parse_market(m) for m in raw_markets]
        logger.info("Refreshed %d active markets", len(self._markets))
        return self._markets

    @property
    def markets(self) -> list[Market]:
        return self._markets

    def get_live_price(self, token_id: str, side: str = "BUY") -> float | None:
        """Get live price from CLOB (not cached)."""
        return self.clob.get_price(token_id, side)

    def get_midpoint(self, token_id: str) -> float | None:
        return self.clob.get_midpoint(token_id)

    def get_orderbook(self, token_id: str) -> dict:
        return self.clob.get_orderbook(token_id)

    def get_orderbook_depth(self, token_id: str, side: str = "bids") -> float:
        """Get total depth on one side of the book in USDC."""
        try:
            book = self.get_orderbook(token_id)
            orders = book.get(side, [])
            return sum(float(o.get("size", 0)) * float(o.get("price", 0)) for o in orders)
        except Exception:
            return 0.0
