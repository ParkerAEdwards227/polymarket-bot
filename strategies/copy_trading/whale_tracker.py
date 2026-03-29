import logging
import time
from dataclasses import dataclass
from typing import Any

from web3 import Web3

logger = logging.getLogger("polybot.copy_trading.whale_tracker")

# Polymarket CTF Exchange on Polygon
CTF_EXCHANGE_ADDRESS = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"

# OrderFilled event signature
ORDER_FILLED_TOPIC = Web3.keccak(
    text="OrderFilled(bytes32,address,address,uint256,uint256,uint256,uint256,uint256)"
).hex()


@dataclass
class WhaleTrade:
    wallet: str
    token_id: str
    side: str  # "BUY" or "SELL"
    size_usdc: float
    price: float
    timestamp: float
    tx_hash: str


class WhaleTracker:
    """Monitors Polygon for whale trades on the Polymarket CTF Exchange."""

    def __init__(
        self,
        polygon_rpc_url: str,
        tracked_wallets: list[dict],
        min_trade_usd: float = 500,
        max_delay_seconds: int = 300,
    ):
        self.tracked = {
            w["address"].lower(): w
            for w in tracked_wallets
        }
        self.min_trade_usd = min_trade_usd
        self.max_delay = max_delay_seconds
        self._w3: Web3 | None = None
        self._last_block: int = 0

        if polygon_rpc_url:
            self._w3 = Web3(Web3.HTTPProvider(polygon_rpc_url))

    def get_recent_trades(self) -> list[WhaleTrade]:
        """Poll for new whale trades since last check."""
        if not self._w3 or not self.tracked:
            return []

        try:
            current_block = self._w3.eth.block_number
            if self._last_block == 0:
                # Start from ~5 minutes ago (~150 blocks at 2s/block)
                self._last_block = max(current_block - 150, 0)

            # Don't scan too many blocks at once
            from_block = self._last_block + 1
            to_block = min(current_block, from_block + 500)

            if from_block > to_block:
                return []

            logs = self._w3.eth.get_logs({
                "fromBlock": from_block,
                "toBlock": to_block,
                "address": Web3.to_checksum_address(CTF_EXCHANGE_ADDRESS),
                "topics": [ORDER_FILLED_TOPIC],
            })

            self._last_block = to_block
            return self._parse_logs(logs)

        except Exception as e:
            logger.error("Failed to fetch whale trades: %s", e)
            return []

    def _parse_logs(self, logs: list) -> list[WhaleTrade]:
        trades = []
        now = time.time()

        for log in logs:
            try:
                # Decode the event data
                # OrderFilled(orderHash, maker, taker, makerAssetId, takerAssetId,
                #             makerAmountFilled, takerAmountFilled, fee)
                data = log["data"]
                if isinstance(data, str):
                    data = bytes.fromhex(data[2:])

                # Topics contain indexed params
                topics = log.get("topics", [])
                if len(topics) < 1:
                    continue

                # Extract maker and taker from data
                # Each field is 32 bytes in the data
                if len(data) < 256:
                    continue

                maker = "0x" + data[12:32].hex()
                taker = "0x" + data[44:64].hex()
                maker_asset_id = int.from_bytes(data[64:96], "big")
                taker_asset_id = int.from_bytes(data[96:128], "big")
                maker_amount = int.from_bytes(data[128:160], "big")
                taker_amount = int.from_bytes(data[160:192], "big")

                # Check if maker or taker is a tracked wallet
                maker_lower = maker.lower()
                taker_lower = taker.lower()

                wallet = None
                if maker_lower in self.tracked:
                    wallet = maker_lower
                    # Maker is selling maker_asset, buying taker_asset
                    side = "SELL"
                    token_id = str(maker_asset_id)
                    size = maker_amount / 1e6  # USDC decimals
                    price = taker_amount / maker_amount if maker_amount > 0 else 0
                elif taker_lower in self.tracked:
                    wallet = taker_lower
                    # Taker is buying maker_asset
                    side = "BUY"
                    token_id = str(maker_asset_id)
                    size = taker_amount / 1e6
                    price = maker_amount / taker_amount if taker_amount > 0 else 0

                if not wallet:
                    continue

                if size < self.min_trade_usd:
                    continue

                tx_hash = log.get("transactionHash", b"").hex()
                trade = WhaleTrade(
                    wallet=wallet,
                    token_id=token_id,
                    side=side,
                    size_usdc=size,
                    price=price,
                    timestamp=now,
                    tx_hash=tx_hash,
                )
                trades.append(trade)
                logger.info(
                    "Whale trade: %s %s $%.2f @ %.4f by %s",
                    side, token_id[:8], size, price,
                    self.tracked[wallet].get("label", wallet[:8]),
                )

            except Exception as e:
                logger.debug("Failed to parse log: %s", e)
                continue

        return trades
