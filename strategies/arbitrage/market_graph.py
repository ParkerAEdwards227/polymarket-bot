import logging
from dataclasses import dataclass

from core.models import Market

logger = logging.getLogger("polybot.arbitrage.graph")


@dataclass
class ArbitrageOpportunity:
    market_a: Market
    market_b: Market
    relationship: str  # "temporal", "complementary", "subset"
    expected_profit_pct: float
    description: str


class MarketGraph:
    """Builds relationships between markets to find logical arbitrage."""

    def __init__(self, min_spread_after_fees: float = 0.03):
        self.min_spread = min_spread_after_fees
        # Estimated max taker fee at worst case (50% probability)
        self.max_fee_rate = 0.015

    def find_opportunities(self, markets: list[Market]) -> list[ArbitrageOpportunity]:
        opportunities = []

        # Strategy 1: YES + NO mispricing within same market
        # YES + NO should sum to ~1.0 (minus spread)
        for market in markets:
            if not market.active:
                continue
            yes_p, no_p = market.outcome_prices
            total = yes_p + no_p
            if total < 1.0 - self.min_spread:
                # Can buy both sides for less than $1 → guaranteed profit
                profit = 1.0 - total - (self.max_fee_rate * 2)  # fees on both sides
                if profit > self.min_spread:
                    opportunities.append(ArbitrageOpportunity(
                        market_a=market,
                        market_b=market,
                        relationship="complementary",
                        expected_profit_pct=profit,
                        description=f"YES+NO={total:.3f} < 1.0, profit={profit:.1%}: {market.question[:60]}",
                    ))

        # Strategy 2: Temporal relationships (same entity, different dates)
        # Group markets by keyword similarity
        keyword_groups = self._group_by_keywords(markets)
        for group in keyword_groups.values():
            if len(group) < 2:
                continue
            temporal = self._find_temporal_arb(group)
            opportunities.extend(temporal)

        opportunities.sort(key=lambda o: o.expected_profit_pct, reverse=True)
        logger.info("Found %d arbitrage opportunities", len(opportunities))
        return opportunities

    def _group_by_keywords(self, markets: list[Market]) -> dict[str, list[Market]]:
        """Group markets that share key terms."""
        groups: dict[str, list[Market]] = {}
        for market in markets:
            if not market.active:
                continue
            # Extract entity/subject (simplified)
            words = market.question.lower().split()
            # Use first 3 significant words as key
            stopwords = {"will", "the", "a", "an", "be", "by", "in", "on", "?"}
            key_words = [w.strip("?.,!") for w in words if w not in stopwords][:3]
            key = " ".join(key_words)
            if key:
                groups.setdefault(key, []).append(market)
        return groups

    def _find_temporal_arb(self, markets: list[Market]) -> list[ArbitrageOpportunity]:
        """Find temporal inconsistencies: earlier deadline priced higher than later."""
        opps = []
        # Sort by end date
        dated = [(m, m.end_date) for m in markets if m.end_date]
        dated.sort(key=lambda x: x[1])

        for i in range(len(dated)):
            for j in range(i + 1, len(dated)):
                early_market, early_date = dated[i]
                late_market, late_date = dated[j]

                if early_date >= late_date:
                    continue

                early_yes = early_market.outcome_prices[0]
                late_yes = late_market.outcome_prices[0]

                # If "X by June" > "X by December", that's wrong
                # (earlier deadline should be <= later deadline probability)
                if early_yes > late_yes + self.min_spread:
                    spread = early_yes - late_yes
                    profit = spread - (self.max_fee_rate * 2)
                    if profit > self.min_spread:
                        opps.append(ArbitrageOpportunity(
                            market_a=early_market,
                            market_b=late_market,
                            relationship="temporal",
                            expected_profit_pct=profit,
                            description=(
                                f"Temporal: '{early_market.question[:30]}' ({early_yes:.0%}) > "
                                f"'{late_market.question[:30]}' ({late_yes:.0%}), spread={spread:.1%}"
                            ),
                        ))
        return opps
