import logging

from core.config import RiskConfig
from core.models import Signal, Portfolio

logger = logging.getLogger("polybot.risk")


class RiskManager:
    def __init__(self, config: RiskConfig):
        self.config = config

    def evaluate(self, signal: Signal, portfolio: Portfolio) -> tuple[Signal | None, str]:
        """Evaluate a signal against risk limits. Returns (approved_signal, rejection_reason)."""
        bankroll = self.config.initial_bankroll_usd

        # 1. Daily loss limit
        if portfolio.daily_pnl < 0:
            max_loss = bankroll * self.config.daily_loss_limit_pct
            if abs(portfolio.daily_pnl) >= max_loss:
                reason = f"Daily loss limit hit: {portfolio.daily_pnl:.2f} (max: -{max_loss:.2f})"
                logger.warning(reason)
                return None, reason

        # 2. Max total exposure
        max_exposure = bankroll * self.config.max_total_exposure_pct
        if portfolio.total_exposure >= max_exposure:
            reason = f"Max exposure reached: {portfolio.total_exposure:.2f} (max: {max_exposure:.2f})"
            logger.warning(reason)
            return None, reason

        # 3. Per-market position limit
        max_per_market = bankroll * self.config.max_position_pct
        existing_in_market = sum(
            p.cost_basis
            for p in portfolio.positions
            if p.market_condition_id == signal.market.condition_id
        )
        remaining_market = max_per_market - existing_in_market
        if remaining_market <= 0:
            reason = f"Per-market limit reached for {signal.market.condition_id[:8]}"
            logger.warning(reason)
            return None, reason

        # 4. Single trade max
        max_single = bankroll * self.config.max_single_trade_pct
        allowed_size = min(signal.size_usd, max_single, remaining_market)

        # 5. Remaining exposure room
        exposure_room = max_exposure - portfolio.total_exposure
        allowed_size = min(allowed_size, exposure_room)

        # 5b. Kelly criterion sizing (opt-in)
        if self.config.use_kelly and signal.confidence > 0:
            kelly_size = self._kelly_size(signal, bankroll)
            if kelly_size is not None and kelly_size > 0:
                allowed_size = min(allowed_size, kelly_size)
                logger.debug(
                    "Kelly sizing: %.2f for confidence=%.2f, price=%.3f",
                    kelly_size, signal.confidence, signal.target_price,
                )

        # 6. Minimum order size
        if allowed_size < self.config.min_order_size_usd:
            reason = f"Order too small after limits: {allowed_size:.2f} < {self.config.min_order_size_usd}"
            logger.warning(reason)
            return None, reason

        # Return signal with potentially reduced size
        if allowed_size < signal.size_usd:
            logger.info(
                "Signal sized down: %.2f → %.2f for %s",
                signal.size_usd, allowed_size, signal.market.question[:40],
            )

        signal.size_usd = allowed_size
        return signal, ""

    def _kelly_size(self, signal: Signal, bankroll: float) -> float | None:
        """Compute quarter-Kelly position size. Returns dollar amount or None."""
        if signal.target_price <= 0 or signal.target_price >= 1:
            return None
        # Odds: what you win per dollar risked on a binary outcome
        odds = (1 - signal.target_price) / signal.target_price
        if odds <= 0:
            return None
        # Kelly fraction: f* = (p(1+b) - 1) / b
        # Using signal.confidence as proxy for estimated win probability
        kelly_f = (signal.confidence * (1 + odds) - 1) / odds
        if kelly_f <= 0:
            return None  # No edge according to Kelly
        # Quarter-Kelly for safety
        return kelly_f * 0.25 * bankroll
