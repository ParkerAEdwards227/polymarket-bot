from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
import uuid


@dataclass
class Market:
    condition_id: str
    question: str
    slug: str
    tokens: list[dict]  # [{"token_id": ..., "outcome": "Yes"}, ...]
    end_date: str
    active: bool
    volume_24h: float = 0.0
    liquidity: float = 0.0
    category: str = ""
    outcome_prices: tuple[float, float] = (0.5, 0.5)  # (yes_price, no_price)

    @property
    def yes_token_id(self) -> str:
        for t in self.tokens:
            if t.get("outcome", "").lower() == "yes":
                return t["token_id"]
        return self.tokens[0]["token_id"] if self.tokens else ""

    @property
    def no_token_id(self) -> str:
        for t in self.tokens:
            if t.get("outcome", "").lower() == "no":
                return t["token_id"]
        return self.tokens[1]["token_id"] if len(self.tokens) > 1 else ""


@dataclass
class Signal:
    strategy_name: str
    market: Market
    side: Literal["BUY", "SELL"]
    token_id: str
    target_price: float
    size_usd: float
    confidence: float  # 0.0-1.0
    reason: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class Trade:
    signal: Signal
    order_id: str
    status: Literal["pending", "filled", "partial", "cancelled", "dry_run"]
    fill_price: float
    fill_size: float
    fees: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class Position:
    market_condition_id: str
    token_id: str
    size: float
    avg_entry_price: float
    current_price: float = 0.0

    @property
    def unrealized_pnl(self) -> float:
        return (self.current_price - self.avg_entry_price) * self.size

    @property
    def cost_basis(self) -> float:
        return self.avg_entry_price * self.size


@dataclass
class Portfolio:
    balance_usd: float = 0.0
    positions: list[Position] = field(default_factory=list)
    daily_pnl: float = 0.0

    @property
    def total_exposure(self) -> float:
        return sum(p.cost_basis for p in self.positions)

    @property
    def exposure_pct(self) -> float:
        total = self.balance_usd + self.total_exposure
        if total == 0:
            return 0.0
        return self.total_exposure / total
