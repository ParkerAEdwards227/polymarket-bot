import logging

from core.models import Market
from services.market_data import MarketDataService

logger = logging.getLogger("polybot.resolution_hunting.scanner")


class MarketScanner:
    """Scans for near-certain markets that haven't fully priced in resolution."""

    def __init__(
        self,
        market_data: MarketDataService,
        min_probability: float = 0.93,
        min_edge_pct: float = 0.03,
        min_liquidity_usd: float = 100,
        exclude_categories: list[str] | None = None,
    ):
        self.market_data = market_data
        self.min_probability = min_probability
        self.min_edge_pct = min_edge_pct
        self.min_liquidity = min_liquidity_usd
        self.exclude_categories = [c.lower() for c in (exclude_categories or [])]

    def scan(self) -> list[dict]:
        """
        Find markets where one outcome is near-certain but priced below $1.

        Returns list of:
            {"market": Market, "token_id": str, "side": "BUY", "price": float, "edge": float}
        """
        candidates = []

        for market in self.market_data.markets:
            if not market.active:
                continue

            if market.category.lower() in self.exclude_categories:
                continue

            if market.liquidity < self.min_liquidity:
                continue

            yes_price, no_price = market.outcome_prices

            # Check YES side: high probability, buy YES cheap
            if yes_price >= self.min_probability:
                edge = 1.0 - yes_price
                if edge >= self.min_edge_pct:
                    candidates.append({
                        "market": market,
                        "token_id": market.yes_token_id,
                        "side": "BUY",
                        "price": yes_price,
                        "edge": edge,
                        "outcome": "YES",
                    })

            # Check NO side: low probability means NO is near-certain
            if no_price >= self.min_probability:
                edge = 1.0 - no_price
                if edge >= self.min_edge_pct:
                    candidates.append({
                        "market": market,
                        "token_id": market.no_token_id,
                        "side": "BUY",
                        "price": no_price,
                        "edge": edge,
                        "outcome": "NO",
                    })

        # Sort by edge (highest first)
        candidates.sort(key=lambda c: c["edge"], reverse=True)
        logger.info("Resolution scanner found %d candidates", len(candidates))
        return candidates
