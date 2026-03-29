import logging

from core.config import BotConfig
from core.models import Trade

logger = logging.getLogger("polybot.notifier")


class Notifier:
    """Telegram notification service."""

    def __init__(self, config: BotConfig):
        self.config = config
        self._bot = None
        self.enabled = config.notifications.telegram_enabled and bool(config.telegram_bot_token)

    async def connect(self):
        if not self.enabled:
            logger.info("Telegram notifications disabled")
            return
        try:
            from telegram import Bot
            self._bot = Bot(token=self.config.telegram_bot_token)
            logger.info("Telegram notifier connected")
        except ImportError:
            logger.warning("python-telegram-bot not installed — notifications disabled")
            self.enabled = False

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
            f"Balance: ${balance:.2f}"
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
