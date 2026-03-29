import logging
from datetime import datetime

from core.config import BotConfig
from core.models import Signal, Trade
from services.clob_client import PolymarketCLOB

logger = logging.getLogger("polybot.executor")


class OrderExecutor:
    def __init__(self, clob: PolymarketCLOB, config: BotConfig):
        self.clob = clob
        self.config = config

    async def execute(self, signal: Signal, use_market_order: bool = False) -> Trade:
        if self.config.mode == "dry_run":
            return self._simulate(signal)
        return self._execute_live(signal, use_market_order)

    def _simulate(self, signal: Signal) -> Trade:
        """Simulate a trade at the target price."""
        shares = signal.size_usd / signal.target_price if signal.target_price > 0 else 0
        logger.info(
            "[DRY RUN] %s %s %.2f USDC @ %.4f (%s) — %s",
            signal.side,
            signal.token_id[:8],
            signal.size_usd,
            signal.target_price,
            signal.strategy_name,
            signal.reason[:60],
        )
        return Trade(
            signal=signal,
            order_id="dry_run",
            status="dry_run",
            fill_price=signal.target_price,
            fill_size=shares,
            fees=0.0,
            timestamp=datetime.utcnow(),
        )

    def _execute_live(self, signal: Signal, use_market_order: bool = False) -> Trade:
        """Execute a real trade via CLOB."""
        try:
            shares = signal.size_usd / signal.target_price if signal.target_price > 0 else 0

            if use_market_order:
                result = self.clob.create_and_post_market_order(
                    token_id=signal.token_id,
                    amount=shares,
                    side=signal.side,
                )
            else:
                result = self.clob.create_and_post_limit_order(
                    token_id=signal.token_id,
                    price=signal.target_price,
                    size=shares,
                    side=signal.side,
                )

            order_id = result.get("orderID", "unknown")
            status = "pending" if not use_market_order else "filled"

            logger.info(
                "[LIVE] %s %s %.2f USDC @ %.4f → order %s (%s)",
                signal.side, signal.token_id[:8],
                signal.size_usd, signal.target_price,
                order_id, signal.strategy_name,
            )

            # Estimate taker fee: fee_rate = base_rate * (1 - |2*price - 1|)
            # Max ~1.5% at 50% probability, 0% at extremes
            fee_rate = 0.015 * (1 - abs(2 * signal.target_price - 1))
            fees = signal.size_usd * fee_rate if use_market_order else 0.0

            return Trade(
                signal=signal,
                order_id=order_id,
                status=status,
                fill_price=signal.target_price,
                fill_size=shares,
                fees=fees,
                timestamp=datetime.utcnow(),
            )

        except Exception as e:
            logger.error("Order execution failed: %s", e)
            return Trade(
                signal=signal,
                order_id="error",
                status="cancelled",
                fill_price=0.0,
                fill_size=0.0,
                fees=0.0,
                timestamp=datetime.utcnow(),
            )
