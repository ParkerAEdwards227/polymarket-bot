import logging
from datetime import datetime

from core.database import Database

logger = logging.getLogger("polybot.copy_trading.scorer")


class WalletScorer:
    """Tracks whale wallet performance and computes dynamic allocation weights."""

    def __init__(self, db: Database, wallets: list[dict]):
        self.db = db
        self.wallets = {w["address"].lower(): w for w in wallets}

    async def initialize(self):
        """Ensure all tracked wallets are in the database."""
        for addr, info in self.wallets.items():
            await self.db._db.execute(
                """INSERT OR IGNORE INTO whale_wallets
                   (address, label, weight, total_trades, winning_trades, total_pnl, updated_at)
                   VALUES (?, ?, ?, 0, 0, 0, ?)""",
                (addr, info.get("label", ""), info.get("weight", 1.0), datetime.utcnow().isoformat()),
            )
        await self.db._db.commit()

    async def record_whale_trade(self, address: str, pnl: float = 0, won: bool = False):
        """Update a whale's performance stats."""
        addr = address.lower()
        now = datetime.utcnow().isoformat()
        await self.db._db.execute(
            """UPDATE whale_wallets
               SET total_trades = total_trades + 1,
                   winning_trades = winning_trades + ?,
                   total_pnl = total_pnl + ?,
                   last_trade_at = ?,
                   updated_at = ?
               WHERE address = ?""",
            (int(won), pnl, now, now, addr),
        )
        await self.db._db.commit()

    async def get_weight(self, address: str) -> float:
        """Get the allocation weight for a whale wallet.

        Combines the configured base weight with performance-based adjustment.
        """
        addr = address.lower()
        base_weight = self.wallets.get(addr, {}).get("weight", 1.0)

        cursor = await self.db._db.execute(
            "SELECT total_trades, winning_trades, total_pnl FROM whale_wallets WHERE address = ?",
            (addr,),
        )
        row = await cursor.fetchone()
        if not row or row[0] < 5:
            # Not enough data — use base weight
            return base_weight

        total, wins, pnl = row[0], row[1], row[2]
        win_rate = wins / total if total > 0 else 0.5

        # Performance multiplier: 0.5x to 2.0x based on win rate
        perf_mult = max(0.5, min(2.0, win_rate * 2))

        return base_weight * perf_mult

    async def get_all_weights(self) -> dict[str, float]:
        """Get normalized weights for all tracked wallets."""
        weights = {}
        for addr in self.wallets:
            weights[addr] = await self.get_weight(addr)

        # Normalize so they sum to 1.0
        total = sum(weights.values())
        if total > 0:
            weights = {k: v / total for k, v in weights.items()}

        return weights
