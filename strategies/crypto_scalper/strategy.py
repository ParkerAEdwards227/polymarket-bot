import logging
import time
from datetime import datetime, timezone

from core.config import BotConfig
from core.models import Market, Signal
from services.market_data import MarketDataService
from strategies.base import BaseStrategy
from strategies.crypto_scalper.exchange_feed import BinanceFeed
from strategies.crypto_scalper.technical_analyzer import TechnicalAnalyzer
from strategies.crypto_scalper.claude_ev_calculator import ClaudeEVCalculator

logger = logging.getLogger("polybot.crypto_scalper")


class CryptoScalperStrategy(BaseStrategy):
    name = "crypto_scalper"

    def __init__(self, config, bot_config: BotConfig, market_data: MarketDataService):
        self.config = config
        self.bot_config = bot_config
        self.market_data = market_data
        self.feed = BinanceFeed(base_url=config.binance_base_url)
        self.ta = TechnicalAnalyzer()
        self.ev_calc = ClaudeEVCalculator(
            api_key=bot_config.anthropic_api_key,
            model=config.claude_model,
        )
        self._last_scan: float = 0

    async def on_startup(self):
        logger.info(
            "Crypto scalper started — assets=%s, interval=%ds, kelly=%.2f",
            self.config.target_assets,
            self.config.scan_interval_seconds,
            self.config.kelly_fraction,
        )

    async def on_shutdown(self):
        await self.feed.close()

    async def scan(self) -> list[Signal]:
        # Self-throttle to configured interval
        now = time.time()
        if now - self._last_scan < self.config.scan_interval_seconds:
            return []
        self._last_scan = now

        signals = []

        # STEP 1: Find crypto markets expiring in 2-20 minutes
        crypto_markets = self._find_crypto_markets()
        if not crypto_markets:
            return []

        logger.debug("Found %d crypto markets in window", len(crypto_markets))

        # STEP 2: Fetch exchange data for all target assets in parallel (~200ms)
        snapshots = await self.feed.get_all_snapshots(self.config.target_assets)
        if not snapshots:
            return []

        # STEP 3-6: Progressive analysis per market
        for market in crypto_markets:
            asset = self._extract_asset(market)
            if asset not in snapshots:
                continue

            snap = snapshots[asset]
            if not snap.candles_1m or len(snap.candles_1m) < 15:
                continue

            closes_1m = [c.close for c in snap.candles_1m]

            # STEP 3: Light TA check (fast, no I/O)
            quick_rsi = self.ta.compute_rsi(closes_1m)
            _, _, quick_macd_hist = self.ta.compute_macd(closes_1m)

            has_signal = quick_rsi < 35 or quick_rsi > 65 or abs(quick_macd_hist) > 0.001
            if not has_signal:
                continue

            # Quick spread check: does TA direction diverge from market price?
            yes_price = market.outcome_prices[0]
            is_bullish_q = self._is_bullish_question(market.question)
            ta_bullish = quick_rsi > 50 and quick_macd_hist > 0

            implied_prob = yes_price if is_bullish_q else (1 - yes_price)
            ta_implied = 0.7 if ta_bullish else 0.3
            spread = abs(ta_implied - implied_prob)

            if spread < 0.02:
                continue

            # STEP 4: Deep analysis — full TA + Claude EV
            ta_signal = self.ta.analyze(snap.candles_1m, snap.candles_5m)

            # Get orderbook
            token_id = market.yes_token_id if (ta_bullish == is_bullish_q) else market.no_token_id
            ob_summary = self._get_orderbook_summary(token_id)

            ev = await self.ev_calc.evaluate(
                market_question=market.question,
                polymarket_price=yes_price,
                spot_price=snap.spot_price,
                ta_signal=ta_signal,
                orderbook_summary=ob_summary,
            )

            if not ev:
                continue

            # STEP 5: Check edge and confidence thresholds
            if abs(ev.edge) < self.config.min_edge_pct:
                continue
            if ev.confidence < self.config.min_confidence:
                continue

            # Determine trade direction
            if ev.edge > 0:
                # YES is underpriced
                side_token_id = market.yes_token_id
                target_price = yes_price
            else:
                # NO is underpriced
                side_token_id = market.no_token_id
                target_price = market.outcome_prices[1]

            # STEP 6: Kelly sizing
            size = self._kelly_size(
                ev_probability=ev.probability if ev.edge > 0 else (1 - ev.probability),
                target_price=target_price,
            )
            size = min(size, self.config.max_position_usd)

            if size < self.bot_config.risk.min_order_size_usd:
                continue

            signal = Signal(
                strategy_name=self.name,
                market=market,
                side="BUY",
                token_id=side_token_id,
                target_price=target_price,
                size_usd=size,
                confidence=ev.confidence,
                reason=(
                    f"Scalp {asset}: edge {ev.edge:+.1%}, RSI={ta_signal.rsi:.0f}, "
                    f"MACD={'bull' if ta_signal.macd_histogram > 0 else 'bear'} — {ev.reasoning[:40]}"
                ),
            )
            signals.append(signal)

        if signals:
            logger.info(
                "Crypto scalper: %d signals (Claude calls this hour: %d)",
                len(signals), self.ev_calc.calls_this_hour,
            )
        return signals

    def _find_crypto_markets(self) -> list[Market]:
        """Filter cached markets to short-term crypto up/down markets expiring in 2-20 min."""
        now = datetime.now(timezone.utc)
        results = []

        for market in self.market_data.markets:
            if not market.active:
                continue

            # Must be crypto
            q = market.question.lower()
            slug = market.slug.lower()
            is_crypto = (
                market.category.lower() == "crypto"
                or any(kw in q for kw in ["btc", "bitcoin", "eth", "ethereum", "sol", "solana"])
                or any(kw in slug for kw in ["btc", "bitcoin", "eth", "ethereum", "sol", "solana"])
            )
            if not is_crypto:
                continue

            # Must expire within 2-20 minutes
            if not market.end_date:
                continue
            try:
                end_str = market.end_date.replace("Z", "+00:00")
                end = datetime.fromisoformat(end_str)
                minutes_left = (end - now).total_seconds() / 60
                if 2 <= minutes_left <= 20:
                    results.append(market)
            except (ValueError, TypeError):
                continue

        return results

    def _extract_asset(self, market: Market) -> str:
        """Extract 'BTC', 'ETH', or 'SOL' from market question/slug."""
        q = (market.question + " " + market.slug).lower()
        for asset in self.config.target_assets:
            if asset.lower() in q:
                return asset
        name_map = {"bitcoin": "BTC", "ethereum": "ETH", "solana": "SOL"}
        for name, ticker in name_map.items():
            if name in q and ticker in self.config.target_assets:
                return ticker
        return ""

    def _is_bullish_question(self, question: str) -> bool:
        """Determine if YES outcome = price goes UP."""
        q = question.lower()
        return any(kw in q for kw in ["above", "up", "over", "higher", "rise", "exceed", "more than"])

    def _kelly_size(self, ev_probability: float, target_price: float) -> float:
        """Quarter-Kelly position sizing based on Claude's probability estimate."""
        if target_price <= 0 or target_price >= 1:
            return 0
        odds = (1 - target_price) / target_price
        if odds <= 0:
            return 0
        kelly = (ev_probability * (1 + odds) - 1) / odds
        if kelly <= 0:
            return 0  # No edge according to Kelly
        fraction = self.config.kelly_fraction
        bankroll = self.config.allocation_pct * self.bot_config.risk.initial_bankroll_usd
        return kelly * fraction * bankroll

    def _get_orderbook_summary(self, token_id: str) -> dict:
        """Get orderbook depth summary for Claude prompt."""
        try:
            book = self.market_data.get_orderbook(token_id)
            bids = book.get("bids", [])
            asks = book.get("asks", [])
            bid_depth = sum(float(o.get("size", 0)) * float(o.get("price", 0)) for o in bids)
            ask_depth = sum(float(o.get("size", 0)) * float(o.get("price", 0)) for o in asks)
            best_bid = float(bids[0]["price"]) if bids else 0
            best_ask = float(asks[0]["price"]) if asks else 1
            return {"bid_depth": bid_depth, "ask_depth": ask_depth, "spread": best_ask - best_bid}
        except Exception:
            return {"bid_depth": 0, "ask_depth": 0, "spread": 0}
