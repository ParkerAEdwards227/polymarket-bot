import asyncio
import logging
from datetime import datetime

from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes

from core.config import BotConfig
from core.models import Trade

logger = logging.getLogger("polybot.telegram")


class TelegramCommandCenter:
    """Two-way Telegram bot: receives commands + sends notifications."""

    def __init__(self, config: BotConfig):
        self.config = config
        self._app: Application | None = None
        self._bot: Bot | None = None
        self._orchestrator = None  # Set via set_orchestrator()
        self.enabled = config.notifications.telegram_enabled and bool(config.telegram_bot_token)
        self._start_time = datetime.utcnow()

    def set_orchestrator(self, orchestrator):
        """Give the command center access to the orchestrator for querying state."""
        self._orchestrator = orchestrator

    async def start(self):
        """Initialize the Telegram Application and start polling for commands."""
        if not self.enabled:
            logger.info("Telegram command center disabled")
            return

        self._app = (
            Application.builder()
            .token(self.config.telegram_bot_token)
            .build()
        )
        self._bot = self._app.bot

        # Register command handlers
        commands = {
            "start": self._cmd_help,
            "help": self._cmd_help,
            "status": self._cmd_status,
            "positions": self._cmd_positions,
            "pnl": self._cmd_pnl,
            "trades": self._cmd_trades,
            "strategies": self._cmd_strategies,
            "enable": self._cmd_enable,
            "disable": self._cmd_disable,
            "mode": self._cmd_mode,
            "risk": self._cmd_risk,
            "markets": self._cmd_markets,
            "pause": self._cmd_pause,
            "resume": self._cmd_resume,
            "cancel": self._cmd_cancel,
        }
        for name, handler in commands.items():
            self._app.add_handler(CommandHandler(name, handler))

        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)
        logger.info("Telegram command center started")

    async def stop(self):
        if self._app and self._app.updater.running:
            await self._app.updater.stop()
            await self._app.stop()
            await self._app.shutdown()

    # ── Auth ─────────────────────────────────────────────────────

    def _is_authorized(self, update: Update) -> bool:
        chat_id = str(update.effective_chat.id)
        return chat_id == self.config.telegram_chat_id

    # ── Commands ─────────────────────────────────────────────────

    async def _cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        await update.message.reply_text(
            "*Polymarket Bot Commands*\n\n"
            "/status — Bot mode, uptime, balance\n"
            "/positions — Open positions + PnL\n"
            "/pnl — Today's profit/loss\n"
            "/trades — Last 5 trades\n"
            "/strategies — Strategy list + status\n"
            "/enable `<name>` — Enable a strategy\n"
            "/disable `<name>` — Disable a strategy\n"
            "/mode `<dry_run|live>` — Switch mode\n"
            "/risk — Risk limits + usage\n"
            "/markets — Top watched markets\n"
            "/pause — Pause all trading\n"
            "/resume — Resume trading\n"
            "/cancel — Cancel open orders\n"
            "/help — This message",
            parse_mode="Markdown",
        )

    async def _cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        orch = self._orchestrator
        if not orch:
            await update.message.reply_text("Bot not initialized yet.")
            return

        uptime = datetime.utcnow() - self._start_time
        hours, remainder = divmod(int(uptime.total_seconds()), 3600)
        minutes, _ = divmod(remainder, 60)

        balance = orch.wallet.get_usdc_balance() if orch.wallet.address else orch.config.risk.initial_bankroll_usd
        strat_names = [s.name for s in orch.strategies]
        paused = "PAUSED" if orch.paused else "RUNNING"

        await update.message.reply_text(
            f"*Bot Status*\n"
            f"Mode: `{orch.config.mode}`\n"
            f"State: `{paused}`\n"
            f"Uptime: {hours}h {minutes}m\n"
            f"Balance: ${balance:.2f}\n"
            f"Strategies: {', '.join(strat_names) or 'None'}\n"
            f"Markets cached: {len(orch.market_data.markets)}",
            parse_mode="Markdown",
        )

    async def _cmd_positions(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        orch = self._orchestrator
        positions = await orch.db.get_positions()

        if not positions:
            await update.message.reply_text("No open positions.")
            return

        lines = ["*Open Positions*\n"]
        total_cost = 0
        for p in positions:
            cost = p["size"] * p["avg_entry_price"]
            total_cost += cost
            lines.append(
                f"• `{p['market_condition_id'][:8]}` "
                f"{p['size']:.1f} shares @ {p['avg_entry_price']:.3f} "
                f"(${cost:.2f})"
            )
        lines.append(f"\nTotal exposure: ${total_cost:.2f}")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _cmd_pnl(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        orch = self._orchestrator
        daily = await orch.db.get_daily_pnl()

        if not daily:
            await update.message.reply_text("No trading activity today.")
            return

        win_rate = (daily["winning_trades"] / daily["total_trades"] * 100) if daily["total_trades"] > 0 else 0
        await update.message.reply_text(
            f"*Today's PnL*\n"
            f"Realized: ${daily['realized_pnl']:+.2f}\n"
            f"Trades: {daily['total_trades']}\n"
            f"Wins: {daily['winning_trades']}\n"
            f"Win rate: {win_rate:.0f}%",
            parse_mode="Markdown",
        )

    async def _cmd_trades(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        orch = self._orchestrator
        trades = await orch.db.get_trades_today()
        trades = trades[:5]  # Last 5

        if not trades:
            await update.message.reply_text("No trades today.")
            return

        lines = ["*Recent Trades*\n"]
        for t in trades:
            mode = "DRY" if t["status"] == "dry_run" else t["status"].upper()
            lines.append(
                f"[{mode}] {t['strategy_name']}\n"
                f"  {t['side']} ${t['size_usd']:.2f} @ {t['fill_price']:.3f}\n"
                f"  _{t['market_question'][:50]}_\n"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _cmd_strategies(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        orch = self._orchestrator

        active = {s.name for s in orch.strategies}
        all_strats = {
            "resolution_hunting": orch.config.resolution_hunting.enabled,
            "copy_trading": orch.config.copy_trading.enabled,
            "sentiment": orch.config.sentiment.enabled,
            "arbitrage": orch.config.arbitrage.enabled,
        }

        lines = ["*Strategies*\n"]
        for name, cfg_enabled in all_strats.items():
            running = name in active
            if running:
                status = "RUNNING"
            elif cfg_enabled:
                status = "ENABLED (not loaded)"
            else:
                status = "DISABLED"
            lines.append(f"• `{name}` — {status}")

        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _cmd_enable(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        args = ctx.args
        if not args:
            await update.message.reply_text("Usage: /enable `<strategy_name>`", parse_mode="Markdown")
            return

        name = args[0].lower()
        orch = self._orchestrator

        # Check if already running
        if any(s.name == name for s in orch.strategies):
            await update.message.reply_text(f"`{name}` is already running.", parse_mode="Markdown")
            return

        try:
            strategy = self._load_strategy(name, orch)
            if strategy:
                await strategy.on_startup()
                orch.register_strategy(strategy)
                await update.message.reply_text(f"Enabled `{name}`", parse_mode="Markdown")
            else:
                await update.message.reply_text(
                    f"Unknown strategy: `{name}`\nAvailable: resolution_hunting, copy_trading, sentiment, arbitrage",
                    parse_mode="Markdown",
                )
        except Exception as e:
            await update.message.reply_text(f"Failed to enable `{name}`: {e}", parse_mode="Markdown")

    async def _cmd_disable(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        args = ctx.args
        if not args:
            await update.message.reply_text("Usage: /disable `<strategy_name>`", parse_mode="Markdown")
            return

        name = args[0].lower()
        orch = self._orchestrator

        strat = next((s for s in orch.strategies if s.name == name), None)
        if not strat:
            await update.message.reply_text(f"`{name}` is not running.", parse_mode="Markdown")
            return

        await strat.on_shutdown()
        orch.strategies.remove(strat)
        await update.message.reply_text(f"Disabled `{name}`", parse_mode="Markdown")

    async def _cmd_mode(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        args = ctx.args
        if not args or args[0] not in ("dry_run", "live"):
            await update.message.reply_text(
                f"Current mode: `{self._orchestrator.config.mode}`\n"
                f"Usage: /mode `<dry_run|live>`",
                parse_mode="Markdown",
            )
            return

        new_mode = args[0]
        old_mode = self._orchestrator.config.mode

        if new_mode == "live" and old_mode != "live":
            await update.message.reply_text(
                f"Switching to *LIVE* mode. Real money will be used.\n"
                f"Reply /mode live again to confirm.",
                parse_mode="Markdown",
            )
            # Use a simple state flag for confirmation
            if not hasattr(self, "_live_confirm"):
                self._live_confirm = True
                return
            del self._live_confirm

        self._orchestrator.config.mode = new_mode
        self._orchestrator.executor.config.mode = new_mode
        await update.message.reply_text(f"Mode switched to `{new_mode}`", parse_mode="Markdown")

    async def _cmd_risk(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        orch = self._orchestrator
        rc = orch.config.risk
        portfolio = await orch._build_portfolio()

        bankroll = rc.initial_bankroll_usd
        exposure_pct = (portfolio.total_exposure / bankroll * 100) if bankroll > 0 else 0
        daily_loss_pct = (abs(portfolio.daily_pnl) / bankroll * 100) if bankroll > 0 and portfolio.daily_pnl < 0 else 0

        await update.message.reply_text(
            f"*Risk Status*\n"
            f"Bankroll: ${bankroll:.2f}\n"
            f"Exposure: ${portfolio.total_exposure:.2f} ({exposure_pct:.0f}% / {rc.max_total_exposure_pct*100:.0f}% max)\n"
            f"Daily PnL: ${portfolio.daily_pnl:+.2f} ({daily_loss_pct:.1f}% / {rc.daily_loss_limit_pct*100:.0f}% max)\n"
            f"Max per market: {rc.max_position_pct*100:.0f}%\n"
            f"Max per trade: {rc.max_single_trade_pct*100:.0f}%\n"
            f"Min order: ${rc.min_order_size_usd:.2f}",
            parse_mode="Markdown",
        )

    async def _cmd_markets(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        orch = self._orchestrator
        markets = sorted(orch.market_data.markets, key=lambda m: m.volume_24h, reverse=True)[:5]

        if not markets:
            await update.message.reply_text("No markets cached. Wait for next tick.")
            return

        lines = ["*Top Markets (24h volume)*\n"]
        for m in markets:
            yes_p = m.outcome_prices[0]
            lines.append(
                f"• YES {yes_p:.0%} | ${m.volume_24h:,.0f}\n"
                f"  _{m.question[:60]}_\n"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

    async def _cmd_pause(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        self._orchestrator.paused = True
        await update.message.reply_text("Bot *paused*. Strategies will not scan. Use /resume to restart.", parse_mode="Markdown")

    async def _cmd_resume(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        self._orchestrator.paused = False
        await update.message.reply_text("Bot *resumed*. Scanning active.", parse_mode="Markdown")

    async def _cmd_cancel(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        if self._orchestrator.config.mode != "live":
            await update.message.reply_text("No open orders in dry\\_run mode.", parse_mode="Markdown")
            return
        try:
            self._orchestrator.clob.cancel_all_orders()
            await update.message.reply_text("All open orders cancelled.", parse_mode="Markdown")
        except Exception as e:
            await update.message.reply_text(f"Cancel failed: {e}")

    # ── Strategy Loader ──────────────────────────────────────────

    def _load_strategy(self, name: str, orch):
        """Dynamically load a strategy by name."""
        if name == "resolution_hunting":
            from strategies.resolution_hunting.strategy import ResolutionHuntingStrategy
            return ResolutionHuntingStrategy(orch.config.resolution_hunting, orch.market_data)
        elif name == "copy_trading":
            from strategies.copy_trading.strategy import CopyTradingStrategy
            return CopyTradingStrategy(orch.config.copy_trading, orch.config, orch.market_data, orch.db)
        elif name == "sentiment":
            from strategies.sentiment.strategy import SentimentStrategy
            return SentimentStrategy(orch.config.sentiment, orch.config, orch.market_data)
        elif name == "arbitrage":
            from strategies.arbitrage.strategy import ArbitrageStrategy
            return ArbitrageStrategy(orch.config.arbitrage, orch.market_data)
        return None

    # ── Outbound Notifications (same API as old Notifier) ────────

    async def send(self, message: str):
        if not self.enabled or not self._bot:
            return
        try:
            await self._bot.send_message(
                chat_id=self.config.telegram_chat_id,
                text=message,
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error("Failed to send Telegram message: %s", e)

    async def notify_trade(self, trade: Trade):
        if not self.config.notifications.notify_on_trade:
            return
        mode = "DRY" if trade.status == "dry_run" else "LIVE"
        msg = (
            f"*[{mode}] {trade.signal.strategy_name}*\n"
            f"{trade.signal.side} @ {trade.fill_price:.4f}\n"
            f"Size: ${trade.signal.size_usd:.2f}\n"
            f"Market: {trade.signal.market.question[:80]}\n"
            f"Reason: {trade.signal.reason[:100]}"
        )
        await self.send(msg)

    async def notify_error(self, error: str):
        if not self.config.notifications.notify_on_error:
            return
        await self.send(f"*ERROR*\n{error[:500]}")

    async def notify_startup(self, mode: str, balance: float):
        await self.send(
            f"*Bot Started*\n"
            f"Mode: {mode}\n"
            f"Balance: ${balance:.2f}\n"
            f"Send /help for commands"
        )

    async def notify_shutdown(self):
        await self.send("*Bot Stopped*")

    async def notify_daily_summary(self, pnl: float, trades: int, wins: int):
        win_rate = (wins / trades * 100) if trades > 0 else 0
        await self.send(
            f"*Daily Summary*\n"
            f"PnL: ${pnl:+.2f}\n"
            f"Trades: {trades}\n"
            f"Win rate: {win_rate:.0f}%"
        )
