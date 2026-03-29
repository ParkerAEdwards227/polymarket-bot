import logging

from core.config import ArbitrageConfig
from core.models import Signal
from services.market_data import MarketDataService
from strategies.base import BaseStrategy
from strategies.arbitrage.market_graph import MarketGraph

logger = logging.getLogger("polybot.arbitrage")


class ArbitrageStrategy(BaseStrategy):
    name = "arbitrage"

    def __init__(self, config: ArbitrageConfig, market_data: MarketDataService):
        self.config = config
        self.market_data = market_data
        self.graph = MarketGraph(min_spread_after_fees=config.min_spread_after_fees_pct)

    async def scan(self) -> list[Signal]:
        opportunities = self.graph.find_opportunities(self.market_data.markets)
        signals = []

        for opp in opportunities:
            if opp.relationship == "complementary":
                # Buy both YES and NO on the same market
                yes_price = opp.market_a.outcome_prices[0]
                no_price = opp.market_a.outcome_prices[1]
                size = min(self.config.max_per_pair_usd / 2, 10.0)

                # Signal to buy YES
                signals.append(Signal(
                    strategy_name=self.name,
                    market=opp.market_a,
                    side="BUY",
                    token_id=opp.market_a.yes_token_id,
                    target_price=yes_price,
                    size_usd=size,
                    confidence=min(opp.expected_profit_pct * 10, 0.95),
                    reason=f"Arb (complementary): {opp.description[:80]}",
                ))
                # Signal to buy NO
                signals.append(Signal(
                    strategy_name=self.name,
                    market=opp.market_a,
                    side="BUY",
                    token_id=opp.market_a.no_token_id,
                    target_price=no_price,
                    size_usd=size,
                    confidence=min(opp.expected_profit_pct * 10, 0.95),
                    reason=f"Arb (complementary): {opp.description[:80]}",
                ))

            elif opp.relationship == "temporal":
                # Sell the overpriced early market, buy the underpriced late market
                size = min(self.config.max_per_pair_usd / 2, 10.0)

                # Buy NO on the overpriced early market (betting it won't happen by early date)
                signals.append(Signal(
                    strategy_name=self.name,
                    market=opp.market_a,
                    side="BUY",
                    token_id=opp.market_a.no_token_id,
                    target_price=1.0 - opp.market_a.outcome_prices[0],
                    size_usd=size,
                    confidence=min(opp.expected_profit_pct * 10, 0.95),
                    reason=f"Arb (temporal short): {opp.description[:80]}",
                ))
                # Buy YES on the underpriced late market
                signals.append(Signal(
                    strategy_name=self.name,
                    market=opp.market_b,
                    side="BUY",
                    token_id=opp.market_b.yes_token_id,
                    target_price=opp.market_b.outcome_prices[0],
                    size_usd=size,
                    confidence=min(opp.expected_profit_pct * 10, 0.95),
                    reason=f"Arb (temporal long): {opp.description[:80]}",
                ))

        if signals:
            logger.info("Generated %d arbitrage signals", len(signals))
        return signals
