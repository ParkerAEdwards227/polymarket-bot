import aiosqlite
import json
import logging
from datetime import datetime, date

logger = logging.getLogger("polybot.database")

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id TEXT PRIMARY KEY,
    signal_id TEXT NOT NULL,
    strategy_name TEXT NOT NULL,
    market_condition_id TEXT NOT NULL,
    market_question TEXT,
    token_id TEXT NOT NULL,
    side TEXT NOT NULL,
    target_price REAL,
    fill_price REAL,
    fill_size REAL,
    size_usd REAL,
    fees REAL DEFAULT 0,
    status TEXT NOT NULL,
    reason TEXT,
    confidence REAL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market_condition_id TEXT NOT NULL,
    token_id TEXT NOT NULL,
    size REAL NOT NULL,
    avg_entry_price REAL NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(market_condition_id, token_id)
);

CREATE TABLE IF NOT EXISTS daily_pnl (
    date TEXT PRIMARY KEY,
    realized_pnl REAL DEFAULT 0,
    unrealized_pnl REAL DEFAULT 0,
    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS whale_wallets (
    address TEXT PRIMARY KEY,
    label TEXT,
    weight REAL DEFAULT 1.0,
    total_trades INTEGER DEFAULT 0,
    winning_trades INTEGER DEFAULT 0,
    total_pnl REAL DEFAULT 0,
    last_trade_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS signals (
    id TEXT PRIMARY KEY,
    strategy_name TEXT NOT NULL,
    market_condition_id TEXT NOT NULL,
    token_id TEXT NOT NULL,
    side TEXT NOT NULL,
    target_price REAL,
    size_usd REAL,
    confidence REAL,
    reason TEXT,
    approved INTEGER DEFAULT 0,
    rejection_reason TEXT,
    created_at TEXT NOT NULL
);
"""


class Database:
    def __init__(self, db_path: str = "bot.db"):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def connect(self):
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA)
        await self._db.commit()
        logger.info("Database connected: %s", self.db_path)

    async def close(self):
        if self._db:
            await self._db.close()

    async def record_signal(self, signal, approved: bool, rejection_reason: str = ""):
        await self._db.execute(
            """INSERT OR REPLACE INTO signals
               (id, strategy_name, market_condition_id, token_id, side,
                target_price, size_usd, confidence, reason, approved,
                rejection_reason, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                signal.id,
                signal.strategy_name,
                signal.market.condition_id,
                signal.token_id,
                signal.side,
                signal.target_price,
                signal.size_usd,
                signal.confidence,
                signal.reason,
                int(approved),
                rejection_reason,
                signal.timestamp.isoformat(),
            ),
        )
        await self._db.commit()

    async def record_trade(self, trade):
        await self._db.execute(
            """INSERT OR REPLACE INTO trades
               (id, signal_id, strategy_name, market_condition_id, market_question,
                token_id, side, target_price, fill_price, fill_size, size_usd,
                fees, status, reason, confidence, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                trade.id,
                trade.signal.id,
                trade.signal.strategy_name,
                trade.signal.market.condition_id,
                trade.signal.market.question,
                trade.signal.token_id,
                trade.signal.side,
                trade.signal.target_price,
                trade.fill_price,
                trade.fill_size,
                trade.signal.size_usd,
                trade.fees,
                trade.status,
                trade.signal.reason,
                trade.signal.confidence,
                trade.timestamp.isoformat(),
            ),
        )
        await self._db.commit()

    async def update_position(self, market_condition_id: str, token_id: str, size: float, avg_price: float):
        now = datetime.utcnow().isoformat()
        if size <= 0:
            await self._db.execute(
                "DELETE FROM positions WHERE market_condition_id = ? AND token_id = ?",
                (market_condition_id, token_id),
            )
        else:
            await self._db.execute(
                """INSERT INTO positions (market_condition_id, token_id, size, avg_entry_price, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(market_condition_id, token_id)
                   DO UPDATE SET size = ?, avg_entry_price = ?, updated_at = ?""",
                (market_condition_id, token_id, size, avg_price, now, size, avg_price, now),
            )
        await self._db.commit()

    async def get_positions(self) -> list[dict]:
        cursor = await self._db.execute("SELECT * FROM positions WHERE size > 0")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_daily_pnl(self, day: date | None = None) -> dict | None:
        day = day or date.today()
        cursor = await self._db.execute(
            "SELECT * FROM daily_pnl WHERE date = ?", (day.isoformat(),)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def update_daily_pnl(self, realized: float, trade_won: bool):
        today = date.today().isoformat()
        existing = await self.get_daily_pnl()
        if existing:
            await self._db.execute(
                """UPDATE daily_pnl
                   SET realized_pnl = realized_pnl + ?,
                       total_trades = total_trades + 1,
                       winning_trades = winning_trades + ?
                   WHERE date = ?""",
                (realized, int(trade_won), today),
            )
        else:
            await self._db.execute(
                """INSERT INTO daily_pnl (date, realized_pnl, total_trades, winning_trades)
                   VALUES (?, ?, 1, ?)""",
                (today, realized, int(trade_won)),
            )
        await self._db.commit()

    async def get_trades_today(self) -> list[dict]:
        today = date.today().isoformat()
        cursor = await self._db.execute(
            "SELECT * FROM trades WHERE created_at >= ? ORDER BY created_at DESC",
            (today,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
