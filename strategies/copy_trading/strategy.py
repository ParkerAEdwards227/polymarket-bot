import logging
from datetime import datetime

from core.config import CopyTradingConfig, BotConfig
from core.database import Database
from core.models import Market, Signal, Trade
from services.market_data import MarketDataService
from strategies.base import BaseStrategy
from strategies.copy_trading.whale_tracker import WhaleTracker
from strategies.copy_trading.wallet_scorer import WalletScorer

logger = logging.getLogger("polybot.copy_trading")


class CopyTradingStrategy(BaseStrategy):
    name = "copy_trading"

    def __init__(
        self,
        config: CopyTradingConfig,
        bot_config: BotConfig,
        market_data: MarketDataService,
        db: Database,
    ):
        self.config = config
        self.bot_config = bot_config
        self.market_data = market_data
        self.db = db

        self.tracker = WhaleTracker(
            polygon_rpc_url=bot_config.polygon_rpc_url,
            tracked_wallets=config.wallets,
            min_trade_usd=config.min_whale_trade_usd,
            max_delay_seconds=config.max_delay_seconds,
        )
        self.scorer = WalletScorer(db, config.wallets)

    async def on_startup(self):
        await self.scorer.initialize()
        logger.info(
            "Copy trading started — tracking %d wallets",
            len(self.config.wallets),
        )

    async def scan(self) -> list[Signal]:
        whale_trades = self.tracker.get_recent_trades()
        if not whale_trades:
            return []

        weights = await self.scorer.get_all_weights()
        signals = []

        for wt in whale_trades:
            weight = weights.get(wt.wallet, 0.1)
            allocation = self.config.allocation_pct * self.bot_config.risk.initial_bankroll_usd
            size = allocation * weight

            # Cap per-market
            max_market = allocation * self.config.max_per_market_pct
            size = min(size, max_market)

            if size < self.bot_config.risk.min_order_size_usd:
                continue

            # Try to find the market in our cached data
            market = self._find_market_for_token(wt.token_id)
            if not market:
                # Create a minimal market object
                market = Market(
                    condition_id=f"unknown_{wt.token_id[:16]}",
                    question=f"Whale trade on token {wt.token_id[:8]}",
                    slug="",
                    tokens=[{"token_id": wt.token_id, "outcome": "Unknown"}],
                    end_date="",
                    active=True,
                    outcome_prices=(wt.price, 1 - wt.price),
                )

            label = self.tracker.tracked.get(wt.wallet, {}).get("label", wt.wallet[:8])
            signal = Signal(
                strategy_name=self.name,
                market=market,
                side=wt.side,
                token_id=wt.token_id,
                target_price=wt.price,
                size_usd=size,
                confidence=weight,
                reason=f"Copy {label}: {wt.side} ${wt.size_usdc:.0f} @ {wt.price:.3f}",
            )
            signals.append(signal)

        if signals:
            logger.info("Generated %d copy trading signals", len(signals))
        return signals

    async def on_fill(self, trade: Trade):
        await self.scorer.record_whale_trade(
            address=trade.signal.reason.split("Copy ")[1].split(":")[0] if "Copy " in trade.signal.reason else "",
        )

    def _find_market_for_token(self, token_id: str) -> Market | None:
        """Search cached markets for one containing this token."""
        for market in self.market_data.markets:
            for t in market.tokens:
                if t["token_id"] == token_id:
                    return market
        return None
