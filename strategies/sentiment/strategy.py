import logging

from core.config import SentimentConfig, BotConfig
from core.models import Signal
from services.market_data import MarketDataService
from strategies.base import BaseStrategy
from strategies.sentiment.news_fetcher import NewsFetcher
from strategies.sentiment.llm_analyzer import LLMAnalyzer

logger = logging.getLogger("polybot.sentiment")


class SentimentStrategy(BaseStrategy):
    name = "sentiment"

    def __init__(self, config: SentimentConfig, bot_config: BotConfig, market_data: MarketDataService):
        self.config = config
        self.bot_config = bot_config
        self.market_data = market_data
        self.news = NewsFetcher(
            api_key=bot_config.newsapi_key,
            categories=config.categories,
            poll_interval=config.newsapi_poll_interval,
        )
        self.llm = LLMAnalyzer(
            api_key=bot_config.anthropic_api_key,
            model=config.claude_model,
        )

    async def scan(self) -> list[Signal]:
        signals = []

        # Get general headlines
        headlines = await self.news.fetch_headlines()
        headline_texts = [h.title for h in headlines]

        if not headline_texts:
            return signals

        # Analyze top markets by volume that match our categories
        markets = self.market_data.markets
        # Focus on higher-volume markets to reduce API calls
        markets_to_analyze = sorted(markets, key=lambda m: m.volume_24h, reverse=True)[:20]

        for market in markets_to_analyze:
            if not market.active:
                continue

            yes_price = market.outcome_prices[0]
            if yes_price <= 0.05 or yes_price >= 0.95:
                # Already near-certain, skip (resolution hunting handles these)
                continue

            # Get market-specific headlines
            keywords = self.news.extract_keywords(market.question)
            relevant = [h for h in headline_texts if any(k in h.lower() for k in keywords.split()[:3])]

            if not relevant:
                continue

            # Ask LLM for probability estimate
            estimate = await self.llm.assess_probability(
                market_question=market.question,
                current_price=yes_price,
                headlines=relevant,
            )

            if not estimate:
                continue

            if estimate.confidence < self.config.min_confidence:
                continue

            edge = estimate.probability - yes_price

            if abs(edge) < self.config.min_edge_pct:
                continue

            # Determine trade direction
            if edge > 0:
                # LLM thinks YES is underpriced
                token_id = market.yes_token_id
                side = "BUY"
                price = yes_price
            else:
                # LLM thinks NO is underpriced
                token_id = market.no_token_id
                side = "BUY"
                price = market.outcome_prices[1]

            size = min(
                self.config.max_per_market_usd,
                self.config.allocation_pct * self.bot_config.risk.initial_bankroll_usd,
            )

            signal = Signal(
                strategy_name=self.name,
                market=market,
                side=side,
                token_id=token_id,
                target_price=price,
                size_usd=size,
                confidence=estimate.confidence * min(abs(edge) / 0.10, 1.0),
                reason=f"Sentiment: edge {edge:+.1%}, LLM={estimate.probability:.0%} vs mkt={yes_price:.0%} — {estimate.reasoning[:60]}",
            )
            signals.append(signal)

        if signals:
            logger.info("Generated %d sentiment signals", len(signals))
        return signals
