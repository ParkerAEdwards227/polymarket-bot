from abc import ABC, abstractmethod

from core.models import Signal, Trade


class BaseStrategy(ABC):
    """Plugin interface for all trading strategies."""

    name: str = "base"

    @abstractmethod
    async def scan(self) -> list[Signal]:
        """Scan markets and return trading signals. Called every tick."""
        ...

    async def on_fill(self, trade: Trade) -> None:
        """Called when an order from this strategy fills."""
        pass

    async def on_startup(self) -> None:
        """Called once at bot startup."""
        pass

    async def on_shutdown(self) -> None:
        """Called on graceful shutdown."""
        pass
