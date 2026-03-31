import json
import logging
import time
from dataclasses import dataclass

import anthropic

from strategies.crypto_scalper.technical_analyzer import TASignal

logger = logging.getLogger("polybot.crypto_scalper.ev")


@dataclass
class EVEstimate:
    probability: float  # 0.0-1.0 (Claude's estimate of true probability)
    confidence: float  # 0.0-1.0
    edge: float  # probability - implied_probability (signed)
    reasoning: str


class ClaudeEVCalculator:
    """Deep EV analysis via Claude API. Called only after light TA check passes."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        self.model = model
        self._client = anthropic.AsyncAnthropic(api_key=api_key) if api_key else None
        self._call_count = 0
        self._last_reset = time.time()

    async def evaluate(
        self,
        market_question: str,
        polymarket_price: float,
        spot_price: float,
        ta_signal: TASignal,
        orderbook_summary: dict,
    ) -> EVEstimate | None:
        if not self._client:
            return None

        prompt = (
            "You are a quantitative crypto-prediction-market analyst. Given market data for a "
            "short-term crypto binary option on Polymarket, estimate the TRUE probability of the outcome.\n\n"
            f"MARKET: {market_question}\n"
            f"CURRENT POLYMARKET PRICE (implied probability): {polymarket_price:.1%}\n\n"
            f"LIVE EXCHANGE DATA:\n"
            f"- Spot price: ${spot_price:,.2f}\n"
            f"- RSI (14, 1m): {ta_signal.rsi:.1f}\n"
            f"- MACD histogram: {ta_signal.macd_histogram:+.6f}\n"
            f"- MACD cross: {ta_signal.macd_cross}\n"
            f"- VWAP deviation: {ta_signal.vwap_deviation:+.4%}\n"
            f"- Bollinger position: {ta_signal.bb_position:.2f} (0=lower, 1=upper)\n"
            f"- Bollinger width: {ta_signal.bb_width:.4f}\n\n"
            f"ORDER BOOK:\n"
            f"- Total bid depth: ${orderbook_summary.get('bid_depth', 0):.0f}\n"
            f"- Total ask depth: ${orderbook_summary.get('ask_depth', 0):.0f}\n"
            f"- Spread: {orderbook_summary.get('spread', 0):.4f}\n\n"
            "Based ONLY on the technical indicators and order flow, estimate the probability that "
            "this market resolves YES. Focus on momentum, mean-reversion signals, and any "
            "divergence between the TA signals and the current Polymarket price.\n\n"
            'Respond in JSON ONLY:\n'
            '{"probability": <float 0.0-1.0>, "confidence": <float 0.0-1.0>, "reasoning": "<30 words max>"}'
        )

        try:
            response = await self._client.messages.create(
                model=self.model,
                max_tokens=150,
                messages=[{"role": "user", "content": prompt}],
                timeout=5.0,
            )

            text = response.content[0].text.strip()
            # Extract JSON from response
            if "```" in text:
                text = text.split("```")[1].strip()
                if text.startswith("json"):
                    text = text[4:].strip()

            data = json.loads(text)
            prob = float(data["probability"])
            conf = float(data["confidence"])
            edge = prob - polymarket_price

            self._call_count += 1
            estimate = EVEstimate(
                probability=prob,
                confidence=conf,
                edge=edge,
                reasoning=data.get("reasoning", ""),
            )
            logger.info(
                "EV estimate for '%s': prob=%.1f%% conf=%.0f%% edge=%+.1f%% — %s",
                market_question[:40],
                prob * 100,
                conf * 100,
                edge * 100,
                estimate.reasoning[:60],
            )
            return estimate

        except json.JSONDecodeError as e:
            logger.warning("Claude returned non-JSON: %s", e)
            return None
        except Exception as e:
            logger.error("Claude EV calculation failed: %s", e)
            return None

    @property
    def calls_this_hour(self) -> int:
        now = time.time()
        if now - self._last_reset > 3600:
            self._call_count = 0
            self._last_reset = now
        return self._call_count
