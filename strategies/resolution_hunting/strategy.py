import logging
from datetime import datetime

from core.config import ResolutionHuntingConfig
from core.models import Signal
from services.market_data import MarketDataService
from strategies.base import BaseStrategy
from strategies.resolution_hunting.market_scanner import MarketScanner

logger = logging.getLogger("polybot.resolution_hunting")


class ResolutionHuntingStrategy(BaseStrategy):
    name = "resolution_hunting"

    def __init__(self, config: ResolutionHuntingConfig, market_data: MarketDataService):
        self.config = config
        self.market_data = market_data
        self.scanner = MarketScanner(
            market_data=market_data,
            min_probability=config.min_probability,
            min_edge_pct=config.min_edge_pct,
            min_liquidity_usd=config.min_liquidity_usd,
            exclude_categories=config.exclude_categories,
        )

    async def scan(self) -> list[Signal]:
        candidates = self.scanner.scan()
        signals = []

        for c in candidates:
            size = min(
                self.config.max_per_market_usd,
                self.config.allocation_pct * 50,  # rough bankroll estimate
            )

            signal = Signal(
                strategy_name=self.name,
                market=c["market"],
                side="BUY",
                token_id=c["token_id"],
                target_price=c["price"],
                size_usd=size,
                confidence=min(c["price"], 0.99),  # near-certain = high confidence
                reason=f"Resolution hunt: {c['outcome']} @ {c['price']:.3f} (edge {c['edge']:.1%})",
            )
            signals.append(signal)

        if signals:
            logger.info("Generated %d resolution hunting signals", len(signals))
        return signals
