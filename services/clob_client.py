import logging
from typing import Any

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY, SELL

from core.config import BotConfig

logger = logging.getLogger("polybot.clob")


class PolymarketCLOB:
    """Wrapper around the official py-clob-client SDK."""

    def __init__(self, config: BotConfig):
        self.config = config
        self._client: ClobClient | None = None

    def connect(self):
        if not self.config.private_key:
            logger.warning("No private key configured — CLOB client will not be initialized")
            return

        self._client = ClobClient(
            host=self.config.clob_host,
            key=self.config.private_key,
            chain_id=self.config.chain_id,
            signature_type=self.config.signature_type,
            funder=self.config.funder_address or None,
        )
        creds = self._client.create_or_derive_api_creds()
        self._client.set_api_creds(creds)
        logger.info("CLOB client connected (chain_id=%d)", self.config.chain_id)

    @property
    def client(self) -> ClobClient:
        if self._client is None:
            raise RuntimeError("CLOB client not initialized. Call connect() first or set PRIVATE_KEY.")
        return self._client

    def get_orderbook(self, token_id: str) -> dict:
        return self.client.get_order_book(token_id)

    def get_price(self, token_id: str, side: str = "BUY") -> float | None:
        try:
            price = self.client.get_price(token_id, side)
            return float(price) if price else None
        except Exception as e:
            logger.error("Failed to get price for %s: %s", token_id, e)
            return None

    def get_midpoint(self, token_id: str) -> float | None:
        try:
            mid = self.client.get_midpoint(token_id)
            return float(mid) if mid else None
        except Exception as e:
            logger.error("Failed to get midpoint for %s: %s", token_id, e)
            return None

    def create_and_post_limit_order(
        self,
        token_id: str,
        price: float,
        size: float,
        side: str = "BUY",
    ) -> dict:
        order_side = BUY if side.upper() == "BUY" else SELL
        order_args = OrderArgs(
            price=price,
            size=size,
            side=order_side,
            token_id=token_id,
        )
        signed = self.client.create_order(order_args)
        result = self.client.post_order(signed, OrderType.GTC)
        logger.info(
            "Posted limit order: %s %s @ %.4f x %.2f → %s",
            side, token_id[:8], price, size, result.get("orderID", "?"),
        )
        return result

    def create_and_post_market_order(
        self,
        token_id: str,
        amount: float,
        side: str = "BUY",
    ) -> dict:
        order_side = BUY if side.upper() == "BUY" else SELL
        order_args = OrderArgs(
            price=0.0,  # market order
            size=amount,
            side=order_side,
            token_id=token_id,
        )
        signed = self.client.create_order(order_args)
        result = self.client.post_order(signed, OrderType.FOK)
        logger.info(
            "Posted market order: %s %s x %.2f → %s",
            side, token_id[:8], amount, result.get("orderID", "?"),
        )
        return result

    def cancel_order(self, order_id: str) -> dict:
        return self.client.cancel(order_id)

    def cancel_all_orders(self) -> dict:
        return self.client.cancel_all()

    def get_open_orders(self) -> list[dict]:
        try:
            return self.client.get_orders() or []
        except Exception as e:
            logger.error("Failed to get open orders: %s", e)
            return []
