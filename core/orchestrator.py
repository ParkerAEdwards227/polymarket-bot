import asyncio
import logging
import signal as sig
from datetime import datetime

from core.config import BotConfig
from core.database import Database
from core.models import Portfolio, Position
from services.clob_client import PolymarketCLOB
from services.gamma_client import GammaClient
from services.market_data import MarketDataService
from services.order_executor import OrderExecutor
from services.risk_manager import RiskManager
from services.wallet import WalletManager
from services.telegram_bot import TelegramCommandCenter
from strategies.base import BaseStrategy

logger = logging.getLogger("polybot.orchestrator")


class Orchestrator:
    def __init__(self, config: BotConfig):
        self.config = config
        self.db = Database()
        self.gamma = GammaClient(host=config.gamma_host, cache_ttl=config.gamma_cache_ttl)
        self.clob = PolymarketCLOB(config)
        self.wallet = WalletManager(config)
        self.market_data = MarketDataService(self.gamma, self.clob)
        self.risk = RiskManager(config.risk)
        self.executor = OrderExecutor(self.clob, config)
        self.telegram = TelegramCommandCenter(config)
        self.telegram.set_orchestrator(self)
        self.strategies: list[BaseStrategy] = []
        self._running = False
        self.paused = False

    def register_strategy(self, strategy: BaseStrategy):
        self.strategies.append(strategy)
        logger.info("Registered strategy: %s", strategy.name)

    async def start(self):
        """Initialize all services and start the main loop."""
        await self.db.connect()

        # Connect services that need auth (skip if no keys)
        try:
            self.clob.connect()
        except Exception as e:
            logger.warning("CLOB connection skipped: %s", e)

        try:
            self.wallet.connect()
        except Exception as e:
            logger.warning("Wallet connection skipped: %s", e)

        await self.telegram.start()

        # Start strategies
        for strat in self.strategies:
            await strat.on_startup()

        # Log startup
        balance = self.wallet.get_usdc_balance() if self.wallet.address else 0
        logger.info(
            "Bot started — mode=%s, strategies=%d, balance=$%.2f",
            self.config.mode,
            len(self.strategies),
            balance,
        )
        await self.telegram.notify_startup(self.config.mode, balance)

        # Handle shutdown signals
        loop = asyncio.get_event_loop()
        for s in (sig.SIGINT, sig.SIGTERM):
            loop.add_signal_handler(s, lambda: asyncio.create_task(self.shutdown()))

        self._running = True
        await self._run_loop()

    async def _run_loop(self):
        while self._running:
            try:
                await self._tick()
            except Exception as e:
                logger.error("Tick failed: %s", e, exc_info=True)
                await self.telegram.notify_error(str(e))

            await asyncio.sleep(self.config.tick_interval_seconds)

    async def _tick(self):
        """One scan cycle: refresh data, collect signals, evaluate risk, execute."""
        if self.paused:
            return

        # Refresh market data
        await self.market_data.refresh_markets()

        # Build current portfolio state
        portfolio = await self._build_portfolio()

        # Collect signals from all strategies in parallel
        results = await asyncio.gather(
            *[strat.scan() for strat in self.strategies],
            return_exceptions=True,
        )

        all_signals = []
        for strat, result in zip(self.strategies, results):
            if isinstance(result, Exception):
                logger.error("Strategy %s scan failed: %s", strat.name, result)
                continue
            all_signals.extend(result)

        if not all_signals:
            return

        # Sort by confidence (highest first)
        all_signals.sort(key=lambda s: s.confidence, reverse=True)
        logger.info("Tick produced %d signals", len(all_signals))

        # Evaluate and execute sequentially (risk limits depend on order)
        for signal in all_signals:
            approved, rejection = self.risk.evaluate(signal, portfolio)
            await self.db.record_signal(signal, approved=approved is not None, rejection_reason=rejection)

            if approved is None:
                logger.debug("Signal rejected: %s — %s", signal.reason[:40], rejection)
                continue

            # Determine order type
            use_market = (
                signal.strategy_name == "copy_trading"
                and self.config.copy_trading.use_market_orders
            )
            trade = await self.executor.execute(approved, use_market_order=use_market)

            # Record and notify
            await self.db.record_trade(trade)
            if trade.status in ("filled", "dry_run"):
                await self._update_portfolio_from_trade(trade, portfolio)
                await self.telegram.notify_trade(trade)

                # Notify strategy
                strategy = next(
                    (s for s in self.strategies if s.name == trade.signal.strategy_name),
                    None,
                )
                if strategy:
                    await strategy.on_fill(trade)

    async def _build_portfolio(self) -> Portfolio:
        balance = self.wallet.get_usdc_balance() if self.wallet.address else self.config.risk.initial_bankroll_usd
        db_positions = await self.db.get_positions()
        positions = [
            Position(
                market_condition_id=p["market_condition_id"],
                token_id=p["token_id"],
                size=p["size"],
                avg_entry_price=p["avg_entry_price"],
            )
            for p in db_positions
        ]

        daily = await self.db.get_daily_pnl()
        daily_pnl = daily["realized_pnl"] if daily else 0.0

        return Portfolio(balance_usd=balance, positions=positions, daily_pnl=daily_pnl)

    async def _update_portfolio_from_trade(self, trade, portfolio: Portfolio):
        """Update position tracking after a fill."""
        if trade.signal.side == "BUY" and trade.fill_size > 0:
            # Find or create position
            existing = next(
                (p for p in portfolio.positions
                 if p.market_condition_id == trade.signal.market.condition_id
                 and p.token_id == trade.signal.token_id),
                None,
            )
            if existing:
                total_cost = existing.avg_entry_price * existing.size + trade.fill_price * trade.fill_size
                new_size = existing.size + trade.fill_size
                new_avg = total_cost / new_size if new_size > 0 else 0
            else:
                new_size = trade.fill_size
                new_avg = trade.fill_price

            await self.db.update_position(
                trade.signal.market.condition_id,
                trade.signal.token_id,
                new_size,
                new_avg,
            )

    async def shutdown(self):
        logger.info("Shutting down...")
        self._running = False

        # Cancel open orders in live mode
        if self.config.mode == "live":
            try:
                self.clob.cancel_all_orders()
                logger.info("Cancelled all open orders")
            except Exception as e:
                logger.error("Failed to cancel orders: %s", e)

        for strat in self.strategies:
            await strat.on_shutdown()

        await self.telegram.notify_shutdown()
        await self.telegram.stop()
        await self.gamma.close()
        await self.db.close()
        logger.info("Shutdown complete")
